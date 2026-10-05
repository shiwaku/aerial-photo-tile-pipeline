#!/usr/bin/env bash
# 動作確認: オープンデータを数図郭だけ取得し、Step 0〜5（PMTiles 出力）を通して結果を検査する。
# 新しい環境（OS・CPU・Docker の種類）で動くかを確かめるためのもの。CI もこれを呼ぶ。
#
# Usage: scripts/selftest.sh [--count N]
#
#   使うデータ: VIRTUAL SHIZUOKA 静岡県 中・西部 点群データのオルソ画像（CC BY 4.0）
#   既定の 4 図郭で約 30 MB をダウンロードする。出力は output/selftest/、入力は data/selftest/。

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

count="4"
while [ $# -gt 0 ]; do
  case "$1" in
    --count) count="$2"; shift 2 ;;
    *) die "不明な引数: $1" ;;
  esac
done

work="output/selftest"
conf="$work/selftest.conf"
mkdir -p "$work"
# 静岡市役所付近。境界 GeoJSON の取得先に依存しないよう MESH_BBOX で絞る
cat > "$conf" <<EOF
DATASET_ID="selftest"
DATASET_NAME="動作確認（VIRTUAL SHIZUOKA）"
MESH_INDEX_URL="https://gic-shizuoka.s3.ap-northeast-1.amazonaws.com/2025/Vectortile/mw/LP/merge/ortho/{z}/{x}/{y}.pbf"
MESH_BBOX="138.36,34.96,138.40,34.99"
MESH_NEAR="138.3828,34.9756"
MESH_COUNT="$count"
FETCH_JOBS="4"
SRC_DIR="data/selftest"
TILE_OUTPUT="pmtiles"
EOF

start_epoch=$SECONDS
"$REPO_ROOT/scripts/00_build_mesh_list.sh" "$conf"
"$REPO_ROOT/scripts/00_fetch_data.sh" "$conf"
"$REPO_ROOT/scripts/run_pipeline.sh" "$conf"

load_conf "$conf"
step "動作確認の判定"

fail=0
check() {
  if eval "$2"; then log "OK  $1"; else warn "NG  $1"; fail=1; fi
}

meta="$WORK_DIR/tiles_meta.json"
tile_count="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['tile_count'])" "$meta" 2>/dev/null || echo 0)"
check "PMTiles ができている（$PMTILES_FILE）" '[ -s "$PMTILES_FILE" ]'
check "タイルが 1 枚以上ある（${tile_count} 枚）" '[ "$tile_count" -gt 0 ]'

eval "$(python3 "$REPO_ROOT/tools/check_tiles.py" --tiles-dir "$TILES_DIR" --format "$TILE_FORMAT")"
check "不透明な黒が混ざっていない（${check_black_ratio:-?}%）" '[ "${check_ok:-}" = "true" ]'

check "PMTiles を読める" 'python3 - "$PMTILES_FILE" <<PY
import sys
from pmtiles.reader import Reader, MmapSource
with open(sys.argv[1], "rb") as f:
    h = Reader(MmapSource(f)).header()
sys.exit(0 if h["max_zoom"] >= h["min_zoom"] else 1)
PY'

elapsed=$((SECONDS - start_epoch))
log "GDAL: $(gdal --version) / CPU: $(uname -m) / 並列: $JOBS / 所要: $((elapsed / 60))分$((elapsed % 60))秒"
[ "$fail" -eq 0 ] || die "動作確認に失敗しました"
step "動作確認: すべて OK"
