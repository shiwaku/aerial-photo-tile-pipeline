#!/usr/bin/env bash
# Step 3: 複数ファイルを 1 つの仮想ファイル（VRT）にモザイク結合する。
# gdal2tiles は 1 ファイルしか受け付けないためこの手順が必要。
#
# Usage: scripts/03_build_vrt.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd gdalbuildvrt

step "Step 3: VRT 作成（$DATASET_ID）"

# ファイル数が多くても引数長制限に当たらないようリストファイル経由で渡す
list_file="$WORK_DIR/vrt_inputs.txt"

# 前処理済みがあればそちらを、無ければ元データを使う
if [ -d "$PREPARED_DIR" ] && [ -n "$(find "$PREPARED_DIR" -maxdepth 1 -name '*.tif' -print -quit)" ]; then
  log "入力: 前処理済みデータ（$PREPARED_DIR）"
  find "$PREPARED_DIR" -maxdepth 1 -type f -name '*.tif' | sort > "$list_file"
else
  log "入力: 元データ（$SRC_DIR）"
  list_sources | tr '\0' '\n' > "$list_file"
fi

count="$(wc -l < "$list_file")"
[ "$count" -gt 0 ] || die "VRT の入力ファイルがありません"

extra_args=()
srs="$(resolve_srs)"
[ -n "$srs" ] && extra_args+=(-a_srs "$srs") && log "CRS: $srs を付与"
# GSD がファイル間で異なる場合は最も細かい解像度に合わせる（既定は平均になってしまう）
if [ "$(inspect_value gsd_values | tr -cd ',' | wc -c)" -gt 0 ]; then
  extra_args+=(-resolution highest)
  warn "GSD が混在（$(inspect_value gsd_values)）→ -resolution highest で最も細かい解像度に合わせます"
fi
# shellcheck disable=SC2206
[ -n "$VRT_EXTRA_OPTS" ] && extra_args+=($VRT_EXTRA_OPTS)

gdalbuildvrt \
  "${extra_args[@]}" \
  -input_file_list "$list_file" \
  "$VRT_FILE"

log "VRT 作成完了（$count ファイル） → $VRT_FILE"
gdalinfo "$VRT_FILE" | sed -n '1,12p'
