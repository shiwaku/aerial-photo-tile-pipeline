#!/usr/bin/env bash
# 航空写真タイル生成パイプラインの一括実行。
#
# Usage: scripts/run_pipeline.sh config/<name>.conf [--from N] [--to N]
#
#   --from N / --to N でステップ番号を絞れる（例: --from 4 でタイル生成からやり直し）

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

conf="${1:-}"
shift || true

from_step=1
to_step=5
while [ $# -gt 0 ]; do
  case "$1" in
    --from) from_step="$2"; shift 2 ;;
    --to)   to_step="$2";   shift 2 ;;
    *) die "不明な引数: $1" ;;
  esac
done

load_conf "$conf"

start_epoch=$SECONDS
log "パイプライン開始: $DATASET_ID（Step $from_step → $to_step）"

steps=(
  "01_inspect.sh"
  "02_prepare.sh"
  "03_build_vrt.sh"
  "04_make_tiles.sh"
  "05_make_tilejson.sh"
)

for i in "${!steps[@]}"; do
  n=$((i + 1))
  [ "$n" -ge "$from_step" ] || continue
  [ "$n" -le "$to_step" ] || continue
  "$REPO_ROOT/scripts/${steps[$i]}" "$conf"
done

elapsed=$((SECONDS - start_epoch))
step "完了（所要 $((elapsed / 60))分$((elapsed % 60))秒）"
log "出力: $WORK_DIR"
[ -d "$TILES_DIR" ] && log "プレビュー: scripts/serve.sh $conf"
