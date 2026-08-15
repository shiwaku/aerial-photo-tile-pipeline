# ビューワ

`viewer/` は生成したタイルを確認する MapLibre GL JS のビューワ（Vite + TypeScript）です。単一 HTML ではないため、使う前にビルドが要ります（Node.js 18 以上）。

```bash
cd viewer
npm install
npm run build        # → viewer/dist/（ローカルプレビュー用）
npm run dev          # 開発サーバ（http://localhost:5173/）
npm run build:pages  # GitHub Pages 用のビルド（.env.pages を読む）
npm run deploy       # build:pages してから gh-pages へ publish
```

ビルドしたら、パイプラインの設定を渡してローカルサーバを起動します。

```bash
./scripts/serve.sh config/sample.conf          # http://localhost:8080/
./scripts/serve.sh config/sample.conf 3000     # ポートを変える
```

`scripts/serve.sh` は `viewer/dist/` を作業ディレクトリ（`output/<id>/`）へ複製して配信します。タイルと同一オリジンでないと `tiles.json` を相対で探せないためです。配信には `tools/serve_range.py` を使います（PMTiles は HTTP Range で部分読みするため、Range 非対応の `python3 -m http.server` では配信できない）。

## 機能

- 背景地図の切替（淡色 / 標準 / 写真 / 白図）
- ライト / ダークテーマ
- オルソ画像の不透明度スライダー
- 整備範囲へのフィット
- URL ハッシュでの位置保持
- PWA 対応（`manifest.webmanifest` / `sw.js`）

背景の「淡色」「標準」は国土地理院の最適化ベクトルタイル、「写真」は全国最新写真（シームレス）です。「白図」を選ぶと背景が消え、生成したオルソタイルだけを確認できます。

## 出力形態の自動判別

ビューワは設定を持たず、`tiles.json` を **`tiles.json` → `tiles/tiles.json` の順**に探します。見つかった TileJSON の `tiles[]` が `pmtiles://` で始まるかどうかで配信形態を判別し、PMTiles なら protocol を登録します。

```
TILE_OUTPUT="dir"     … output/<id>/tiles/tiles.json  + tiles/{z}/{x}/{y}.webp
TILE_OUTPUT="pmtiles" … output/<id>/tiles.json        + pmtiles://<id>.pmtiles/{z}/{x}/{y}
```

## タイルを別ホストに置く場合

TileJSON の場所を `VITE_TILEJSON_URL` で指定してビルドします。

```bash
VITE_TILEJSON_URL=https://example.com/ortho/tiles.json npm run build
```

**TileJSON をタイル（または PMTiles）と同じディレクトリに置けば、それ以外の設定は要りません。** ビューワは `tiles[]` の相対 URL を TileJSON の URL 基準で解決するため、パイプラインが生成した `tiles.json` をそのままアップロードできます。

TileJSON だけを別の場所（ビューワと同じオリジンなど）に置く場合は、`tiles[]` を絶対 URL にする必要があります。パイプライン側で `TILE_URL_TEMPLATE` を設定してから Step 5 を実行してください。

```bash
TILE_URL_TEMPLATE="https://example.com/ortho/tiles/{z}/{x}/{y}.webp"
TILE_URL_TEMPLATE="pmtiles://https://example.com/ortho/aerial-photo.pmtiles/{z}/{x}/{y}"
```

## GitHub Pages で公開する

ビューワを GitHub Pages に、タイルを別ホストに置く構成です。`vite.config.ts` の `base` はビルド時に `./` になるため、Pages のサブパス（`https://<user>.github.io/<repo>/`）でもそのまま動きます。

TileJSON の URL は `viewer/.env.pages` に書いてあり、`npm run deploy` が読みます。デプロイのたびに環境変数を手で付ける必要はありません。

```bash
# viewer/.env.pages
VITE_TILEJSON_URL=https://example.com/ortho/tiles.json
```

```bash
cd viewer
npm run deploy
```

> **`.env.pages` は `--mode pages` のビルドでだけ読まれます。** ローカルプレビュー用の `npm run build` は読まないため、`scripts/serve.sh` では従来どおりタイルと同一オリジンの `tiles.json` を相対で探します。両者を分けているのは、本番 URL を焼き込んだ `dist/` でローカルプレビューすると、手元のタイルではなく公開中のタイルを見てしまうためです。
>
> 逆に、**`.env.pages` に URL を書かずに `npm run deploy` すると、ビューワが `tiles.json` を相対で探して 404 になり、白い地図が公開されます。**

配信ホスト側に必要な条件は 2 つです。

| 条件 | 確認方法 |
|---|---|
| HTTP Range に対応している（PMTiles の場合） | `curl -D - -o /dev/null -H 'Range: bytes=0-99' <url>` が `206` を返す |
| CORS を許可している | 同じリクエストに `Origin:` を付けて `access-control-allow-origin` が返る |

PMTiles を配信する場合、[protomaps のドキュメント](https://docs.protomaps.com/pmtiles/cloud-storage)は `Range` / `If-Match` リクエストヘッダの許可と、`ETag` / `Access-Control-Allow-Origin` / `Access-Control-Allow-Methods`（GET, HEAD）レスポンスヘッダを挙げています。

**タイル自体を GitHub Pages に置く場合は容量に注意してください。** [公開サイトの上限は 1 GB](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)、帯域は月 100 GB（ソフト）です。本番規模の PMTiles（実測 7.9 GB）は収まりません。サンプル規模（12 図郭で 9.3 MB）なら問題ありません。

なお公開はデータの再配布にあたります。入力データのライセンス条件を確認し、`ATTRIBUTION` に出典表記を入れてください（ビューワの著作権表示に出ます）。

## ソース構成

```
viewer/
├── index.html
├── package.json
├── vite.config.ts
├── public/               # icon.svg / manifest.webmanifest / sw.js / pale.json / std.json
└── src/
    ├── main.ts           # 地図・パネル・背景切替
    ├── basemap.ts        # 淡色 / 標準 / 写真 / 白図
    ├── ortho.ts          # TileJSON 読み込みとソース組み立て
    ├── theme.ts          # ライト / ダーク
    └── style.css
```
