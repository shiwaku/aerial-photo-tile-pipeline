# ビューワ

`viewer/` は生成したタイルを確認する MapLibre GL JS のビューワ（Vite + TypeScript）です。単一 HTML ではないため、使う前にビルドが要ります（Node.js 18 以上）。

```bash
cd viewer
npm install
npm run build        # → viewer/dist/
npm run dev          # 開発サーバ（http://localhost:5173/）
npm run deploy       # GitHub Pages へ（gh-pages）
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

タイル自体の URL は TileJSON の `tiles[]` に入るため、パイプライン側で `TILE_URL_TEMPLATE` を設定してから Step 5 を実行してください。

```bash
TILE_URL_TEMPLATE="https://example.com/ortho/tiles/{z}/{x}/{y}.webp"
```

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
