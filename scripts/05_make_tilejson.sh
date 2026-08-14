#!/usr/bin/env bash
# Step 5: TileJSON（tiles.json）を生成する。
#
# Usage: scripts/05_make_tilejson.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd python3

step "Step 5: TileJSON 生成（$DATASET_ID）"

meta="$WORK_DIR/tiles_meta.json"
[ -f "$meta" ] || die "タイルがありません。先に scripts/04_make_tiles.sh を実行してください"

# Step 4 がどちらの形態で出力したかは tiles_meta.json を根拠にする
# （設定を読み直すと、設定変更後に実体と食い違う）
output_kind="$(python3 -c "
import json,sys
with open(sys.argv[1], encoding='utf-8') as f:
    print(json.load(f).get('output', 'dir'))
" "$meta")"

tile_url="$TILE_URL_TEMPLATE"

if [ "$output_kind" = "pmtiles" ]; then
  # PMTiles は単一ファイルなので tiles.json はアーカイブと同じ階層に置く
  out_json="$WORK_DIR/tiles.json"
  if [ -z "$tile_url" ]; then
    tile_url="pmtiles://$(basename "$PMTILES_FILE")/{z}/{x}/{y}"
    log "TILE_URL_TEMPLATE 未設定 → 相対パス（$tile_url）で生成"
  fi
else
  out_json="$TILES_DIR/tiles.json"
  if [ -z "$tile_url" ]; then
    tile_url="{z}/{x}/{y}.${TILE_FORMAT}"
    log "TILE_URL_TEMPLATE 未設定 → 相対パス（$tile_url）で生成"
  fi
fi

python3 "$REPO_ROOT/tools/make_tilejson.py" \
  --source "$VRT_FILE" \
  --tiles-meta "$meta" \
  --name "$DATASET_NAME" \
  --tile-url "$tile_url" \
  --attribution "$ATTRIBUTION" \
  --out "$out_json"

log "TileJSON: $out_json"
