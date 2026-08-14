#!/usr/bin/env bash
# Step 4: ラスタータイルを生成する。
#
#   TILE_OUTPUT="dir"     … gdal2tiles で XYZ ディレクトリを作る（既定）
#   TILE_OUTPUT="pmtiles" … rio-mbtiles で MBTiles を作り PMTiles に変換する
#
# Usage: scripts/04_make_tiles.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"

step "Step 4: タイル生成（$DATASET_ID / 出力形態: $TILE_OUTPUT）"

[ -f "$VRT_FILE" ] || die "VRT がありません。先に scripts/03_build_vrt.sh を実行してください"

# --- 最大ZL ------------------------------------------------------------------
max_zoom="$MAX_ZOOM"
if [ "$max_zoom" = "auto" ]; then
  max_zoom="$(inspect_value recommended_max_zoom)"
  [ -n "$max_zoom" ] || die "最大ZLを自動決定できません。設定で MAX_ZOOM を明示してください"
  log "最大ZL: ZL$max_zoom（GSD $(inspect_value gsd) m/px から自動決定）"
else
  log "最大ZL: ZL$max_zoom（設定で明示）"
fi
[ "$MIN_ZOOM" -le "$max_zoom" ] || die "MIN_ZOOM($MIN_ZOOM) が最大ZL($max_zoom) を超えています"

# --- CRS ---------------------------------------------------------------------
src_srs="$(resolve_srs)"
[ -n "$src_srs" ] || die "入力 CRS が不明です。設定で SRC_SRS を指定してください"

# --- NoData ------------------------------------------------------------------
# 前処理でアルファバンドを付けている場合は後段での指定は不要。
nodata="$(resolve_nodata)"

# =============================================================================
# TILE_OUTPUT="dir": gdal2tiles で XYZ ディレクトリを生成
# =============================================================================
make_tiles_dir() {
  require_cmd gdal2tiles

  local driver_args=()
  case "$TILE_FORMAT" in
    webp)
      driver_args=(--tiledriver=WEBP)
      if [ "$WEBP_QUALITY" = "lossless" ]; then
        driver_args+=(--webp-lossless)
        log "出力形式: WebP（可逆）"
      else
        driver_args+=(--webp-quality="$WEBP_QUALITY")
        log "出力形式: WebP（非可逆 品質$WEBP_QUALITY）"
      fi
      ;;
    png) log "出力形式: PNG" ;;
    *)   die "TILE_FORMAT は webp または png を指定してください（現在: $TILE_FORMAT）" ;;
  esac

  local nodata_args=()
  if [ -z "$nodata" ]; then
    log "NoData: 透過処理なし"
  elif [ -d "$PREPARED_DIR" ]; then
    log "NoData: 前処理済みのアルファバンドを使用"
  else
    nodata_args=(--srcnodata="${nodata// /,}")
    log "NoData: gdal2tiles で ${nodata} を透過扱い"
  fi

  local resume_args=()
  if [ "$RESUME" = "true" ]; then
    resume_args=(-e)
    log "再開モード: 既存タイルを残し不足分のみ生成"
  fi

  log "ZL範囲: $MIN_ZOOM-$max_zoom / CRS: $src_srs / 並列: $JOBS"

  gdal2tiles \
    "${resume_args[@]}" \
    --s_srs "$src_srs" \
    --xyz \
    -z "${MIN_ZOOM}-${max_zoom}" \
    --processes="$JOBS" \
    --resampling="$RESAMPLING" \
    -x \
    -w none \
    "${nodata_args[@]}" \
    "${driver_args[@]}" \
    "$VRT_FILE" \
    "$TILES_DIR"

  local ext="$TILE_FORMAT" tile_count total_bytes
  tile_count="$(find "$TILES_DIR" -name "*.${ext}" | wc -l)"
  total_bytes="$(find "$TILES_DIR" -name "*.${ext}" -printf '%s\n' | awk '{s+=$1} END{print s+0}')"
  log "タイル生成完了: ${tile_count} 枚 / $(awk "BEGIN{printf \"%.1f\", $total_bytes/1024/1024}") MB → $TILES_DIR"

  cat > "$WORK_DIR/tiles_meta.json" <<EOF
{
  "dataset_id": "$DATASET_ID",
  "output": "dir",
  "min_zoom": $MIN_ZOOM,
  "max_zoom": $max_zoom,
  "format": "$TILE_FORMAT",
  "tile_count": $tile_count,
  "total_bytes": $total_bytes
}
EOF
}

