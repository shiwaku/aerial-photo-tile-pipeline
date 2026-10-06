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

# PMTiles の書き出しは Step 4 の最後なので、Python の pmtiles が無いとタイル生成を
# 終えてから落ちる。タイル生成を含むときは最初に確かめる（Docker イメージには入っている）
if [ "$TILE_OUTPUT" = "pmtiles" ] && [ "$PMTILES_VIA" = "gdal2tiles" ] \
   && [ "$from_step" -le 4 ] && [ "$to_step" -ge 4 ]; then
  python3 -c 'import pmtiles' 2>/dev/null \
    || die "PMTiles の書き出しに Python の pmtiles が必要です（pip install pmtiles）。タイルのフォルダで出力するなら、設定を TILE_OUTPUT=\"dir\" にしてください"
fi

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
if [ -n "${HOST_PROJECT_DIR:-}" ]; then
  # docker-run.sh / docker-run.ps1 から実行した場合。コンテナの中のパス（/work/...）は
  # 手元から見えないので、作業フォルダのパスで示す。serve.sh はコンテナの外で
  # リポジトリの output/ を見るため、作業フォルダの出力には使えない
  # docker-run.ps1 から来たパス（C:\Users\...）は、区切りを \ にそろえて示す
  sep="/"
  case "$HOST_PROJECT_DIR" in *\\*) sep='\' ;; esac
  host_out="$HOST_PROJECT_DIR${sep}output${sep}$DATASET_ID"
  if [ "$TILE_OUTPUT" = "pmtiles" ]; then
    log "出力: $host_out${sep}$(basename "$PMTILES_FILE")"
    # PMTILES_KEEP_TILES="true"（既定）なら、中間の XYZ ディレクトリも成果物として残っている
    [ -d "$TILES_DIR" ] && log "出力: $host_out${sep}tiles${sep}（XYZ ディレクトリ）"
  else
    log "出力: $host_out${sep}tiles${sep}"
  fi
  log "ビューワで確認: ${HOST_WRAPPER:-docker-run.sh} serve $conf"
else
  log "出力: $WORK_DIR"
  if [ "$TILE_OUTPUT" = "pmtiles" ]; then
    [ -f "$PMTILES_FILE" ] && log "プレビュー: scripts/serve.sh $conf"
  else
    [ -d "$TILES_DIR" ] && log "プレビュー: scripts/serve.sh $conf"
  fi
fi
