#!/usr/bin/env bash
# Docker イメージでパイプラインを実行するホスト側のラッパー（macOS / Linux / WSL2）。
#
# Usage: ./docker-run.sh config/<name>.conf [--from N] [--to N]
#        ./docker-run.sh ./scripts/<step>.sh config/<name>.conf ...   # 個別ステップ
#        ./docker-run.sh selftest                                       # オープンデータで動作確認
#
# 作業フォルダ（既定はカレントディレクトリ）の data/ output/ config/ をコンテナの
# /work 以下にマウントする。設定ファイルのパスはこの作業フォルダからの相対で書く。
# スクリプトはイメージに入っているので、作業フォルダにリポジトリは要らない。
#
# 環境変数:
#   PROJECT_DIR  作業フォルダ（既定: カレントディレクトリ）
#   IMAGE        使うイメージ（既定: 手元で build した aerial-tile-pipeline。無ければ GHCR の公開イメージ）
set -euo pipefail

PROJECT_DIR="$(cd "${PROJECT_DIR:-.}" && pwd)"
LOCAL_IMAGE="aerial-tile-pipeline"
PUBLIC_IMAGE="ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ $# -ge 1 ] || die "使い方: $0 config/<name>.conf [--from N] [--to N]"
command -v docker >/dev/null 2>&1 || die "docker が見つかりません"
# 手元にイメージがあれば 0、無ければ 1 を返す。Docker に接続できないなど、
# 「無い」以外の理由で確かめられないときは止める。どんな失敗でも「無い」とみなすと、
# Docker の一時的な不調で、気付かないうちに古い公開イメージで動くことがある
image_exists() {
  local err
  err="$(docker image inspect "$1" 2>&1 >/dev/null)" && return 0
  case "$err" in
    *"No such image"*) return 1 ;;
  esac
  die "イメージ $1 を確かめられません（Docker Desktop が起動しているか確認してください）: $err"
}

if [ -z "${IMAGE:-}" ]; then
  if image_exists "$LOCAL_IMAGE"; then
    IMAGE="$LOCAL_IMAGE"
    printf '手元でビルドしたイメージ %s を使います\n' "$IMAGE" >&2
  else
    IMAGE="$PUBLIC_IMAGE"
    printf '公開イメージ %s を使います\n' "$IMAGE" >&2
  fi
fi
# レジストリを含まない名前は手元にあるはずなので、無ければ build を促す（含む名前は docker run が取得する）
case "$IMAGE" in
  */*) ;;
  *) image_exists "$IMAGE" \
       || die "イメージ $IMAGE がありません。リポジトリで docker build -t $IMAGE . を実行してください" ;;
esac

# 第1引数が設定ファイルなら一括実行、それ以外はコマンドとしてそのまま渡す
case "$1" in
  *.conf)   cmd=(./scripts/run_pipeline.sh "$@"); conf="$1" ;;
  selftest) shift; cmd=(./scripts/selftest.sh "$@"); conf="" ;;
  *)        cmd=("$@"); conf="" ;;
esac
if [ -n "$conf" ]; then
  [ -f "$PROJECT_DIR/$conf" ] || die "設定ファイルが見つかりません: $PROJECT_DIR/$conf"
fi

mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/output" "$PROJECT_DIR/config"

# 長時間ジョブがスリープで止まらないようにする。macOS は caffeinate、
# systemd のある Linux は systemd-inhibit。WSL2 は Windows 側の電源設定に従う。
# systemd-inhibit は権限が無いと「Access denied」で失敗する（SSH・CI など）ので、
# 一度試して通ったときだけ使う
wrap=()
inhibit=(systemd-inhibit --what=sleep:idle --why="aerial-photo-tile-pipeline")
if command -v caffeinate >/dev/null 2>&1; then
  wrap=(caffeinate -is)
elif command -v systemd-inhibit >/dev/null 2>&1 && "${inhibit[@]}" true >/dev/null 2>&1; then
  wrap=("${inhibit[@]}")
fi

tty=()
[ -t 0 ] && [ -t 1 ] && tty=(-it)

exec ${wrap[@]+"${wrap[@]}"} docker run --rm ${tty[@]+"${tty[@]}"} \
  --user "$(id -u):$(id -g)" -e HOME=/tmp -e HOST_PROJECT_DIR="$PROJECT_DIR" \
  -v "$PROJECT_DIR/data":/work/data \
  -v "$PROJECT_DIR/output":/work/output \
  -v "$PROJECT_DIR/config":/work/config:ro \
  "$IMAGE" "${cmd[@]}"
