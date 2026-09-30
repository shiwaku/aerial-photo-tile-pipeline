#!/usr/bin/env bash
# Step 4: ラスタータイルを生成する。
#
#   TILE_OUTPUT="dir"     … XYZ ディレクトリを作る（既定）
#   TILE_OUTPUT="pmtiles" … PMTILES_VIA で作り方が変わる
#       gdal2tiles（既定） … XYZ を作ってから PMTiles を直接書き出す
#                           （名前は歴史的経緯。実際は gdal raster tile を優先して使う）
#       rio-mbtiles       … MBTiles を作り pmtiles convert で変換する
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
# XYZ ディレクトリを生成する（dir 出力と PMTiles 経路の共通処理）
# 生成枚数と総バイト数を xyz_tile_count / xyz_total_bytes に入れて返す。
#
# `gdal raster tile`（GDAL 3.11 で追加）が使えればそれを直接呼ぶ。GDAL 3.13 の
# gdal2tiles は内部で同じ処理を Python から呼ぶが、その経路では --processes を
# 渡しても 1 本でしか動かない（プロセス・スレッドとも 1、CPU 100%）。CLI は gdal
# 実行ファイルを子プロセスにして並列化する（--parallel-method の既定は spawn 優先）が、
# Python 内からはそれができないためと見ている。入力が大きいほど差が開く。
# 静岡サンプル 25 図郭・ZL9-19・8 並列で 13.1 秒 → 5.9 秒。
# --legacy（Python の multiprocessing）は重く、GDAL 3.15 で削除予定なので使わない。
# 出力はほぼ同一（同サンプル 1,139 枚中 1,121 枚がバイト一致。残りは図郭の境目で
# わずかに違う。gdal raster tile 同士でも -j 1 と -j 8 で同程度の差が出る）。
# 使うオプションが揃っていない GDAL は従来どおり gdal2tiles（古い版は並列が効く）。
# =============================================================================
generate_xyz_tiles() {
  local use_raster_tile=false rt_help
  rt_help="$(gdal raster tile --help 2>/dev/null || true)"
  if grep -q -- '--skip-blank' <<<"$rt_help" \
     && grep -q -- '--webviewer' <<<"$rt_help" \
     && grep -q -- '--resume' <<<"$rt_help"; then
    use_raster_tile=true
  else
    require_cmd gdal2tiles
  fi

  # g2t_* は gdal2tiles 用、rt_* は gdal raster tile 用
  local g2t_driver_args=() rt_driver_args=()
  case "$TILE_FORMAT" in
    webp)
      g2t_driver_args=(--tiledriver=WEBP)
      rt_driver_args=(-f WEBP)
      if [ "$WEBP_QUALITY" = "lossless" ]; then
        g2t_driver_args+=(--webp-lossless)
        rt_driver_args+=(--co LOSSLESS=YES)
        log "出力形式: WebP（可逆）"
      else
        g2t_driver_args+=(--webp-quality="$WEBP_QUALITY")
        rt_driver_args+=(--co QUALITY="$WEBP_QUALITY")
        log "出力形式: WebP（非可逆 品質$WEBP_QUALITY）"
      fi
      ;;
    png)
      rt_driver_args=(-f PNG)
      log "出力形式: PNG"
      ;;
    *)   die "TILE_FORMAT は webp または png を指定してください（現在: $TILE_FORMAT）" ;;
  esac

  local srcnodata=""
  if [ -z "$nodata" ]; then
    log "NoData: 透過処理なし"
  elif [ -d "$PREPARED_DIR" ]; then
    log "NoData: 前処理済みのアルファバンドを使用"
  else
    srcnodata="${nodata// /,}"
    log "NoData: タイル生成時に ${nodata} を透過扱い"
  fi

  if [ "$RESUME" = "true" ]; then
    log "再開モード: 既存タイルを残し不足分のみ生成"
  fi

  log "ZL範囲: $MIN_ZOOM-$max_zoom / CRS: $src_srs / 並列: $JOBS"

  if [ "$use_raster_tile" = "true" ]; then
    log "タイル生成: gdal raster tile"
    # gdal raster tile には入力 CRS・NoData の指定が無いので、gdal2tiles が内部で
    # やっているのと同じ gdal.Translate で CRS と NoData を付けた VRT を挟む
    local tile_input="$WORK_DIR/tile_input.vrt"
    python3 -c "
import sys
from osgeo import gdal
gdal.UseExceptions()
gdal.Translate(sys.argv[2], sys.argv[1], format='VRT', outputSRS=sys.argv[3],
               noData=sys.argv[4] or None)
