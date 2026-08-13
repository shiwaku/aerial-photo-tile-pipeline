# aerial-photo-tile-pipeline

航空写真（正射画像）から XYZ ラスタータイルを生成するパイプライン。

GeoTIFF / JPEG + ワールドファイルで受け取った図郭分割済みのオルソ画像を入力に、
**検査 → 前処理 → モザイク結合 → タイル生成 → TileJSON** までを設定ファイル 1 枚で通す。

- 入力の諸元（GSD・CRS・バンド構成・NoData）を機械的に検査し、**最大ズームレベルを自動決定**する
- 図郭外の余白（白地／黒地）をアルファバンドに変換して透過させる
- 出力は **WebP（既定）** または PNG
- 生成物をローカルの MapLibre ビューワで即確認できる

## 必要なもの

| ツール | 用途 | 確認 |
|--------|------|------|
| GDAL 3.6+（`gdal2tiles` が `--tiledriver=WEBP` 対応） | 全ステップ | `gdal2tiles --help \| grep webp` |
| Python 3.9+ ＋ GDAL バインディング（`osgeo`） | 検査・TileJSON 生成 | `python3 -c "from osgeo import gdal"` |
| bash 4+ | スクリプト実行 | — |

Python 側の追加ライブラリは不要（標準ライブラリ ＋ `osgeo` のみ）。

## 使い方

```bash
# 1. データを置く（data/README.md 参照）
#    data/sample/*.tif + *.tfw

# 2. 設定を作る
cp config/sample.conf.example config/sample.conf
$EDITOR config/sample.conf          # SRC_DIR / SRC_SRS / NODATA を埋める

# 3. まず検査だけ実行して諸元を確認する
./scripts/01_inspect.sh config/sample.conf

# 4. 通しで実行
./scripts/run_pipeline.sh config/sample.conf

# 5. ローカルで確認
./scripts/serve.sh config/sample.conf     # http://localhost:8080/
```

途中からやり直す場合:

```bash
./scripts/run_pipeline.sh config/sample.conf --from 4      # タイル生成以降だけ
./scripts/run_pipeline.sh config/sample.conf --from 2 --to 3
```

### 図郭単位で配布されているオープンデータを取得する場合（Step 0）

オルソ画像が「地図上で図郭を選択してダウンロード」形式で公開されている場合、
その索引はダウンロード URL を属性に持つベクトルタイルとして配信されていることが多い。
Step 0 はその索引から対象範囲の図郭リストを作り、ZIP を一括ダウンロードして平置き展開する。

```bash
cp config/shizuoka-city.conf.example config/shizuoka-city.conf

./scripts/00_build_mesh_list.sh config/shizuoka-city.conf   # 図郭リスト作成
./scripts/00_fetch_data.sh      config/shizuoka-city.conf   # 一括ダウンロード
./scripts/run_pipeline.sh       config/shizuoka-city.conf   # タイル生成
```

`00_build_mesh_list.sh` は行政境界 GeoJSON（`MESH_BOUNDARY`）または bbox（`MESH_BBOX`）と
交差する図郭だけを選び、`output/<id>/mesh_list.csv`（`mesh_no,url`）と
範囲確認用の `mesh_polygons.geojson` を出す。

大きい自治体は全域で数千〜1万図郭・数十 GB になるため、まず
`MESH_NEAR="lon,lat"` ＋ `MESH_COUNT=12` で小さい範囲を通してから全域に広げる
（`00_fetch_data.sh --limit N` でも絞れる）。

> **ダウンロード URL は図郭コードから組み立てず、必ず索引の URL 属性を使う。**
> 再撮影分などで `<図郭コード>_2.zip` のように規則から外れるファイルが混ざる
> （実例のデータセットでは 8,840 件中 68 件）。

## パイプラインの構成

```
（Step 0）図郭索引ベクトルタイル → mesh_list.csv → ZIP 一括DL → data/<id>/ に平置き
  │
data/<id>/*.tif + *.tfw
  │
  ├─ Step 1  01_inspect.sh      検査（GSD・CRS・バンド・NoData）→ 推奨最大ZLを算出
  │                             出力: output/<id>/inspect/{inputs.json,report.md}
  │
  ├─ Step 2  02_prepare.sh      前処理（GeoTIFF 統一・CRS 付与・図郭外の透過）
  │                             gdalwarp -srcnodata -dstalpha / gdal_translate
  │                             出力: output/<id>/prepared/*.tif
  │                             ※ 不要な場合は自動スキップして元データを直接使う
  │
  ├─ Step 3  03_build_vrt.sh    モザイク結合（gdalbuildvrt）
  │                             出力: output/<id>/merge.vrt
  │
  ├─ Step 4  04_make_tiles.sh   タイル生成（gdal2tiles --xyz）
  │                             出力: output/<id>/tiles/{z}/{x}/{y}.webp
  │
  └─ Step 5  05_make_tilejson.sh  TileJSON 生成
                                出力: output/<id>/tiles/tiles.json
```

各ステップは独立して実行でき、`config/<name>.conf` を第 1 引数に取る。

### 動作実績（オープンデータでの実行例）

`config/shizuoka-city.conf.example` の設定（静岡市 オルソ画像・GSD 0.20 m/px）で
市役所周辺 12 図郭（1.2km × 1.2km、元データ 103 MB）を通した結果:

