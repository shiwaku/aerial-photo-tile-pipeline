#!/usr/bin/env bash
# 生成タイルをローカルで確認する（MapLibre のビューワを起動）。
#
# Usage: scripts/serve.sh config/<name>.conf [port]

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
port="${2:-8080}"

if [ "$TILE_OUTPUT" = "pmtiles" ]; then
  [ -f "$PMTILES_FILE" ] || die "PMTiles がありません: $PMTILES_FILE"
  [ -f "$WORK_DIR/tiles.json" ] || warn "tiles.json がありません（Step 5 未実行）"
else
  [ -d "$TILES_DIR" ] || die "タイルがありません: $TILES_DIR"
  [ -f "$TILES_DIR/tiles.json" ] || warn "tiles.json がありません（Step 5 未実行）"
fi

# タイル（$WORK_DIR 配下）と同一オリジンで配信するため $WORK_DIR に置く
cp -f "$REPO_ROOT/viewer/index.html" "$WORK_DIR/index.html"

log "http://localhost:$port/ を開いてください（Ctrl+C で終了）"

# PMTiles は HTTP Range で部分読みするため、Range 非対応の
# `python3 -m http.server` は使えない。
python3 "$REPO_ROOT/tools/serve_range.py" --directory "$WORK_DIR" --port "$port"
