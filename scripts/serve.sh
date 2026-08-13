#!/usr/bin/env bash
# 生成タイルをローカルで確認する（MapLibre のビューワを起動）。
#
# Usage: scripts/serve.sh config/<name>.conf [port]

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
port="${2:-8080}"

[ -d "$TILES_DIR" ] || die "タイルがありません: $TILES_DIR"
[ -f "$TILES_DIR/tiles.json" ] || warn "tiles.json がありません（Step 5 未実行）"

# タイル（$WORK_DIR/tiles/）と同一オリジンで配信するため $WORK_DIR に置く
cp -f "$REPO_ROOT/viewer/index.html" "$WORK_DIR/index.html"

log "http://localhost:$port/ を開いてください（Ctrl+C で終了）"
cd "$WORK_DIR"
python3 -m http.server "$port"
