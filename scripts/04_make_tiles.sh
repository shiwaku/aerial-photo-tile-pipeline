#!/usr/bin/env bash
# Step 4: gdal2tiles で XYZ ラスタータイルを生成する。
#
# Usage: scripts/04_make_tiles.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd gdal2tiles

step "Step 4: タイル生成（$DATASET_ID）"

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

# --- 出力形式 ----------------------------------------------------------------
driver_args=()
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
  png)
    log "出力形式: PNG"
    ;;
  *)
    die "TILE_FORMAT は webp または png を指定してください（現在: $TILE_FORMAT）"
    ;;
esac

# --- NoData ------------------------------------------------------------------
# 前処理でアルファバンドを付けている場合は gdal2tiles 側の指定は不要。
nodata="$(resolve_nodata)"
nodata_args=()
if [ -z "$nodata" ]; then
  log "NoData: 透過処理なし"
elif [ -d "$PREPARED_DIR" ]; then
  log "NoData: 前処理済みのアルファバンドを使用"
else
  nodata_args=(--srcnodata="${nodata// /,}")
  log "NoData: gdal2tiles で ${nodata} を透過扱い"
fi

resume_args=()
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

ext="$TILE_FORMAT"
tile_count="$(find "$TILES_DIR" -name "*.${ext}" | wc -l)"
total_bytes="$(find "$TILES_DIR" -name "*.${ext}" -printf '%s\n' | awk '{s+=$1} END{print s+0}')"
log "タイル生成完了: ${tile_count} 枚 / $(awk "BEGIN{printf \"%.1f\", $total_bytes/1024/1024}") MB → $TILES_DIR"

# ステップ間で受け渡す実行結果
cat > "$WORK_DIR/tiles_meta.json" <<EOF
{
  "dataset_id": "$DATASET_ID",
  "min_zoom": $MIN_ZOOM,
  "max_zoom": $max_zoom,
  "format": "$TILE_FORMAT",
  "tile_count": $tile_count,
  "total_bytes": $total_bytes
}
EOF
