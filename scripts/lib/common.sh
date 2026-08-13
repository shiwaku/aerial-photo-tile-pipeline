#!/usr/bin/env bash
# パイプライン共通関数・設定ロード
# 各ステップスクリプトから source して使う。

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export REPO_ROOT

# ---- ログ -------------------------------------------------------------------

_ts() { date +'%H:%M:%S'; }

log()  { printf '[%s] %s\n' "$(_ts)" "$*"; }
warn() { printf '[%s] WARN: %s\n' "$(_ts)" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(_ts)" "$*" >&2; exit 1; }

step() {
  printf '\n=== %s ===\n' "$*"
}

# ---- 依存チェック -----------------------------------------------------------

require_cmd() {
  local missing=0
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || { warn "コマンドが見つかりません: $c"; missing=1; }
  done
  [ "$missing" -eq 0 ] || die "必要なコマンドが不足しています（GDAL のインストールを確認してください）"
}

# ---- 設定ロード -------------------------------------------------------------

# 既定値。config/<name>.conf で上書きする。
DATASET_ID=""            # 出力ディレクトリ名・TileJSON の name に使う識別子
DATASET_NAME=""          # 人が読む名称（TileJSON の name）
SRC_DIR=""               # 入力画像ディレクトリ
SRC_EXT="auto"           # 入力画像の拡張子（tif / jpg など）。auto で混在も受け付ける
SRC_SRS="auto"           # 入力の CRS（例: EPSG:6676）。auto で座標値から系番号を推定
NODATA="auto"            # 図郭外の余白色（"255 255 255" 等）。auto で外周画素から判定、空で透過処理なし
MIN_ZOOM="9"
MAX_ZOOM="auto"          # auto = GSD から自動決定
TILE_FORMAT="webp"       # webp | png
WEBP_QUALITY="85"        # 非可逆の品質。lossless にすると可逆
RESAMPLING="average"
RESUME="false"           # true で既存タイルを残し不足分のみ生成（gdal2tiles -e）
JOBS=""                  # 並列数。空なら nproc
ATTRIBUTION=""           # TileJSON の attribution（出典表記）
TILE_URL_TEMPLATE=""     # 例: https://example.com/data/foo/latest/tiles/{z}/{x}/{y}.webp
VRT_EXTRA_OPTS=""        # gdalbuildvrt への追加オプション

# --- Step 0（任意）: 図郭単位で配布されているオープンデータの取得 ------------
MESH_INDEX_URL=""        # 図郭索引ベクトルタイルの URL テンプレート（{z}/{x}/{y}）
MESH_BOUNDARY=""         # 対象範囲の境界 GeoJSON（ファイルまたは URL）
MESH_BBOX=""             # 境界の代わりに使う範囲（west,south,east,north）
MESH_INDEX_ZOOM="12"     # 索引タイルを取得する ZL
MESH_FIELD="MESH_NO"     # 索引の図郭コード属性名
MESH_URL_FIELD="URL"     # 索引のダウンロード URL 属性名
MESH_NEAR=""             # サンプル抽出: この地点（lon,lat）に近い図郭に絞る
MESH_COUNT=""            # サンプル抽出: 抽出件数（MESH_NEAR と併用）
FETCH_LIMIT=""           # 取得を先頭 N 件に制限する
FETCH_JOBS="4"           # 並列ダウンロード数（配布元に負荷をかけない範囲で）

load_conf() {
  local conf="$1"
  [ -n "$conf" ] || die "設定ファイルを指定してください（例: config/sample.conf）"
  [ -f "$conf" ] || die "設定ファイルが見つかりません: $conf"
  # shellcheck disable=SC1090
  source "$conf"

  [ -n "$DATASET_ID" ] || die "DATASET_ID が未設定です: $conf"
  [ -n "$SRC_DIR" ]    || die "SRC_DIR が未設定です: $conf"

  : "${DATASET_NAME:=$DATASET_ID}"
  : "${JOBS:=$(nproc)}"

  WORK_DIR="$REPO_ROOT/output/$DATASET_ID"
  INSPECT_DIR="$WORK_DIR/inspect"
  PREPARED_DIR="$WORK_DIR/prepared"
  VRT_FILE="$WORK_DIR/merge.vrt"
  TILES_DIR="$WORK_DIR/tiles"
  MESH_LIST="$WORK_DIR/mesh_list.csv"
  export WORK_DIR INSPECT_DIR PREPARED_DIR VRT_FILE TILES_DIR MESH_LIST

  mkdir -p "$WORK_DIR"
}

# SRC_EXT="auto" のときに受け付ける拡張子
AUTO_EXTS=(tif tiff jpg jpeg png)

# 入力画像の一覧を NUL 区切りで出力（サブディレクトリは辿らない）
list_sources() {
  [ -d "$SRC_DIR" ] || die "SRC_DIR が存在しません: $SRC_DIR（Step 0 でデータを取得するか、手動で配置してください）"
  if [ "$SRC_EXT" = "auto" ]; then
    local expr=()
    for e in "${AUTO_EXTS[@]}"; do
      [ "${#expr[@]}" -eq 0 ] || expr+=(-o)
      expr+=(-iname "*.$e")
    done
    find "$SRC_DIR" -maxdepth 1 -type f \( "${expr[@]}" \) -print0 | sort -z
  else
    find "$SRC_DIR" -maxdepth 1 -type f -iname "*.${SRC_EXT}" -print0 | sort -z
  fi
}

# 入力に含まれる拡張子（小文字・重複なし）を改行区切りで出力
source_exts() {
  list_sources | tr '\0' '\n' | sed -n 's/.*\.\([^.]*\)$/\1/p' | tr '[:upper:]' '[:lower:]' | sort -u
}

# --- auto 値の解決 -----------------------------------------------------------
# いずれも Step 1 の検査結果を根拠にする。

# 入力 CRS。SRC_SRS が auto／空なら検査結果（埋め込み CRS または座標値からの推定）を使う
resolve_srs() {
  if [ -n "$SRC_SRS" ] && [ "$SRC_SRS" != "auto" ]; then
    printf '%s' "$SRC_SRS"
  else
    inspect_value srs
  fi
}

# 図郭外の余白色。NODATA が auto なら外周画素の実測から判定した値を使う
resolve_nodata() {
  if [ "$NODATA" = "auto" ]; then
    inspect_value nodata_suggestion
  else
    printf '%s' "$NODATA"
  fi
}

# inspect の結果から値を取り出す（jq 不要・Python 使用）
inspect_value() {
  local key="$1"
  local json="$INSPECT_DIR/inputs.json"
  [ -f "$json" ] || die "検査結果がありません。先に scripts/01_inspect.sh を実行してください"
  python3 -c "
import json,sys
with open(sys.argv[1], encoding='utf-8') as f:
    d = json.load(f)
v = d['summary'].get(sys.argv[2])
print('' if v is None else v)
" "$json" "$key"
}