# =============================================================================
# TILE_OUTPUT="pmtiles": rio-mbtiles → MBTiles → pmtiles convert
# =============================================================================
# gdal2tiles を使わないのは、gdal_translate -of MBTILES では最大ZL を指定できず
# （GDAL 3.11 の MBTiles ドライバに ZOOM_LEVEL 作成オプションが無い）、
# MAX_ZOOM の設定を尊重できないため。rio-mbtiles は --zoom-levels で明示できる。
make_tiles_pmtiles() {
  require_cmd rio pmtiles python3 gdalinfo

  local fmt co_args=()
  case "$TILE_FORMAT" in
    webp)
      fmt="WEBP"
      if [ "$WEBP_QUALITY" = "lossless" ]; then
        co_args=(--co LOSSLESS=TRUE)
        log "出力形式: WebP（可逆）"
      else
        co_args=(--co "QUALITY=$WEBP_QUALITY")
        log "出力形式: WebP（非可逆 品質$WEBP_QUALITY）"
      fi
      ;;
    png) fmt="PNG"; log "出力形式: PNG" ;;
    *)   die "TILE_FORMAT は webp または png を指定してください（現在: $TILE_FORMAT）" ;;
  esac

  # リサンプリング名は gdal2tiles と rasterio で綴りが違うものがある
  local resampling="$RESAMPLING"
  case "$resampling" in
    near)        resampling="nearest" ;;
    cubicspline) resampling="cubic_spline" ;;
    antialias)   die "RESAMPLING=antialias は TILE_OUTPUT=pmtiles では使えません（rasterio に相当する方式が無い）" ;;
  esac

  # アルファバンドの有無で --rgba を切り替える（rio-mbtiles は 3 バンド以上が必須）
  local band_count rgba_args=()
  band_count="$(gdalinfo "$VRT_FILE" | grep -c '^Band ')"
  [ "$band_count" -ge 3 ] || die "rio-mbtiles は 3 バンド以上が必要です（現在: ${band_count} バンド）"
  if [ "$band_count" -ge 4 ]; then
    rgba_args=(--rgba)
    log "透過: 第4バンドを --rgba で出力（整備範囲の外側も透過になる）"
  elif [ -n "$nodata" ]; then
    warn "NoData（$nodata）が指定されていますが VRT は ${band_count} バンドです。"
    warn "  rio-mbtiles の --src-nodata は単一値のみで RGB の色指定を受け付けません。"
    warn "  透過させる場合は Step 2 の前処理でアルファバンドを付けてください。"
  else
    log "NoData: 透過処理なし"
  fi

  [ "$RESUME" = "true" ] && warn "RESUME=true は TILE_OUTPUT=pmtiles では無視されます（毎回作り直します）"

  log "ZL範囲: $MIN_ZOOM-$max_zoom / CRS: $src_srs / 並列: $JOBS"

  # rio-mbtiles 1.6.0 のバグ回避:
  # --overwrite（既定）かつ出力ファイルが存在しないと、内部の `appending` が
  # どの分岐でも代入されないまま参照され NameError で落ちる。
  # 空ファイルを先に置いて「存在する」状態にすると上書き経路に入り正常動作する。
  rm -f "$MBTILES_FILE"
  : > "$MBTILES_FILE"

  rio mbtiles "$VRT_FILE" "$MBTILES_FILE" \
    --overwrite \
    --format "$fmt" \
    "${co_args[@]}" \
    --zoom-levels "${MIN_ZOOM}..${max_zoom}" \
    --resampling "$resampling" \
    --tile-size 256 \
    -j "$JOBS" \
    --title "$DATASET_NAME" \
    --description "$DATASET_NAME" \
    "${rgba_args[@]}"

  # PMTiles 変換前に metadata を整える（go-pmtiles の center 桁あふれ回避を含む）
  local mb_min_zoom mb_max_zoom mb_zoom_levels mb_tile_count mb_total_bytes
  local mb_center mb_center_overflow_avoided
  eval "$(python3 "$REPO_ROOT/tools/mbtiles_meta.py" \
    --mbtiles "$MBTILES_FILE" \
    --name "$DATASET_NAME" \
    --description "$DATASET_NAME" \
    --attribution "$ATTRIBUTION" \
    --center-zoom "$MIN_ZOOM")"

  log "MBTiles: ${mb_tile_count} 枚 / ZL ${mb_zoom_levels} / $(awk "BEGIN{printf \"%.1f\", $mb_total_bytes/1024/1024}") MB"
  if [ "$mb_center_overflow_avoided" = "true" ]; then
    log "center=${mb_center} を明示（go-pmtiles の桁あふれ回避）"
  fi

  rm -f "$PMTILES_FILE"
  pmtiles convert "$MBTILES_FILE" "$PMTILES_FILE"

  local pm_bytes
  pm_bytes="$(stat -c '%s' "$PMTILES_FILE")"
  log "PMTiles 生成完了: $(awk "BEGIN{printf \"%.1f\", $pm_bytes/1024/1024}") MB → $PMTILES_FILE"

  if [ "$PMTILES_KEEP_MBTILES" = "true" ]; then
    log "中間 MBTiles を残しました（PMTILES_KEEP_MBTILES=false で削除）: $MBTILES_FILE"
  else
    rm -f "$MBTILES_FILE"
    log "中間 MBTiles を削除しました"
  fi

  cat > "$WORK_DIR/tiles_meta.json" <<EOF
{
  "dataset_id": "$DATASET_ID",
  "output": "pmtiles",
  "pmtiles_file": "$(basename "$PMTILES_FILE")",
  "min_zoom": $mb_min_zoom,
  "max_zoom": $mb_max_zoom,
  "format": "$TILE_FORMAT",
  "tile_count": $mb_tile_count,
  "total_bytes": $pm_bytes
}
EOF
}

case "$TILE_OUTPUT" in
  dir)     make_tiles_dir ;;
  pmtiles) make_tiles_pmtiles ;;
esac
