# 設定リファレンス

設定は `config/<name>.conf` の 1 枚にまとめ、各スクリプトの第 1 引数に渡します。ファイルは bash の変数代入としてそのまま `source` されます。

```bash
cp config/sample.conf.example config/sample.conf
$EDITOR config/sample.conf
./scripts/run_pipeline.sh config/sample.conf
```

既定値は `scripts/lib/common.sh` の冒頭にまとまっています。新しい設定を足す場合はそこに既定値を書き、`config/sample.conf.example` にコメント付きで追記してください。

## 識別子

| 設定 | デフォルト | 説明 |
|---|---|---|
| `DATASET_ID` | （必須） | 出力先ディレクトリ名になる（`output/<DATASET_ID>/`） |
| `DATASET_NAME` | `DATASET_ID` と同じ | TileJSON の `name` に入る表示名 |

## 入力

| 設定 | デフォルト | 説明 |
|---|---|---|
| `SRC_DIR` | （必須） | 画像とワールドファイルを平置きしたディレクトリ。サブディレクトリは辿らない |
| `SRC_EXT` | `auto` | 入力画像の拡張子。`auto` で `tif` / `tiff` / `jpg` / `jpeg` / `png` を拾い、1 データセット内での混在も受け付ける |
| `SRC_SRS` | `auto` | 入力の CRS（例: `EPSG:6676`）。[判定ロジック](#src_srsauto-の判定)を参照 |
| `NODATA` | `auto` | 図郭外の余白色（例: `"255 255 255"`）。空文字で透過処理をしない。[判定ロジック](#nodataauto-の判定)を参照 |

JGD2011 平面直角座標系は 第1系 = EPSG:6669 〜 第19系 = EPSG:6687（系番号 + 6668）です。経緯度なら EPSG:4326、Web メルカトルなら EPSG:3857。

## ズームレベル

| 設定 | デフォルト | 説明 |
|---|---|---|
| `MIN_ZOOM` | `9` | 最小ズームレベル |
| `MAX_ZOOM` | `auto` | `auto` は GSD とデータ中心緯度から算出（[最大 ZL の決め方](design-notes.md#最大ズームレベルの決定)） |

## 出力

| 設定 | デフォルト | 説明 |
|---|---|---|
| `TILE_OUTPUT` | `dir` | `dir`（XYZ ディレクトリ）または `pmtiles`（単一ファイル） |
| `TILE_FORMAT` | `webp` | `webp` または `png` |
| `WEBP_QUALITY` | `85` | 非可逆の品質（1-100）。`lossless` と書くと可逆（`--webp-lossless`） |
| `RESAMPLING` | `average` | 縮小時の再標本化方法（`average` / `near` / `bilinear` / `lanczos` など） |
| `RESUME` | `false` | `true` で既存タイルを残し不足分のみ生成（`gdal raster tile --resume`。古い GDAL では `gdal2tiles -e`）。`TILE_OUTPUT="dir"` のみ |

写真系コンテンツは非可逆圧縮がよく効くため既定は WebP 品質 85 です。削減率は GSD や地物の密度に依存するので、案件ごとに設定を変えて Step 4 を回し、`output/<id>/tiles_meta.json` の `total_bytes` を比較して決めてください。

| 設定 | 用途 |
|---|---|
| `WEBP_QUALITY="85"` | 標準。背景地図としての視認性は十分 |
| `WEBP_QUALITY="95"` | 拡大時の圧縮ノイズを抑えたい場合 |
| `WEBP_QUALITY="lossless"` | 可逆が要件の場合 |
| `TILE_FORMAT="png"` | 画素値をパレットで厳密に保持する必要がある場合 |

### PMTiles 関連（`TILE_OUTPUT="pmtiles"` のときだけ効く）

| 設定 | デフォルト | 説明 |
|---|---|---|
| `PMTILES_NAME` | （空 → `DATASET_ID`） | 成果物のファイル名（拡張子なし）。`tiles.json` が指す名前も追従する |
| `PMTILES_VIA` | `gdal2tiles` | PMTiles の作り方。`gdal2tiles`（XYZ タイルを作ってから書き出す。速い）または `rio-mbtiles`。名前は互換のため据え置きで、タイル生成には `gdal raster tile` を優先して使う |
| `PMTILES_KEEP_MBTILES` | `true` | 変換後に中間 MBTiles を残すか（本番規模で数 GB）。`PMTILES_VIA="rio-mbtiles"` のみ効く |
| `PMTILES_KEEP_TILES` | `true` | 中間の XYZ ディレクトリを残すか（`PMTILES_VIA="gdal2tiles"` のみ。本番規模で数十万ファイル） |

詳細は [PMTiles 出力](pmtiles.md)を参照してください。

## 配信メタデータ

| 設定 | デフォルト | 説明 |
|---|---|---|
| `ATTRIBUTION` | （空） | TileJSON の `attribution`。HTML を書ける（`<a href="...">出典</a>`） |
| `TILE_URL_TEMPLATE` | （空） | 本番のタイル URL テンプレート。空ならローカルプレビュー用の相対パスになる |

`TILE_URL_TEMPLATE` が空のときは、`TILE_OUTPUT="dir"` なら `{z}/{x}/{y}.webp`、`pmtiles` なら `pmtiles://<id>.pmtiles/{z}/{x}/{y}` が入ります。

## 実行環境

| 設定 | デフォルト | 説明 |
|---|---|---|
| `JOBS` | `nproc` | 並列数。16 スレッド機での実測では 8 が妥当（[性能実測](benchmarks.md#ワーカー数)） |
| `VRT_EXTRA_OPTS` | （空） | `gdalbuildvrt` への追加オプション（例: `-resolution highest`） |

## Step 0（任意）: 図郭単位のオープンデータ取得

| 設定 | デフォルト | 説明 |
|---|---|---|
| `MESH_INDEX_URL` | （空） | 図郭索引ベクトルタイルの URL テンプレート（`{z}/{x}/{y}`） |
| `MESH_BOUNDARY` | （空） | 対象範囲の境界 GeoJSON（ファイルパスまたは URL） |
| `MESH_BBOX` | （空） | 境界の代わりに使う範囲（`west,south,east,north`） |
| `MESH_INDEX_ZOOM` | `12` | 索引タイルを取得する ZL |
| `MESH_FIELD` | `MESH_NO` | 索引の図郭コード属性名 |
| `MESH_URL_FIELD` | `URL` | 索引のダウンロード URL 属性名 |
| `MESH_NEAR` | （空） | サンプル抽出: この地点（`lon,lat`）に近い図郭に絞る |
| `MESH_COUNT` | （空） | サンプル抽出: 抽出件数（`MESH_NEAR` と併用） |
| `FETCH_LIMIT` | （空） | 取得を先頭 N 件に制限する（`00_fetch_data.sh --limit N` でも指定できる） |
| `FETCH_JOBS` | `4` | 並列ダウンロード数。回線帯域が律速なので 8〜12 が上限（[性能実測](benchmarks.md)） |

`MESH_BOUNDARY` と `MESH_BBOX` はどちらか一方が必須です。詳細は[図郭データの取得](mesh-fetch.md)を参照してください。

## `auto` の判定

`auto` の解決は **Step 1 の検査結果（`output/<id>/inspect/inputs.json`）を唯一の根拠**にします。各ステップがバラバラに判定すると、判定根拠がレポートと食い違って追えなくなるためです。判定内容は必ず `output/<id>/inspect/report.md` に出るので、鵜呑みにせず確認してから流してください。

| 設定 | `auto` の判定内容 |
|---|---|
| `SRC_EXT="auto"` | `tif` / `tiff` / `jpg` / `jpeg` / `png` を拾う。混在も可 |
| `SRC_SRS="auto"` | 画像に CRS があればそれを使う。無ければ図郭コード先頭 2 桁の系番号を、座標値がその系の適用範囲に収まるかで検証して確定する |
| `NODATA="auto"` | 外周 4px を実測して余白色を判定する。余白が無ければ透過処理をしない |
| `MAX_ZOOM="auto"` | GSD（ワールドファイル由来でも可）とデータ中心緯度から算出する |

このほか、明示設定なしで吸収するものがあります。

- **GSD の取得元**: 画像内部のジオリファレンスとワールドファイル（`.tfw` / `.jgw`）のどちらから来た値かを判定してレポートに出す。混在していれば警告する
- **バンド数の混在**: 3 バンドと 4 バンドが混ざると `gdalbuildvrt` が失敗するため、混在を検出したら Step 2 で全ファイルにアルファバンドを付けて揃える
- **GSD の混在**: `gdalbuildvrt -resolution highest` で最も細かい解像度に合わせる（既定の平均だと細かい方の情報が落ちる）
- **図郭サイズ**: 地上サイズから地図情報レベル（1/500〜1/5,000）を判定してレポートに出す

### `SRC_SRS="auto"` の判定

**系番号は座標値だけでは決められません。** 平面直角座標系は 19 系すべてが自系の適用範囲内に原点を持つため、ある (x, y) は多くの系で「適用範囲内」に落ちます。実測では 13 系が候補として残りました。

```
| 座標値から見てありえる系 | EPSG:6669, EPSG:6670, EPSG:6671, EPSG:6673, EPSG:6674,
                            EPSG:6675, EPSG:6676, EPSG:6677, EPSG:6678, EPSG:6679,
                            EPSG:6680, EPSG:6681, EPSG:6682 |
```

そのため判定の第一根拠は**図郭コード先頭 2 桁**（国土基本図の図郭コードで系番号を表す規約）とし、座標値は妥当性検証にのみ使います。この順序を逆にすると誤った系を自信満々に返します。

図郭コードでない命名規則のデータでは自動判定できないため、`SRC_SRS` を明示してください。

### `NODATA="auto"` の判定

外周 4px を実測し、2 段階で判定します。

1. 外周に**純白（255,255,255）または純黒（0,0,0）が 2% 以上**あればそれを余白とする。航空写真の地物は全バンドが飽和することがほとんど無いため、少量でも余白の証拠になる。純白と純黒が混在した場合は自動判定せず、手動指定を促す
2. 純白・純黒以外の色の場合は、**外周の 50% 以上が単色**で埋まっていることを要求する（地物の色を誤って余白と判定しないため）

実測では、余白なしのデータセットは 12 ファイルすべてで純白 0px、余白ありのデータセットは 8/12 ファイルの外周に純白が 3〜82% ありました。

> **余白が無いデータに `NODATA` を指定しないでください。** 図郭が隅まで画像化されている配布形式では余白が存在せず、`"0 0 0"` は影を、`"255 255 255"` は白飽和部分を誤って透過させます。Step 1 の検査結果と、整備範囲の縁にある図郭の画素を実際に確認してから決めてください。

`NODATA` が解決されている場合、Step 2 が `gdalwarp -srcnodata <色> -dstalpha` でアルファバンドへ変換します。その場合 Step 4 では `--srcnodata` を渡しません。

## 前処理（Step 2）がスキップされる条件

次の 4 条件が揃うと Step 2 は何もせず、Step 3 が元データから直接 VRT を作ります。

- `NODATA` が空（透過処理が不要）
- 入力がすべて tif
- CRS が判定済み
- バンド数が一致している

また Step 2 は出力が入力より新しければファイル単位でスキップするため、中断・再実行に耐えます。
