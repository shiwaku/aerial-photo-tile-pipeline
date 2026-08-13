#!/usr/bin/env bash
# Step 3: 複数ファイルを 1 つの仮想ファイル（VRT）にモザイク結合する。
# gdal2tiles は 1 ファイルしか受け付けないためこの手順が必要。
#
# Usage: scripts/03_build_vrt.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd gdalbuildvrt

step "Step 3: VRT 作成（$DATASET_ID）"

# 前処理済みがあればそちらを、無ければ元データを使う
if [ -d "$PREPARED_DIR" ] && [ -n "$(find "$PREPARED_DIR" -maxdepth 1 -name '*.tif' -print -quit)" ]; then
  vrt_src_dir="$PREPARED_DIR"
  vrt_src_ext="tif"
  log "入力: 前処理済みデータ（$PREPARED_DIR）"
else
  vrt_src_dir="$SRC_DIR"
  vrt_src_ext="$SRC_EXT"
  log "入力: 元データ（$SRC_DIR）"
fi

# ファイル数が多くても引数長制限に当たらないようリストファイル経由で渡す
list_file="$WORK_DIR/vrt_inputs.txt"
find "$vrt_src_dir" -maxdepth 1 -type f -iname "*.${vrt_src_ext}" | sort > "$list_file"
count="$(wc -l < "$list_file")"
[ "$count" -gt 0 ] || die "VRT の入力ファイルがありません: $vrt_src_dir/*.$vrt_src_ext"

extra_args=()
[ -n "$SRC_SRS" ] && extra_args+=(-a_srs "$SRC_SRS")
# shellcheck disable=SC2206
[ -n "$VRT_EXTRA_OPTS" ] && extra_args+=($VRT_EXTRA_OPTS)

gdalbuildvrt \
  "${extra_args[@]}" \
  -input_file_list "$list_file" \
  "$VRT_FILE"

log "VRT 作成完了（$count ファイル） → $VRT_FILE"
gdalinfo "$VRT_FILE" | sed -n '1,12p'
