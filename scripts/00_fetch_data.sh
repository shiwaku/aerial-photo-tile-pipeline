#!/usr/bin/env bash
# Step 0-b（任意）: 図郭リストに従ってオルソ画像を一括ダウンロードし、SRC_DIR に平置きする。
#
# Usage: scripts/00_fetch_data.sh config/<name>.conf [--limit N]

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

conf="${1:-}"
shift || true
limit_override=""
while [ $# -gt 0 ]; do
  case "$1" in
    --limit) limit_override="$2"; shift 2 ;;
    *) die "不明な引数: $1" ;;
  esac
done

load_conf "$conf"
require_cmd python3

step "Step 0-b: データ取得（$DATASET_ID）"

[ -f "$MESH_LIST" ] || die "図郭リストがありません。先に scripts/00_build_mesh_list.sh を実行してください"

limit="${limit_override:-$FETCH_LIMIT}"
args=(--out-dir "$SRC_DIR" --zip-dir "$WORK_DIR/_zip" --jobs "$FETCH_JOBS")
[ -n "$limit" ] && args+=(--limit "$limit") && log "取得を先頭 $limit 件に制限"

mkdir -p "$SRC_DIR"
python3 "$REPO_ROOT/tools/fetch_meshes.py" "$MESH_LIST" "${args[@]}"

log "展開先: $SRC_DIR"
