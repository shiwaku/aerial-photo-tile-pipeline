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
| [go-pmtiles](https://github.com/protomaps/go-pmtiles) | MBTiles → PMTiles | 両方 | `pmtiles convert --help` |
| [mbutil](https://github.com/mapbox/mbutil) | XYZ → MBTiles | `PMTILES_VIA="gdal2tiles"`（既定） | `mb-util --help` |
| [rio-mbtiles](https://github.com/mapbox/rio-mbtiles) | MBTiles 生成 | `PMTILES_VIA="rio-mbtiles"` | `rio mbtiles --help` |

```bash
pip install mbutil
pip install rio-mbtiles && pip install "shapely>=2.0"   # ← rio 経路を使う場合のみ
```

## 実行

```bash
# 設定
TILE_OUTPUT="pmtiles"
PMTILES_VIA="gdal2tiles"      # または rio-mbtiles
PMTILES_KEEP_MBTILES="true"   # 中間 MBTiles を残すか
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

## 2 つの経路（`PMTILES_VIA`）

**`pmtiles convert` の入力は MBTiles のみ**（公式 CLI ドキュメントおよび `pmtiles convert --help` で確認）で、タイルディレクトリからの直接変換口はありません。どちらの経路も最後は MBTiles を経由します。

| | `"gdal2tiles"`（既定） | `"rio-mbtiles"` |
|---|---|---|
| 経路 | gdal2tiles → mb-util → convert | rio mbtiles → convert |
| 中間生成物 | XYZ ディレクトリ（大量の小ファイル） | 無し |
| 追加の依存 | `mb-util` | `rio-mbtiles` |

400 図郭・ZL9-19・WebP 品質 85・8 並列での実測:

| 工程 | 経路A: gdal2tiles | 経路B: rio-mbtiles |
|---|---|---|
| タイル生成 | 335 s | 1,093 s |
| MBTiles 化（mb-util） | 85 s | （同上に含む） |
| `pmtiles convert` | 2 s | 40 s |
| **合計** | **422 s** | 1,133 s |

**既定が gdal2tiles なのは 2.7 倍速いからです。** gdal2tiles は最大 ZL を作ってからピラミッドを縮小で積みますが、rio-mbtiles は ZL ごとに元データから warp し直すため低 ZL が重くなります。rio-mbtiles の公式ドキュメントも "suited for small to medium (~1 GB) sized sources" と明記しています。成果物は両経路で同一でした（400 図郭でどちらも 325 MB）。

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
