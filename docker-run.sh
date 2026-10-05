#!/usr/bin/env bash
# Docker イメージでパイプラインを実行するホスト側のラッパー（macOS / Linux / WSL2）。
#
# Usage: ./docker-run.sh config/<name>.conf [--from N] [--to N]
#        ./docker-run.sh ./scripts/<step>.sh config/<name>.conf ...   # 個別ステップ
#
# 作業フォルダ（既定はカレントディレクトリ）の data/ output/ config/ をコンテナの
# /work 以下にマウントする。設定ファイルのパスはこの作業フォルダからの相対で書く。
# スクリプトはイメージに入っているので、作業フォルダにリポジトリは要らない。
#
# 環境変数:
#   PROJECT_DIR  作業フォルダ（既定: カレントディレクトリ）
#   IMAGE        使うイメージ（既定: aerial-tile-pipeline）
set -euo pipefail

PROJECT_DIR="$(cd "${PROJECT_DIR:-.}" && pwd)"
IMAGE="${IMAGE:-aerial-tile-pipeline}"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ $# -ge 1 ] || die "使い方: $0 config/<name>.conf [--from N] [--to N]"
command -v docker >/dev/null 2>&1 || die "docker が見つかりません"
docker image inspect "$IMAGE" >/dev/null 2>&1 \
  || die "イメージ $IMAGE がありません。リポジトリで docker build -t $IMAGE . を実行してください"

# 第1引数が設定ファイルなら一括実行、それ以外はコマンドとしてそのまま渡す
case "$1" in
  *.conf) cmd=(./scripts/run_pipeline.sh "$@"); conf="$1" ;;
  *)      cmd=("$@"); conf="" ;;
esac
if [ -n "$conf" ]; then
  [ -f "$PROJECT_DIR/$conf" ] || die "設定ファイルが見つかりません: $PROJECT_DIR/$conf"
fi

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/output" "$PROJECT_DIR/config"

# 長時間ジョブがスリープで止まらないようにする。macOS は caffeinate、
# systemd のある Linux は systemd-inhibit。WSL2 は Windows 側の電源設定に従う
wrap=()
if command -v caffeinate >/dev/null 2>&1; then
  wrap=(caffeinate -is)
elif command -v systemd-inhibit >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  wrap=(systemd-inhibit --what=sleep:idle --why="aerial-photo-tile-pipeline")
fi

tty=()
[ -t 0 ] && [ -t 1 ] && tty=(-it)

exec ${wrap[@]+"${wrap[@]}"} docker run --rm ${tty[@]+"${tty[@]}"} \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PROJECT_DIR/data":/work/data \
  -v "$PROJECT_DIR/output":/work/output \
  -v "$PROJECT_DIR/config":/work/config:ro \
  "$IMAGE" "${cmd[@]}"
