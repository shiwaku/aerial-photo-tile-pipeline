# aerial-photo-tile-pipeline

航空写真（正射画像）から XYZ ラスタータイル／PMTiles を生成します。図郭分割された GeoTIFF・JPEG を入力に、**検査 → 前処理 → モザイク結合 → タイル生成 → TileJSON** までを設定ファイル 1 枚で通します。

出力したタイルは、同梱の MapLibre ビューワのほか、QGIS や任意の Web 地図の背景地図として利用できます。

- 入力の諸元（GSD・CRS・バンド構成・余白色）を機械的に検査し、**最大ズームレベルを自動決定**する
- 図郭外の余白と整備範囲の穴を透過させる（不透明な黒が残らないことを生成後に自動検査する）
- 出力は **WebP（既定）** または PNG、形態は **XYZ ディレクトリ（既定）** または **PMTiles（単一ファイル）**
- 図郭単位で配布されているオープンデータなら、対象範囲の一括ダウンロードから通せる

## クイックスタート

必要なのは **GDAL 3.11 以上**と **Python 3.9 以上（GDAL バインディング付き）** だけです。Python の追加ライブラリは要りません（PMTiles 出力のみ `pmtiles` が要ります）。タイル生成には GDAL 3.11 で入った `gdal raster tile` を使います（`gdal2tiles` は GDAL 3.13 で非推奨になりました）。

```bash
gdal --version                            # GDAL のバージョン
gdal raster tile --help | grep -- --skip-blank   # タイル生成コマンドの確認
python3 -c "from osgeo import gdal"       # バインディングの確認
```

