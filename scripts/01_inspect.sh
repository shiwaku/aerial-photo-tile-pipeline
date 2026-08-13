#!/usr/bin/env bash
# Step 1: 受領データを検査し、GSD・CRS・バンド構成・NoData と推奨最大ZLを出す。
#
# Usage: scripts/01_inspect.sh config/<name>.conf

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
load_conf "${1:-}"
require_cmd gdalinfo python3

step "Step 1: 入力データ検査（$DATASET_ID）"

mkdir -p "$INSPECT_DIR"

mapfile -d '' sources < <(list_sources)
[ "${#sources[@]}" -gt 0 ] || die "入力画像が見つかりません: $SRC_DIR/*.$SRC_EXT"

log "対象 ${#sources[@]} ファイル（$SRC_DIR/*.$SRC_EXT）"

assume_args=()
[ -n "$SRC_SRS" ] && assume_args=(--assume-srs "$SRC_SRS")

python3 "$REPO_ROOT/tools/inspect_inputs.py" \
  "${assume_args[@]}" \
  --out-json "$INSPECT_DIR/inputs.json" \
  --out-report "$INSPECT_DIR/report.md" \
  "${sources[@]}"

log "レポート: $INSPECT_DIR/report.md"