| 項目 | 値 |
|------|-----|
| 図郭リスト作成（市全域 8,840 図郭） | 27 秒（索引タイル ZL12 を 77 枚取得） |
| ダウンロード＋展開（12 図郭） | 77 秒（並列 4） |
| Step 1〜5（12 図郭 → タイル） | 8 秒（16 並列） |
| 生成タイル | ZL9–19 で 556 枚 / 9.3 MB（WebP 品質85） |

市全域まで広げた場合の目安は、元データ 約 75 GB・タイル 約 36 万枚 / 約 8 GB。

## 設計上の判断

### 最大ズームレベルの決定

タイル解像度が元画像の GSD に**最も近い** ZL を採用する。
これより低い ZL では 1 ピクセルが元画像の複数ピクセルを平均化することになり元データの
解像度を活かしきれず、高い ZL では補間で水増しするだけで情報は増えない。

ZL *z* のタイル解像度（256px タイル）は緯度 φ において

```
res(z) = 156543.033928 × cos(φ) / 2^z   [m/px]
```

なので、採用 ZL は `round(log2(res(0) / GSD))` で求まる。
`tools/inspect_inputs.py` はデータ中心の緯度を使ってこれを計算し、
`report.md` に前後 ZL の解像度比とあわせて出す。

| GSD | 推奨 ZL（北緯 35° 付近） | その ZL の解像度 |
|-----|------------------------|----------------|
| 0.10 m/px | ZL20 | 0.122 m/px |
| 0.25 m/px | ZL19 | 0.245 m/px |
| 0.50 m/px | ZL18 | 0.489 m/px |
| 1.00 m/px | ZL17 | 0.978 m/px |

### 図郭外の透過

図郭単位で分割されたオルソ画像は、撮影範囲外が白または黒で塗られていることがあり、
そのままタイル化すると地図上に四角い枠が見える。`NODATA` に余白色を指定すると
Step 2 で `gdalwarp -srcnodata <色> -dstalpha` によりアルファバンドへ変換する。

余白色はファイル単位で異なる場合があり、また NoData が未設定のファイルが混在すると
そのファイルだけ透過漏れになる。Step 1 の検査でファイル別の NoData 設定と
バンド数（3 バンドと 4 バンドの混在は `gdalbuildvrt` が失敗する）を突き合わせて警告する。

### 出力形式

航空写真は写真系コンテンツのため非可逆圧縮がよく効き、WebP 非可逆で PNG に対して
大幅にサイズを削減できる。既定は `TILE_FORMAT=webp` / `WEBP_QUALITY=85`。

| 設定 | 用途 |
|------|------|
| `WEBP_QUALITY=85` | 標準。背景地図としての視認性は十分 |
| `WEBP_QUALITY=95` | 拡大時の圧縮ノイズを抑えたい場合 |
| `WEBP_QUALITY=lossless` | 可逆が要件の場合（`--webp-lossless`） |
| `TILE_FORMAT=png` | 画素値をパレットで厳密に保持する必要がある場合 |

実データでの削減率は GSD や地物の density に依存するため、案件ごとに
`TILE_FORMAT` / `WEBP_QUALITY` を変えて Step 4 を回し、
`output/<id>/tiles_meta.json` の `total_bytes` を比較して決めるとよい。

## ディレクトリ構成

```
.
├── config/
│   ├── sample.conf.example         … 設定サンプル（実体の *.conf は gitignore）
│   └── shizuoka-city.conf.example  … オープンデータでの実例（Step 0 付き）
├── data/                     … 入力データ（gitignore／オープンデータのみ）
├── output/                   … 中間・出力（gitignore）
├── scripts/
│   ├── 00_build_mesh_list.sh … Step 0-a: 図郭リスト作成（任意）
│   ├── 00_fetch_data.sh      … Step 0-b: 一括ダウンロード（任意）
│   ├── 01_inspect.sh
│   ├── 02_prepare.sh
│   ├── 03_build_vrt.sh
│   ├── 04_make_tiles.sh
│   ├── 05_make_tilejson.sh
│   ├── run_pipeline.sh       … Step 1〜5 の一括実行
│   ├── serve.sh              … ローカルプレビュー
│   └── lib/
│       ├── common.sh         … ログ・設定ロード・共通処理
│       └── prepare_one.sh    … 前処理ワーカー（並列実行される）
├── tools/
│   ├── build_mesh_index.py   … 図郭索引ベクトルタイル → 図郭リスト
│   ├── fetch_meshes.py       … 図郭 ZIP の並列取得・平置き展開
│   ├── inspect_inputs.py     … 入力検査・最大ZL算出
│   └── make_tilejson.py      … TileJSON 生成
└── viewer/
    └── index.html            … MapLibre プレビュー
```

## 参考

- [GDAL: gdal2tiles](https://gdal.org/en/stable/programs/gdal2tiles.html)
- [GDAL: gdalwarp](https://gdal.org/en/stable/programs/gdalwarp.html) / [gdalbuildvrt](https://gdal.org/en/stable/programs/gdalbuildvrt.html)
- [TileJSON 2.2.0 仕様](https://github.com/mapbox/tilejson-spec/tree/master/2.2.0)
- [国土地理院 地理院タイル一覧](https://maps.gsi.go.jp/development/ichiran.html)
