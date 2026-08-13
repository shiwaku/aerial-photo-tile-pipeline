#!/usr/bin/env bash
# Step 2: 前処理（GeoTIFF への統一・図郭外の透過・CRS 付与）。
#
# 何もする必要がない場合（tif かつ CRS 埋め込み済みかつ透過処理不要）は
# スキップして元データをそのまま使う。
#
# Usage: scripts/02_prepare.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd gdalwarp gdal_translate

step "Step 2: 前処理（$DATASET_ID）"

ext_lower="$(printf '%s' "$SRC_EXT" | tr '[:upper:]' '[:lower:]')"
# CRS は画像埋め込みでも SRC_SRS 指定でもよい（VRT 作成時に -a_srs で付与される）
srs_known="$(inspect_value srs)"

if [ -z "$NODATA" ] && [ "$ext_lower" = "tif" ] && [ -n "$srs_known" ]; then
  log "前処理不要（GeoTIFF・CRS 判定済み・透過処理なし）→ 元データを直接使用"
  rm -rf "$PREPARED_DIR"
  exit 0
fi

if [ -n "$NODATA" ]; then
  log "透過処理: NoData = \"$NODATA\" をアルファバンドに変換"
else
  log "透過処理なし（GeoTIFF への統一と CRS 付与のみ）"
fi
[ -n "$SRC_SRS" ] && log "CRS: $SRC_SRS を指定"

mkdir -p "$PREPARED_DIR"

export PREPARED_DIR SRC_SRS NODATA
list_sources | xargs -0 -P "$JOBS" -n 1 "$REPO_ROOT/scripts/lib/prepare_one.sh"

count="$(find "$PREPARED_DIR" -maxdepth 1 -name '*.tif' | wc -l)"
log "前処理済み $count ファイル → $PREPARED_DIR"
