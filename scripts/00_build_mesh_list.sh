#!/usr/bin/env bash
# Step 0-a（任意）: 図郭索引ベクトルタイルから、対象範囲の図郭リストを作る。
#
# オルソ画像が「図郭を選択してダウンロード」形式で公開されているオープンデータ向け。
# 手元にデータを配置済みなら不要。
#
# Usage: scripts/00_build_mesh_list.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd python3

step "Step 0-a: 図郭リスト作成（$DATASET_ID）"

[ -n "$MESH_INDEX_URL" ] || die "MESH_INDEX_URL が未設定です（設定ファイルを確認してください）"
[ -n "$MESH_BOUNDARY$MESH_BBOX" ] || die "MESH_BOUNDARY か MESH_BBOX のどちらかを設定してください"

args=(
  --index-url "$MESH_INDEX_URL"
  --zoom "$MESH_INDEX_ZOOM"
  --mesh-field "$MESH_FIELD"
  --url-field "$MESH_URL_FIELD"
  --cache-dir "$REPO_ROOT/output/_index_cache"
  --out-csv "$MESH_LIST"
  --out-geojson "$WORK_DIR/mesh_polygons.geojson"
)
[ -n "$MESH_BOUNDARY" ] && args+=(--boundary "$MESH_BOUNDARY")
[ -n "$MESH_BBOX" ]     && args+=(--bbox "$MESH_BBOX")
[ -n "$MESH_NEAR" ]     && args+=(--near "$MESH_NEAR")
[ -n "$MESH_COUNT" ]    && args+=(--count "$MESH_COUNT")

python3 "$REPO_ROOT/tools/build_mesh_index.py" "${args[@]}"

log "図郭リスト: $MESH_LIST"
log "図郭ポリゴン（範囲確認用）: $WORK_DIR/mesh_polygons.geojson"
