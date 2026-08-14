#!/usr/bin/env bash
# 生成タイルをローカルで確認する（MapLibre のビューワを起動）。
#
# Usage: scripts/serve.sh config/<name>.conf [port]
#
# ビューワは viewer/ の Vite プロジェクト。初回だけビルドが要る:
#   cd viewer && npm install && npm run build

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

dist="$REPO_ROOT/viewer/dist"
if [ ! -f "$dist/index.html" ]; then
  die "ビューワが未ビルドです。次を実行してください:
    cd $REPO_ROOT/viewer && npm install && npm run build"
fi

# ビューワはタイルと同一オリジンで配信する必要がある（tiles.json を相対で探すため）。
# ビルド成果物を作業ディレクトリへ複製する。パイプラインの出力とは名前が衝突しない。
cp -r "$dist"/. "$WORK_DIR"/

log "http://localhost:$port/ を開いてください（Ctrl+C で終了）"

# PMTiles は HTTP Range で部分読みするため、Range 非対応の
# `python3 -m http.server` は使えない。
python3 "$REPO_ROOT/tools/serve_range.py" --directory "$WORK_DIR" --port "$port"