手元に GDAL を用意しにくい場合は、同梱の `Dockerfile` を使えます（[Docker で実行する](#docker-で実行する)）。

**1. データを用意する**

手元にデータが無ければ、[VIRTUAL SHIZUOKA 静岡県 中・西部 点群データ](https://www.geospatial.jp/ckan/dataset/virtual-shizuoka-mw)のオルソ画像（GSD 0.20 m/px・ODbL）が試用に使えます。同梱の設定例がこのデータの図郭索引を指しているので、ダウンロードから自動で通ります。

```bash
git clone https://github.com/shiwaku/aerial-photo-tile-pipeline.git
cd aerial-photo-tile-pipeline

cp config/shizuoka-city.conf.example config/shizuoka-city.conf
```

コピーした `config/shizuoka-city.conf` の次の 2 行のコメント（先頭の `#`）を外してください。静岡市役所付近の 12 図郭（約 100 MB）だけに絞る指定です。

```bash
MESH_NEAR="138.3828,34.9756"
MESH_COUNT="12"
```

> **外さずに実行すると静岡市全域（約 8,800 図郭・展開後 74 GB）を取りにいきます。** 全域を通す場合は[性能実測](docs/benchmarks.md)で所要時間と容量を確認してから実行してください。

**2. タイルを作る**

```bash
./scripts/00_build_mesh_list.sh config/shizuoka-city.conf   # 図郭リスト作成（約30秒）
./scripts/00_fetch_data.sh      config/shizuoka-city.conf   # ダウンロード
./scripts/run_pipeline.sh       config/shizuoka-city.conf   # 検査→タイル生成（約10秒）

ls output/shizuoka-city/tiles/            # ZL9〜19 のタイルが出る
cat output/shizuoka-city/inspect/report.md   # CRS・GSD・最大ZL の判定根拠
```

手元のデータを使う場合は Step 0 を飛ばし、画像とワールドファイルを `data/<任意の名前>/` に平置きしてから `config/sample.conf.example` をコピーして `SRC_DIR` を指定します（[入力データの置き方](data/README.md)）。ひな形は PMTiles で出力する設定なので、`pip install pmtiles` が要ります（タイルのフォルダで出力するなら `TILE_OUTPUT="dir"` に変えれば不要です）。設定値は `auto` のままで構いませんが、**まず `./scripts/01_inspect.sh` だけを実行して判定結果を確認してから**通しで流してください。

**3. 地図で見る**

ビューワは Vite プロジェクトなので、初回だけビルドが要ります（Node.js 18 以上）。

```bash
cd viewer && npm install && npm run build && cd ..
./scripts/serve.sh config/shizuoka-city.conf      # http://localhost:8080/
```

背景地図の切替・不透明度スライダー・整備範囲へのフィットが使えます（[ビューワ](docs/viewer.md)）。

### Docker で実行する

GDAL を手元に入れにくい場合（macOS の Homebrew 版で依存ライブラリが欠ける場合など）は、同梱の `Dockerfile` を使えます。イメージに実行環境とスクリプト一式が入っているので、手元に要るのは Docker だけです。macOS・Linux（amd64 / arm64）・Windows（WSL2 / PowerShell）で動きます。

```bash
# 公開イメージ ghcr.io/shiwaku/aerial-photo-tile-pipeline を自動で使う（手元で build したものがあればそちらを優先）
cd ~
git clone https://github.com/shiwaku/aerial-photo-tile-pipeline.git
mkdir ~/aerial-selftest && cd ~/aerial-selftest
~/aerial-photo-tile-pipeline/docker-run.sh selftest      # オープンデータで動作確認
```

自分のデータでの実行、Windows の PowerShell での使い方、作業フォルダの形、OS ごとの注意、メモリ・ディスク・Docker Desktop のライセンスについては [Docker で実行する](docs/docker.md) を参照してください。

## 使い方

各ステップは独立して実行でき、第 1 引数に設定ファイルを取ります。

```bash
./scripts/run_pipeline.sh config/sample.conf                 # Step 1〜5 を通しで
./scripts/run_pipeline.sh config/sample.conf --from 4        # タイル生成以降だけやり直す
./scripts/run_pipeline.sh config/sample.conf --from 2 --to 3
./scripts/01_inspect.sh   config/sample.conf                 # 単体で実行する場合
```

| スクリプト | 処理 |
|---|---|
| `00_build_mesh_list.sh` | （任意）図郭索引ベクトルタイルから対象範囲の図郭リストを作る |
| `00_fetch_data.sh` | （任意）図郭 ZIP を一括ダウンロードして `SRC_DIR` に平置き展開する |
| `01_inspect.sh` | 入力を検査し、CRS・GSD・余白色・最大 ZL を判定する |
| `02_prepare.sh` | GeoTIFF への統一・CRS 付与・図郭外の透過（不要なら自動スキップ） |
| `03_build_vrt.sh` | モザイク結合（`gdalbuildvrt -addalpha`） |
| `04_make_tiles.sh` | タイル生成（`gdal raster tile`）と生成後の抜き取り検査 |
| `05_make_tilejson.sh` | TileJSON 生成 |
| `serve.sh` | ローカルプレビュー（`config` と `[port]` を取る。既定 8080） |

中断しても再実行に耐えます。Step 0-b は展開済みの図郭を、Step 2 は処理済みのファイルをスキップします。Step 4 は `RESUME="true"` で不足タイルのみ生成します。

### 主な設定

案件ごとに違う値は `auto` と書けば実データから判定します。判定根拠は必ず `output/<id>/inspect/report.md` に残るので、鵜呑みにせず確認してから流してください。

| 設定 | デフォルト | 説明 |
|---|---|---|
| `DATASET_ID` | （必須） | 出力先ディレクトリ名（`output/<DATASET_ID>/`） |
| `SRC_DIR` | （必須） | 入力画像を平置きしたディレクトリ |
| `SRC_EXT` | `auto` | 入力画像の拡張子。`auto` で tif/jpg 等の混在も受け付ける |
| `SRC_SRS` | `auto` | 入力の CRS。`auto` は画像の CRS →図郭コードの系番号の順で判定 |
| `NODATA` | `auto` | 図郭外の余白色。`auto` は外周画素の実測で判定、空で透過処理なし |
| `MIN_ZOOM` / `MAX_ZOOM` | `9` / `auto` | `auto` は GSD とデータ中心緯度から算出 |
| `TILE_OUTPUT` | `dir` | `dir`（XYZ ディレクトリ）または `pmtiles`（単一ファイル）。`sample.conf.example` では `pmtiles` |
| `TILE_FORMAT` | `webp` | `webp` または `png` |
| `WEBP_QUALITY` | `85` | 非可逆の品質（1-100）。`lossless` で可逆 |
| `ATTRIBUTION` | （空） | TileJSON の出典表記。オープンデータのライセンス表記を入れる |
| `JOBS` | `nproc` | 並列数。16 スレッド機での実測では 8 が妥当 |

全項目と `auto` の判定ロジックは[設定リファレンス](docs/config.md)を参照してください。

### 出力ファイル

| パス | 内容 |
|---|---|
| `output/<id>/inspect/report.md` | 検査レポート（CRS・GSD・最大 ZL の判定根拠、警告） |
| `output/<id>/inspect/inputs.json` | ファイル別の検査結果（後段の `auto` 解決の唯一の根拠） |
| `output/<id>/merge.vrt` | モザイク VRT |
| `output/<id>/tiles/{z}/{x}/{y}.webp` | タイル（`TILE_OUTPUT="dir"`） |
| `output/<id>/tiles/tiles.json` | TileJSON（同上） |
| `output/<id>/<id>.pmtiles` | PMTiles アーカイブ（`TILE_OUTPUT="pmtiles"`） |
| `output/<id>/tiles.json` | TileJSON（同上。アーカイブと同じ階層） |
| `output/<id>/tiles_meta.json` | 出力形態・ZL 範囲・枚数・容量（Step 5 はこれを見て分岐する） |
| `output/<id>/mesh_list.csv` | 図郭リスト（Step 0-a） |
| `output/<id>/mesh_polygons.geojson` | 図郭ポリゴンと整備範囲の外形（範囲確認用） |

## PMTiles で出力する

`TILE_OUTPUT="pmtiles"` にすると、タイルを単一ファイルにまとめます。本番実測では 366,827 ファイルが 1 ファイル（約 7.5 GB）になりました。追加で [pmtiles](https://pypi.org/project/pmtiles/)（依存ゼロの純 Python）が必要です。

```bash
pip install pmtiles

# sample.conf.example から作った設定は最初からこの値。Step 1〜5 の流し方は同じ
TILE_OUTPUT="pmtiles"

./scripts/run_pipeline.sh config/sample.conf
./scripts/serve.sh        config/sample.conf   # Range 対応サーバで起動する
pmtiles show output/sample/sample.pmtiles      # center の経度が正しいことを確認
```

既定の経路はタイルディレクトリから **PMTiles を直接書き出します**。以前は MBTiles を経由していましたが、その工程は変換の入力を作るためだけのもので、本番 366,827 枚で 65分30秒 → 22分16秒（**43 分の削減**）になりました。経路の違い・`center` が壊れる既知の問題・rio-mbtiles の注意点は [PMTiles 出力](docs/pmtiles.md)を参照してください。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [Docker で実行する](docs/docker.md) | OS ごとの手順・動作確認（selftest）・メモリとディスクの注意 |
| [設定リファレンス](docs/config.md) | 全設定項目・`auto` の判定ロジック・系番号が座標値だけでは決まらない理由 |
| [図郭データの取得（Step 0）](docs/mesh-fetch.md) | 図郭索引ベクトルタイルの扱い・境界での絞り込み・実測メモ |
| [PMTiles 出力](docs/pmtiles.md) | 2 経路の比較・`center` の桁あふれ・rio-mbtiles の罠 |
| [設計判断と落とし穴](docs/design-notes.md) | 最大 ZL の決め方・透過処理・整備範囲の穴が黒くなる事故 |
| [性能実測](docs/benchmarks.md) | ダウンロード・タイル生成・並列数・本番 8,844 図郭の実測 |
| [ビューワ](docs/viewer.md) | MapLibre ビューワの機能・ビルド・別ホスト配信 |
| [入力データの置き方](data/README.md) | ディレクトリ構成とオープンデータの入手先 |

## ディレクトリ構成

```
aerial-photo-tile-pipeline/
├── config/                    # 設定ファイル。実体の *.conf は Git 管理対象外
│   ├── sample.conf.example         # 手元のデータから始める場合
│   ├── shizuoka-city.conf.example  # オープンデータの実例（Step 0 付き）
│   └── shizuoka-north.conf.example # 同上（諸元の異なる別データセット）
├── data/                      # 入力画像を平置き。Git 管理対象外
├── output/                    # 中間・出力。Git 管理対象外
├── docs/                      # 詳細ドキュメント
├── scripts/
│   ├── 00_build_mesh_list.sh … 05_make_tilejson.sh
│   ├── run_pipeline.sh        # Step 1〜5 の一括実行
│   ├── serve.sh               # ローカルプレビュー
│   ├── selftest.sh            # オープンデータでの動作確認
│   └── lib/                   # 共通関数（common.sh）と前処理ワーカー
├── tools/                     # Python ツール（stdlib + osgeo のみ）
│   ├── build_mesh_index.py    # 図郭索引ベクトルタイル → 図郭リスト
│   ├── fetch_meshes.py        # 図郭 ZIP の並列取得・平置き展開
│   ├── inspect_inputs.py      # 入力検査・最大 ZL 算出
│   ├── make_tilejson.py       # TileJSON 生成
│   ├── dir_to_pmtiles.py      # タイルディレクトリ → PMTiles 直接書き出し
│   ├── mbtiles_meta.py        # MBTiles metadata 補正（rio-mbtiles 経路のみ）
│   ├── check_tiles.py         # 生成タイルの抜き取り検査
│   └── serve_range.py         # HTTP Range 対応の静的サーバ
├── viewer/                    # MapLibre ビューワ（Vite + TypeScript）
├── Dockerfile                 # 実行環境（GDAL 3.13 + pmtiles）とスクリプト一式
├── docker-run.sh              # Docker で実行するホスト側ラッパー（macOS / Linux / WSL2）
├── docker-run.ps1             # 同（Windows PowerShell）
└── LICENSE                    # Apache-2.0（対象はパイプラインとビューワ）
```

## 留意事項

- **`data/` と `output/`、案件ごとの `config/*.conf` は `.gitignore` で除外しています。** リポジトリにデータは含まれません。
- **入力データのライセンスはパイプラインとは別です。** オープンデータを使う場合は出典表記の条件を確認し、`ATTRIBUTION` に反映してください（クイックスタートで使う静岡県のデータは ODbL）。
- 入力は**図郭ごとに 1 ディレクトリへ平置き**する前提です。サブディレクトリは辿りません。
- 3 バンドと 4 バンドが混在すると `gdalbuildvrt` が失敗するため、混在を検出したら Step 2 が全ファイルにアルファバンドを付けて揃えます。
- **入力を drvfs（`/mnt/c`）から ext4 に移すと 3.5 倍速くなります**（WSL2 での実測）。支配的なのは入力の読み込みで、出力先の違いは誤差でした。

## ライセンス

本リポジトリのソースコードおよびドキュメントは [Apache License, Version 2.0](LICENSE) です。**パイプラインとビューワが対象で、入力する画像および生成したタイルには適用されません。**

## 参考

- [GDAL: gdal raster tile](https://gdal.org/en/stable/programs/gdal_raster_tile.html) / [gdalwarp](https://gdal.org/en/stable/programs/gdalwarp.html) / [gdalbuildvrt](https://gdal.org/en/stable/programs/gdalbuildvrt.html)
- [TileJSON 2.2.0 仕様](https://github.com/mapbox/tilejson-spec/tree/master/2.2.0)
- [PMTiles v3 仕様](https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md) / [go-pmtiles CLI](https://docs.protomaps.com/pmtiles/cli)
- [国土地理院 地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html)
