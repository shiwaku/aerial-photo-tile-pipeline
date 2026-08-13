#!/usr/bin/env bash
# 1ファイル分の前処理ワーカー（02_prepare.sh から xargs 経由で並列実行される）。
#
# 環境変数で設定を受け取る: PREPARED_DIR / SRC_SRS / NODATA / SRC_EXT
# Usage: prepare_one.sh <input_file>

set -euo pipefail

src="$1"
base="$(basename "${src%.*}")"
dst="$PREPARED_DIR/$base.tif"

if [ -f "$dst" ] && [ "$dst" -nt "$src" ]; then
  echo "skip  $base（既に処理済み）"
  exit 0
fi

tmp="$dst.part"
rm -f "$tmp"

srs_args=()
[ -n "${SRC_SRS:-}" ] && srs_args=(-a_srs "$SRC_SRS")

co_args=(-co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=IF_SAFER)

if [ -n "${NODATA:-}" ]; then
  # 図郭外の色をアルファバンドに落とす（gdalwarp は -a_srs を持たないため
  # CRS 指定が必要なら -s_srs/-t_srs で同一 CRS を渡す）
  warp_srs=()
  if [ -n "${SRC_SRS:-}" ]; then
    warp_srs=(-s_srs "$SRC_SRS" -t_srs "$SRC_SRS")
  fi
  # -of GTiff は必須（出力名が .part のため拡張子からドライバを推測できない）
  gdalwarp -q -of GTiff \
    "${warp_srs[@]}" \
    -srcnodata "$NODATA" \
    -dstalpha \
    "${co_args[@]}" \
    "$src" "$tmp"
else
  # 透過処理なし: GeoTIFF に揃えるだけ（CRS 付与を含む）
  gdal_translate -q -of GTiff "${srs_args[@]}" "${co_args[@]}" "$src" "$tmp"
fi

mv "$tmp" "$dst"
echo "done  $base"
