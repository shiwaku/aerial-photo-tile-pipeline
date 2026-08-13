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

tile_url="$TILE_URL_TEMPLATE"
if [ -z "$tile_url" ]; then
  # 未指定ならローカルプレビュー用の相対パスにする
  tile_url="{z}/{x}/{y}.${TILE_FORMAT}"
  log "TILE_URL_TEMPLATE 未設定 → 相対パス（$tile_url）で生成"
fi

python3 "$REPO_ROOT/tools/make_tilejson.py" \
  --source "$VRT_FILE" \
  --tiles-meta "$meta" \
  --name "$DATASET_NAME" \
  --tile-url "$tile_url" \
  --attribution "$ATTRIBUTION" \
  --out "$TILES_DIR/tiles.json"

log "TileJSON: $TILES_DIR/tiles.json"
