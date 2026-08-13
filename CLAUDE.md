# CLAUDE.md

## プロジェクト概要

航空写真（正射画像）から XYZ ラスタータイルを生成するパイプライン。
GeoTIFF / JPEG + ワールドファイルを入力に、検査 → 前処理 → モザイク結合 →
タイル生成 → TileJSON を設定ファイル 1 枚で通す。

詳細な使い方・設計判断は `README.md` を参照。

## 取り扱いルール（重要）

- **このリポジトリで扱う検証データはオープンデータのみ。**
  業務で受領したデータ・顧客提供データ・案件固有の受領仕様や実測値は
  コード・ドキュメント・コミットメッセージのいずれにも含めない。
- `data/` と `output/` は `.gitignore` 済み。案件ごとの設定 `config/*.conf` も
  コミット対象外（`config/*.conf.example` のみ管理）。

## 構成

| パス | 役割 |
|------|------|
| `scripts/00_build_mesh_list.sh` / `00_fetch_data.sh` | Step 0（任意）: 図郭リスト作成・一括DL |
| `scripts/01_inspect.sh` … `05_make_tilejson.sh` | 各ステップ。第1引数に設定ファイルを取る |
| `scripts/run_pipeline.sh` | Step 1〜5 の一括実行（`--from N` / `--to N` でステップ指定） |
| `scripts/serve.sh` | ローカルプレビュー（`viewer/index.html` を配信） |
| `scripts/lib/common.sh` | ログ・設定ロード・依存チェック・入力列挙 |
| `scripts/lib/prepare_one.sh` | 前処理ワーカー（`xargs -P` で並列実行される） |
| `tools/build_mesh_index.py` | 図郭索引ベクトルタイル → 図郭リスト CSV |
| `tools/fetch_meshes.py` | 図郭 ZIP の並列取得・平置き展開 |
| `tools/inspect_inputs.py` | 入力検査・推奨最大ZL算出（stdlib + `osgeo` のみ） |
| `tools/make_tilejson.py` | TileJSON 生成 |

## 設計上の決めごと

- **最大ZL**: タイル解像度が GSD に最も近い ZL を採用。
  `round(log2(res(0) / GSD))`（`res(0) = 156543.033928 × cos(φ)`、φ はデータ中心緯度）。
  設定 `MAX_ZOOM="auto"` でこれを使い、数値指定で上書きできる。
- **透過処理**: `NODATA` 指定時は Step 2 で `gdalwarp -srcnodata <色> -dstalpha`。
  その場合 Step 4 では `--srcnodata` を渡さない（アルファバンドを使う）。
- **前処理のスキップ**: `NODATA` が空・入力が tif・CRS 埋め込み済みの 3 条件が揃えば
  Step 2 は何もせず、Step 3 が元データから直接 VRT を作る。
- **VRT 経由**: `gdal2tiles` は 1 ファイルしか受け付けないため必ず VRT を作る。
  ファイル数が多くても引数長制限に当たらないよう `-input_file_list` を使う。
- **出力形式**: 既定は WebP 非可逆 品質85。`TILE_FORMAT=png` で PNG。
- **冪等性**: Step 2 は出力が入力より新しければスキップする。
  Step 0-b も展開済みの図郭をスキップするため中断・再実行に耐える。
  Step 4 の再実行は `gdal2tiles` がディレクトリを上書きする（`-e` は使っていない）。

## 図郭索引ベクトルタイルを扱う際の実測メモ

`tools/build_mesh_index.py` の前提。オープンデータでの検証で確認した事実。

- 索引タイルは GDAL の MVT ドライバで単体タイルとして開ける
  （`gdal.OpenEx("MVT:<path>", open_options=["X=","Y=","Z=","CLIP=NO"])`）。
  返る図形は EPSG:3857 なので EPSG:4326 へ変換してから境界と交差判定する。
  `CLIP=NO` を付けないとタイル境界で図郭ポリゴンが切られる。
- 低 ZL でも図郭は間引かれていなかった（ZL12 の結果が ZL14 の結果を完全に包含）。
  ZL12（1枚あたり約 8km 四方）なら市域規模でも数十枚で済む。
  ただしこれはデータセット依存の性質なので、新しい索引を扱うときは
  高 ZL の結果と集合比較して確かめること。
- **ダウンロード URL は図郭コードから導出しない。** 再撮影分が
  `<図郭コード>_2.zip` のように別名で配布されている場合がある
  （検証したデータセットでは 8,840 件中 68 件）。索引の URL 属性をそのまま使う。
- 図郭コードの先頭 2 桁は平面直角座標系の系番号として使われていることが多く、
  `SRC_SRS` の裏取りに使える（例: `08...` → 第VIII系 = EPSG:6676）。
- `NODATA` を安易に設定しないこと。図郭が隅まで画像化されている配布形式では
  余白が存在せず、`"0 0 0"` は影、`"255 255 255"` は白飽和部分を誤透過させる。
  Step 1 の検査結果と、整備範囲の縁にある図郭の画素を実際に確認してから決める。

## 開発時の注意

- スクリプトは `set -euo pipefail` 前提。`common.sh` を `source` してから使う。
- 設定値の既定は `common.sh` の冒頭にまとめてある。新しい設定を足す場合は
  そこに既定値を書き、`config/sample.conf.example` にコメント付きで追記する。
- ファイル名の空白・日本語に耐えるよう、入力列挙は `find -print0` + `mapfile -d ''`
  で NUL 区切りにしている。この方針を崩さないこと。
- ステップ間の受け渡しはファイル経由（`inspect/inputs.json`、`tiles_meta.json`）。
  環境変数で暗黙に渡さない。
