# PMTiles 出力

`TILE_OUTPUT="pmtiles"` にすると、タイルを単一ファイル（PMTiles アーカイブ）にまとめます。タイルの中身（WebP / ZL 範囲 / リサンプリング）は XYZ ディレクトリ出力と同じ設定が効きます。

| | `TILE_OUTPUT="dir"`（既定） | `TILE_OUTPUT="pmtiles"` |
|---|---|---|
| 出力 | `output/<id>/tiles/{z}/{x}/{y}.webp` | `output/<id>/<id>.pmtiles` |
| TileJSON | `output/<id>/tiles/tiles.json` | `output/<id>/tiles.json` |
| 配信 | 静的ホスティングにそのまま置ける | HTTP Range 対応のホスティングが必要 |
| 途中再開 | `RESUME="true"` で不足分のみ生成 | 非対応（毎回作り直し） |

PMTiles を選ぶ主な理由は**小さいファイルが大量にできないこと**です。本番実測では 366,827 ファイル → 1 ファイル（約 7.5 GB）になりました。配布・バックアップ・同期のほか、削除にも効きます。36 万ファイルの `rm -rf` は drvfs 上で 10 分 26 秒かかり、`du -sh` は事実上返ってきません。

## 必要なもの

| ツール | 用途 | 必要な経路 | 確認 |
|---|---|---|---|
| [pmtiles](https://pypi.org/project/pmtiles/) | PMTiles の直接書き出し | `PMTILES_VIA="gdal2tiles"`（既定） | `python3 -c "import pmtiles"` |
| [go-pmtiles](https://github.com/protomaps/go-pmtiles) | MBTiles → PMTiles | `PMTILES_VIA="rio-mbtiles"` | `pmtiles convert --help` |
| [rio-mbtiles](https://github.com/mapbox/rio-mbtiles) | MBTiles 生成 | `PMTILES_VIA="rio-mbtiles"` | `rio mbtiles --help` |

```bash
pip install pmtiles                                     # 既定の経路に必要
pip install rio-mbtiles && pip install "shapely>=2.0"    # ← rio 経路を使う場合のみ
```

`pmtiles` パッケージは依存ゼロの純 Python なので、`pip install` で他のパッケージを巻き込むことはありません（rio-mbtiles とは対照的）。

なお go-pmtiles の `pmtiles` コマンドは既定の経路では不要ですが、生成物を確認する `pmtiles show` に使うので入れておくと便利です。

## 実行

```bash
# 設定
TILE_OUTPUT="pmtiles"
PMTILES_VIA="gdal2tiles"      # または rio-mbtiles
PMTILES_KEEP_MBTILES="true"   # 中間 MBTiles を残すか（rio-mbtiles 経路のみ）
PMTILES_KEEP_TILES="true"     # 中間の XYZ ディレクトリを残すか

# 実行（Step 1〜5 は共通）
./scripts/run_pipeline.sh config/sample.conf
./scripts/serve.sh        config/sample.conf      # Range 対応サーバで起動する
```

生成物の確認:

```bash
pmtiles show output/sample/sample.pmtiles
#   tile type: webp
#   min zoom: 9 / max zoom: 19
#   center: (long: 138.383908, lat: 34.975052)   ← 経度が正しいこと
```

PMTiles v3 の `tile_type` は WebP = 4（PNG = 2 / JPEG = 3 / AVIF = 5）です。

Step 5 は設定ではなく `output/<id>/tiles_meta.json` の `output` を見て出力形態を分岐します。設定を後から変えると実体と食い違うためです。

## 成果物のファイル名（`PMTILES_NAME`）

既定のファイル名は `DATASET_ID` です。配信先で他のデータと同じディレクトリに並べる場合、地域名より中身が分かる名前にしたいことがあるため `PMTILES_NAME` で上書きできます。

```bash
DATASET_ID="shizuoka-city"
PMTILES_NAME="aerial-photo"     # → output/shizuoka-city/aerial-photo.pmtiles
```

中間の MBTiles も同じ名前になり、**`tiles.json` が指す名前も追従します**（`TILE_URL_TEMPLATE` が空なら Step 5 が `PMTILES_FILE` の basename から相対 URL を組む）。

> **アップロード時に手でリネームしないでください。** `tiles.json` は生成時のファイル名を指しているため、実体だけ改名すると PMTiles が 404 になります。名前を変えたいときは `PMTILES_NAME` を設定し、既存の成果物を `mv` してから Step 5 を再実行してください（タイルの作り直しは不要です）。

## 2 つの経路（`PMTILES_VIA`）

| | `"gdal2tiles"`（既定） | `"rio-mbtiles"` |
|---|---|---|
| 経路 | gdal2tiles → PMTiles 直接書き出し | rio mbtiles → `pmtiles convert` |
| 中間生成物 | XYZ ディレクトリ（大量の小ファイル） | MBTiles |
| 追加の依存 | `pmtiles`（Python） | `rio-mbtiles` ＋ go-pmtiles |

**既定が gdal2tiles なのは 2.7 倍速いからです。** gdal2tiles は最大 ZL を作ってからピラミッドを縮小で積みますが、rio-mbtiles は ZL ごとに元データから warp し直すため低 ZL が重くなります。rio-mbtiles の公式ドキュメントも "suited for small to medium (~1 GB) sized sources" と明記しています。成果物は両経路で同一でした（400 図郭でどちらも 325 MB）。

`"rio-mbtiles"` は中間の XYZ ディレクトリを作らずに済むのが利点です。数十万の小ファイルを置く余裕が無い場合の選択肢として残しています。

### なぜ MBTiles を経由しなくなったか

`pmtiles convert`（go-pmtiles）の入力は MBTiles のみで、タイルディレクトリからの直接変換口はありません。そのため以前は `mb-util` で MBTiles を作ってから変換していましたが、**中間の SQLite は変換の入力を作るためだけに存在し、2 つの工程が丸ごと無駄でした**。

- `mb-util` は無条件に `VACUUM` する。7.65 GB を丸ごと書き直すが、直後に捨てるファイルなので詰める意味がない（CLI に止めるオプションは無い。`--do_compression` はタイルの重複排除で別物）
- `pmtiles convert` は、一度 SQLite に入れたものを読み直しているだけ

PyPI の `pmtiles` パッケージの `Writer` はタイルを直接書けるので、SQLite を挟まなければどちらも消えます。本番 366,827 枚（7.5 GB）での実測:

| 工程 | 旧（mb-util 経由） | 現行（直接書き出し） |
|---|---|---|
| 走査 | — | 9 s |
| mb-util 挿入 | 1,420 s | — |
| mb-util `VACUUM` | 1,687 s | — |
| `pmtiles convert` | 823 s | — |
| 直接書き出し | — | 1,326 s |
| **合計** | **3,930 s（65分30秒）** | **1,336 s（22分16秒）** |

**43 分 14 秒（66%）の削減**です。出力はバイト単位で同一であることを確認しています（全 11 ZL から 2,475 枚を抽出して相違ゼロ、`pmtiles show` の意味的項目もすべて一致）。

削減の実体は「無駄な 2 工程が消えた」ことで、タイルの読み込み自体は 305 枚/秒と mb-util の 258 枚/秒に対して 18% しか速くありません。**ボトルネックは drvfs から小ファイルを読むこと**なので、入力を ext4 に置けばさらに縮む余地があります。

### `Writer` を使ううえでの注意

`pmtiles` 3.7.0 の実装を読んで確認した事実です。

- **重複排除と run-length は Writer が持っている**（同一バイト列は 1 度だけ格納され、連続する同一タイルはまとめられる）。自前で行う必要はない
- **tileid（ヒルベルト順）の昇順で書かないと `clustered` が false になる**。`finalize()` はエントリを並べ替えるがタイル本体の並びは書いた順のままなので、範囲リクエストの局所性が落ちる。`tools/dir_to_pmtiles.py` は並べ替えてから書いている
- **タイル本体は一時ファイルに溜めてから出力へコピーされる**。`TMPDIR` に出力と同じ容量が必要になる。WSL2 では既定の `/tmp` が ext4 なので、drvfs への書き込みは 1 回で済む
- center を渡さないと Writer が `bounds` から計算するが、**Python の int は任意精度なので go-pmtiles のような桁あふれは起きない**。それでも値を明示している

## 既知の落とし穴

### `center` の経度が桁あふれする（日本全域が該当）

> **`pmtiles show` の `center` は必ず確認してください。**

metadata に `center` が無いと go-pmtiles が `bounds` から計算しますが、経度を E7 の int32 で「先に加算してから 2 で割る」実装のため、**経度の和が 214.7483647 度（= 2³¹ / 10⁷）を超えるとあふれます**。東経 138 度なら和は約 277 度で確実に該当し、center が -76 度付近（北米東岸沖）に化けます。

```
(1383773285 + 1383904847) - 2³² = -1527289164   ÷2 → -76.3644582
```

PMTiles v3 仕様は center を int32 E7 で持つので値自体は表現できます。あふれるのは go-pmtiles の途中計算だけです。**回避策は metadata に `center` を明示すること**で（あれば go-pmtiles は計算しない）、`tools/mbtiles_meta.py` がこれを担当します。producer（GDAL / rio-mbtiles）を変えても再現するので、producer 側の問題ではありません。

### rio-mbtiles 1.6.0 は初回実行が必ず落ちる

`--overwrite`（既定）かつ出力ファイルが存在しないとき、`appending` がどの分岐でも代入されないままクロージャから参照され `NameError` になります（`mbtiles/scripts/cli.py` の `init_mbtiles`）。

```python
if append:              appending = output_exists
elif output_exists:     appending = False      # ← 出力が無いとどちらにも入らない
```

**出力を空ファイルで先に作れば上書き経路に入って正常動作します。**

### rio-mbtiles は shapely 1.7 をハード pin している

`shapely~=1.7.0` を要求するため、素直に `pip install` すると shapely 2.x が 1.7.1 へダウングレードされ、geopandas や mapbox-vector-tile が壊れます。実行時は shapely 2.1.2 でも問題なく動く（pin は宣言のみ）ので、**インストール後に shapely を戻してください**。`pip` は依存の警告を出しますが動作に影響はありません。既定の gdal2tiles 経路なら rio-mbtiles は不要で、この問題も起きません。

### rio-mbtiles では NoData の色指定ができない

`--src-nodata` は単一 FLOAT で、このリポジトリが使う `"255 255 255"` のような RGB 指定を受け付けません。透過は Step 2 の前処理でアルファバンドを付け、Step 4 は 4 バンドを検出したら `--rgba` を渡す、という既存の流れに乗せています（`--rgba` は PNG / WEBP のみ・入力 4 バンド以上が条件）。

### `python3 -m http.server` では配信できない

PMTiles は 1 ファイルの中を HTTP Range で部分読みします。標準の `http.server` は Range を実装しておらず常に全体を 200 で返すため読めません。プレビュー用に `tools/serve_range.py` を用意しており、`scripts/serve.sh` はこちらを使います。

### GDAL の MBTiles ドライバを使わない理由

GDAL 3.11 の MBTiles ドライバには `ZOOM_LEVEL` 作成オプションが無く（あるのは `ZOOM_LEVEL_STRATEGY` だけ）、解像度から ZL が自動決定されるため `MAX_ZOOM` を尊重できません。ZL を合わせるには入力を目的 ZL の解像度へスナップさせる細工が要ります。rio-mbtiles は `--zoom-levels MIN..MAX` で明示できるため、そちらを使っています。

なお `gdalwarp -of MBTILES` は Create() 経路で「解像度が ZL と完全一致」を要求して失敗します。`gdal_translate`（CreateCopy）なら 3857 へ自動再投影されます。
