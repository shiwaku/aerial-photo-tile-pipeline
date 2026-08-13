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

log "対象 ${#sources[@]} ファイル（$SRC_DIR、拡張子: $(source_exts | paste -sd, -)）"

# SRC_SRS を明示している場合のみ検査側に渡す。auto のときは推定させる
assume_args=()
if [ -n "$SRC_SRS" ] && [ "$SRC_SRS" != "auto" ]; then
  assume_args=(--assume-srs "$SRC_SRS")
else
  log "CRS: auto（画像に CRS が無ければ図郭コードの系番号を座標値で検証して判定）"
fi

# レポート本文は数千ファイル規模だと長大になるため、ファイル数が多い場合は
# 標準出力に流さずレポートの要約だけ見せる
python3 "$REPO_ROOT/tools/inspect_inputs.py" \
  "${assume_args[@]}" \
  --jobs "$JOBS" \
  --out-json "$INSPECT_DIR/inputs.json" \
  --out-report "$INSPECT_DIR/report.md" \
  "${sources[@]}" \
  > "$INSPECT_DIR/report.stdout.txt"

if [ "${#sources[@]}" -le 50 ]; then
  cat "$INSPECT_DIR/report.stdout.txt"
else
  sed -n '/^## サマリ/,/^$/p;/^## 警告/,/^## ファイル別/p' "$INSPECT_DIR/report.md" \
    | grep -v '^## ファイル別'
fi

log "レポート: $INSPECT_DIR/report.md"