" "$VRT_FILE" "$tile_input" "$src_srs" "$srcnodata"

    local rt_args=()
    [ "$RESUME" = "true" ] && rt_args+=(--resume)
    gdal raster tile \
      "${rt_args[@]}" \
      --min-zoom "$MIN_ZOOM" \
      --max-zoom "$max_zoom" \
      -j "$JOBS" \
      -r "$RESAMPLING" \
      --skip-blank \
      --webviewer none \
      "${rt_driver_args[@]}" \
      "$tile_input" \
      "$TILES_DIR"
    rm -f "$tile_input"
  else
    log "タイル生成: gdal2tiles（gdal raster tile が無いか、必要なオプションが無い GDAL）"
    local g2t_args=()
    [ "$RESUME" = "true" ] && g2t_args+=(-e)
    [ -n "$srcnodata" ] && g2t_args+=(--srcnodata="$srcnodata")
    gdal2tiles \
      "${g2t_args[@]}" \
      --s_srs "$src_srs" \
      --xyz \
      -z "${MIN_ZOOM}-${max_zoom}" \
      --processes="$JOBS" \
      --resampling="$RESAMPLING" \
      -x \
      -w none \
      "${g2t_driver_args[@]}" \
      "$VRT_FILE" \
      "$TILES_DIR"
  fi

  local ext="$TILE_FORMAT"
  xyz_tile_count="$(find "$TILES_DIR" -name "*.${ext}" | wc -l)"
  xyz_total_bytes="$(find "$TILES_DIR" -name "*.${ext}" -printf '%s\n' | awk '{s+=$1} END{print s+0}')"
  log "タイル生成完了: ${xyz_tile_count} 枚 / $(awk "BEGIN{printf \"%.1f\", $xyz_total_bytes/1024/1024}") MB → $TILES_DIR"

  check_tiles --tiles-dir "$TILES_DIR" --format "$ext"
}

# 生成物の抜き取り検査。整備範囲の穴が透過せず「不透明な黒」になっていないか見る。
# 速度だけ測って正しさを見ないまま本番を流し、4時間かけて作り直した経緯がある。
check_tiles() {
  local check_sampled check_black_ratio check_transparent_ratio check_ok
  eval "$(python3 "$REPO_ROOT/tools/check_tiles.py" "$@")"
  if [ "$check_ok" = "unknown" ]; then
    warn "検査: タイルを読み取れず確認できませんでした"
    return
  fi
  log "検査: ${check_sampled} 枚を抜き取り / 不透明な黒 ${check_black_ratio}% / 透過 ${check_transparent_ratio}%"
  if [ "$check_ok" != "true" ]; then
    warn "不透明な黒が多すぎます（${check_black_ratio}%）。整備範囲の穴が透過していない可能性があります。"
    warn "  VRT にアルファバンドがあるか確認してください（Step 3 の -addalpha）:"
    warn "    gdalinfo $VRT_FILE | grep '^Band '"
  fi
}

# =============================================================================
# TILE_OUTPUT="dir": XYZ ディレクトリをそのまま成果物にする
# =============================================================================
make_tiles_dir() {
  generate_xyz_tiles

  cat > "$WORK_DIR/tiles_meta.json" <<EOF
{
  "dataset_id": "$DATASET_ID",
  "output": "dir",
  "min_zoom": $MIN_ZOOM,
  "max_zoom": $max_zoom,
  "format": "$TILE_FORMAT",
  "tile_count": $xyz_tile_count,
  "total_bytes": $xyz_total_bytes
}
EOF
}

# =============================================================================
# PMTiles 経路B 用: MBTiles の metadata を整えてから pmtiles convert する
# =============================================================================
# 引数で受けた MBTiles を PMTiles にする。tiles_meta.json もここで書く。
# 経路A（既定）は MBTiles を作らないのでこの関数を通らない。
finalize_pmtiles() {
  local tile_count_hint="$1"

  local mb_min_zoom mb_max_zoom mb_zoom_levels mb_tile_count mb_total_bytes
  local mb_center mb_center_overflow_avoided mb_bounds_derived
  eval "$(python3 "$REPO_ROOT/tools/mbtiles_meta.py" \
    --mbtiles "$MBTILES_FILE" \
    --name "$DATASET_NAME" \
    --description "$DATASET_NAME" \
    --attribution "$ATTRIBUTION" \
    --format "$TILE_FORMAT" \
    --center-zoom "$MIN_ZOOM")"

  log "MBTiles: ${mb_tile_count} 枚 / ZL ${mb_zoom_levels} / $(awk "BEGIN{printf \"%.1f\", $mb_total_bytes/1024/1024}") MB"
  [ "$mb_bounds_derived" = "true" ] && log "bounds をタイル座標から逆算（mb-util は metadata を書かないため）"
  [ "$mb_center_overflow_avoided" = "true" ] && log "center=${mb_center} を明示（go-pmtiles の桁あふれ回避）"

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
  "via": "$PMTILES_VIA",
  "pmtiles_file": "$(basename "$PMTILES_FILE")",
  "min_zoom": $mb_min_zoom,
  "max_zoom": $mb_max_zoom,
  "format": "$TILE_FORMAT",
  "tile_count": $mb_tile_count,
  "total_bytes": $pm_bytes
}
EOF
}

