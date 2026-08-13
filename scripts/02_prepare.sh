#!/usr/bin/env bash
# Step 2: 前処理（GeoTIFF への統一・図郭外の透過・CRS 付与・バンド数の統一）。
#
# 何もする必要がない場合（すべて tif・CRS 判定済み・透過処理不要・バンド数が揃っている）は
# スキップして元データをそのまま使う。
#
# Usage: scripts/02_prepare.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd gdalwarp gdal_translate

step "Step 2: 前処理（$DATASET_ID）"

srs_known="$(resolve_srs)"
nodata="$(resolve_nodata)"
exts="$(source_exts | paste -sd, -)"
band_counts="$(inspect_value band_counts)"

# gdalbuildvrt は 3 バンドと 4 バンドの混在で失敗するため、混在時はアルファを付けて揃える
unify_bands=0
if [ "$band_counts" != "[3]" ] && [ "$band_counts" != "[4]" ]; then
  unify_bands=1
  warn "バンド数が混在しています（$band_counts）→ 全ファイルにアルファバンドを付けて揃えます"
fi

if [ -z "$nodata" ] && [ "$exts" = "tif" ] && [ -n "$srs_known" ] && [ "$unify_bands" -eq 0 ]; then
  log "前処理不要（GeoTIFF・CRS 判定済み・透過処理なし・バンド数一致）→ 元データを直接使用"
  rm -rf "$PREPARED_DIR"
  exit 0
fi

if [ -n "$nodata" ]; then
  log "透過処理: NoData = \"$nodata\" をアルファバンドに変換"
  [ "$NODATA" = "auto" ] && log "  （NODATA=auto → 外周画素の実測から判定: $(inspect_value nodata_reason)）"
else
  log "透過処理なし（$( [ "$NODATA" = "auto" ] && echo "auto 判定の結果: $(inspect_value nodata_reason)" || echo "NODATA 未設定" )）"
fi
[ "$exts" != "tif" ] && log "GeoTIFF へ統一（入力拡張子: $exts）"
[ -n "$srs_known" ] && log "CRS: $srs_known を付与"

mkdir -p "$PREPARED_DIR"

export PREPARED_DIR
export SRC_SRS="$srs_known"
export NODATA="$nodata"
export UNIFY_BANDS="$unify_bands"
list_sources | xargs -0 -P "$JOBS" -n 1 "$REPO_ROOT/scripts/lib/prepare_one.sh"

count="$(find "$PREPARED_DIR" -maxdepth 1 -name '*.tif' | wc -l)"
log "前処理済み $count ファイル → $PREPARED_DIR"