# =============================================================================
# PMTiles 経路A（既定）: XYZ タイル生成 → PMTiles 直接書き出し
# =============================================================================
# 実測でこちらが速い。gdal raster tile / gdal2tiles は最大ZLを作ってからピラミッドを縮小で積むが、
# rio-mbtiles は ZL ごとに元データから warp し直すため低ZLが重くなる。
# 400図郭での実測: 経路A 422秒 / 経路B 1,133秒（成果物はどちらも 325MB）。
# 代償として中間の XYZ ディレクトリ（大量の小ファイル）を一度作る。
#
# 以前は mb-util で MBTiles を作ってから pmtiles convert していた。中間の SQLite は
# convert の入力を作るためだけに存在し、mb-util の VACUUM（捨てるファイルを整理する
# だけ）と convert（一度入れたものを読み直すだけ）が丸ごと無駄だった。
# 本番 366,827 枚での実測: 65分30秒 → 22分16秒。出力はバイト単位で同一
# （全11ZLから2,475枚を抽出して相違ゼロ）。mb-util への依存も消えた。
make_tiles_pmtiles_via_gdal2tiles() {
  require_cmd python3

  generate_xyz_tiles

  local pm_tile_count pm_unique_tiles pm_source_bytes pm_bytes
  local pm_min_zoom pm_max_zoom pm_zoom_levels pm_center pm_bounds
  local pm_clustered pm_elapsed

  log "PMTiles へ直接書き出し中…"
  rm -f "$PMTILES_FILE"
  eval "$(python3 "$REPO_ROOT/tools/dir_to_pmtiles.py" \
    --tiles-dir "$TILES_DIR" \
    --output "$PMTILES_FILE" \
    --format "$TILE_FORMAT" \
    --name "$DATASET_NAME" \
    --description "$DATASET_NAME" \
    --attribution "$ATTRIBUTION" \
    --center-zoom "$MIN_ZOOM")"

  log "PMTiles 生成完了: ${pm_tile_count} 枚 / ZL ${pm_zoom_levels} / $(awk "BEGIN{printf \"%.1f\", $pm_bytes/1024/1024}") MB（${pm_elapsed} 秒）→ $PMTILES_FILE"
  log "center=${pm_center} を明示（go-pmtiles の桁あふれ問題と同じ轍を踏まないため）"
  [ "$pm_clustered" = "true" ] || \
    warn "clustered=false になりました。範囲リクエストの局所性が落ちます"

  cat > "$WORK_DIR/tiles_meta.json" <<EOF
{
  "dataset_id": "$DATASET_ID",
  "output": "pmtiles",
  "via": "$PMTILES_VIA",
  "pmtiles_file": "$(basename "$PMTILES_FILE")",
  "min_zoom": $pm_min_zoom,
  "max_zoom": $pm_max_zoom,
  "format": "$TILE_FORMAT",
  "tile_count": $pm_tile_count,
  "total_bytes": $pm_bytes
}
EOF

  if [ "$PMTILES_KEEP_TILES" = "true" ]; then
    log "中間の XYZ ディレクトリを残しました（PMTILES_KEEP_TILES=false で削除）: $TILES_DIR"
  else
    log "中間の XYZ ディレクトリを削除中（${xyz_tile_count} ファイル）…"
    rm -rf "$TILES_DIR"
    log "削除しました"
  fi
}

# =============================================================================
# PMTiles 経路B: rio-mbtiles → pmtiles convert
# =============================================================================
# 中間の XYZ ディレクトリを作らずに済むが遅い。
# gdal_translate -of MBTILES を使わないのは、GDAL 3.11 の MBTiles ドライバに
# ZOOM_LEVEL 作成オプションが無く MAX_ZOOM を尊重できないため。
make_tiles_pmtiles_via_rio() {
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

  check_tiles --mbtiles "$MBTILES_FILE"

  finalize_pmtiles "$mb_tile_count"
}

case "$TILE_OUTPUT" in
  dir) make_tiles_dir ;;
  pmtiles)
    case "$PMTILES_VIA" in
      gdal2tiles)  make_tiles_pmtiles_via_gdal2tiles ;;
      rio-mbtiles) make_tiles_pmtiles_via_rio ;;
    esac
    ;;
esac
