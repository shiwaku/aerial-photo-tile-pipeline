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
| `tools/mbtiles_meta.py` | PMTiles 変換前の MBTiles metadata 補正（stdlib のみ） |
| `tools/serve_range.py` | HTTP Range 対応の静的サーバ（PMTiles プレビュー用・stdlib のみ） |

## 設計上の決めごと

- **`auto` 値の解決は Step 1 の検査結果を唯一の根拠にする**。
  `SRC_EXT` / `SRC_SRS` / `NODATA` / `MAX_ZOOM` は `auto` を受け付ける。
  解決は `common.sh` の `resolve_srs()` / `resolve_nodata()` に集約し、
  各ステップがバラバラに判定しないこと（判定根拠がレポートと食い違うと追えなくなる）。
- **最大ZL**: タイル解像度が GSD に最も近い ZL を採用。
  `round(log2(res(0) / GSD))`（`res(0) = 156543.033928 × cos(φ)`、φ はデータ中心緯度）。
  設定 `MAX_ZOOM="auto"` でこれを使い、数値指定で上書きできる。
- **系番号（`SRC_SRS="auto"`）は座標値だけでは決められない**。
  平面直角座標系は 19 系すべてが自系の適用範囲内に原点を持つため、ある (x, y) は
  多くの系で「適用範囲内」に落ちる（実測で 13 系が候補として残った）。
  したがって判定の第一根拠は**図郭コード先頭 2 桁**（国土基本図の図郭コードの規約）とし、
  座標値は妥当性検証にのみ使う。この順序を逆にすると誤った系を自信満々に返すので注意。
- **透過処理**: `NODATA` が解決されている場合は Step 2 で
  `gdalwarp -srcnodata <色> -dstalpha`。その場合 Step 4 では `--srcnodata` を渡さない。
  `NODATA="auto"` は外周 4px の実測で余白の有無を判断する。判定は 2 段階で、
  純白・純黒は 2% 以上（航空写真の地物は全バンド飽和しにくいため少量でも証拠になる）、
  それ以外の色は外周の 50% 以上を要求する。純白と純黒が混在したら自動判定しない。
  余白が無いデータに値を指定すると影（純黒）や白飽和部分を誤透過させる。
  実測: 余白なしのデータセットは 12 ファイルすべて純白 0px、
  余白ありのデータセットは 8/12 ファイルの外周に純白が 3〜82% あった。
- **バンド数の混在**: 3/4 バンドが混ざると `gdalbuildvrt` が失敗するため、Step 2 が
  混在を検出したら `NODATA` 指定が無くても `-dstalpha` で全ファイルを 4 バンドに揃える。
- **前処理のスキップ**: `NODATA` が空・入力がすべて tif・CRS 判定済み・バンド数一致の
  4 条件が揃えば Step 2 は何もせず、Step 3 が元データから直接 VRT を作る。
- **gdalwarp / gdal_translate には `-of GTiff` を必ず付ける**。
  出力を `<名前>.part` に書いてから `mv` する方式のため、拡張子からドライバを
  推測できずエラーメッセージも出ずに失敗する。
- **VRT 経由**: `gdal2tiles` は 1 ファイルしか受け付けないため必ず VRT を作る。
  ファイル数が多くても引数長制限に当たらないよう `-input_file_list` を使う。
- **出力形式**: 既定は WebP 非可逆 品質85。`TILE_FORMAT=png` で PNG。
- **出力形態（`TILE_OUTPUT`）**: `dir`（既定・gdal2tiles で XYZ ディレクトリ）と
  `pmtiles`（rio-mbtiles → MBTiles → `pmtiles convert`）の 2 系統。Step 5 は
  設定ではなく `tiles_meta.json` の `output` を見て分岐する
  （設定を後から変えると実体と食い違うため）。
- **PMTiles 経路で GDAL の MBTiles ドライバを使わない理由**: GDAL 3.11 の
  MBTiles ドライバには `ZOOM_LEVEL` 作成オプションが無く（あるのは
  `ZOOM_LEVEL_STRATEGY` だけ）、解像度から ZL が自動決定されるため `MAX_ZOOM`
  を尊重できない。ZL を合わせるには入力を目的 ZL の解像度へスナップさせる
  細工が要る。rio-mbtiles は `--zoom-levels MIN..MAX` で明示できるため、そちらを使う。
  なお `gdalwarp -of MBTILES` は Create() 経路で「解像度が ZL と完全一致」を
  要求して失敗する。`gdal_translate`（CreateCopy）なら 3857 へ自動再投影される。
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
- **同じ図郭が複数タイルに現れたらジオメトリを Union する。** ベクトルタイルは
  各タイル内でジオメトリがクリップされて格納されるため、最初に見つけた 1 枚だけを
  採用すると境界をまたぐ図郭の外側が欠ける。静岡市では 1,612 図郭が該当し、
  欠けたポリゴンが境界交差判定から漏れて対象図郭が 4 件不足していた。
- **索引タイルのキャッシュは索引 URL ごとに分ける。** `z/x/y` だけをキーにすると
  別データセットの索引が同じパスに衝突し、図郭が混ざる（実際に踏んだ）。
  `build_mesh_index.py` は `--cache-dir` の下に索引 URL の SHA1 先頭 10 桁で
  サブディレクトリを作る。
- 図郭コードの先頭 2 桁は平面直角座標系の系番号として使われていることが多く、
  `SRC_SRS` の裏取りに使える（例: `08...` → 第VIII系 = EPSG:6676）。
- `NODATA` を安易に設定しないこと。図郭が隅まで画像化されている配布形式では
  余白が存在せず、`"0 0 0"` は影、`"255 255 255"` は白飽和部分を誤透過させる。
  Step 1 の検査結果と、整備範囲の縁にある図郭の画素を実際に確認してから決める。

## PMTiles 出力（`TILE_OUTPUT="pmtiles"`）の実測メモ

オープンデータ 12 図郭で end-to-end 検証して確認した事実。

- **`pmtiles convert` の入力は MBTiles のみ**（公式 CLI ドキュメントおよび
  `pmtiles convert --help` で確認）。タイルディレクトリからの直接変換口は無い。
  どの経路を選んでも最後は必ず MBTiles を経由する。
- **go-pmtiles は center の経度を桁あふれさせる。日本全域が該当する。**
  metadata に `center` が無いと go-pmtiles が `bounds` から計算するが、
  経度を E7 の int32 で「先に加算してから 2 で割る」実装のため、
  経度の和が 214.7483647 度（= 2³¹ / 10⁷）を超えるとあふれる。
  東経 138 度なら和は約 277 度で確実に該当し、center が -76 度付近に化ける。
  実測: `(1383773285 + 1383904847) - 2³² = -1527289164`、÷2 で -76.3644582。
  PMTiles v3 仕様は center を int32 E7 で持つので値自体は表現できる。
  あふれるのは go-pmtiles の途中計算だけ。
  **回避策は metadata に `center` を明示すること**（あれば go-pmtiles は計算しない）。
  `tools/mbtiles_meta.py` がここを担当する。producer（GDAL / rio-mbtiles）を
  変えても再現するので、producer 側の問題ではない。
- **rio-mbtiles は `minzoom` / `maxzoom` / `center` を metadata に書かない**
  （書くのは name / type / version / description / format / bounds のみ）。
  min/max zoom は `pmtiles convert` が tiles テーブルから導出するので実害は無いが、
  center は上記のとおり壊れる。
- **rio-mbtiles 1.6.0 は初回実行が必ず落ちる。**
  `--overwrite`（既定）かつ出力ファイルが存在しないとき、`appending` が
  どの分岐でも代入されないままクロージャから参照され `NameError` になる
  （`mbtiles/scripts/cli.py` の `init_mbtiles`）。
  ```python
  if append:              appending = output_exists
  elif output_exists:     appending = False      # ← 出力が無いとどちらにも入らない
  ```
  **出力を空ファイルで先に作れば上書き経路に入って正常動作する。**
- **rio-mbtiles は `shapely~=1.7.0` をハード pin している。**
  素直に `pip install` すると shapely 2.x が 1.7.1 へダウングレードされ、
  geopandas や mapbox-vector-tile が壊れる。実行時は shapely 2.1.2 でも
  問題なく動く（pin は宣言のみ）ので、**インストール後に shapely を戻すこと**。
- **PMTiles 出力では VRT にアルファバンドが要る（`-addalpha`）。**
  忘れると**整備範囲の外側が透過ではなく黒 (0,0,0) で塗られ、写真の外枠が黒くなる**。
  gdal2tiles は範囲外を自前でアルファ 0 にするため dir 経路では起きず、
  PMTiles 経路だけで出る。原因は NoData の設定ではない（余白の無いデータでも出る）。
  rio-mbtiles の `--rgba` は入力 4 バンド以上が条件なので、3 バンドのままだと
  アルファを持てず 0 = 黒が残る。Step 3 が `TILE_OUTPUT="pmtiles"` かつ
  入力 3 バンドのとき `-addalpha` を付け、Step 4 が 4 バンドを検出して `--rgba` を渡す。
  実測: 端タイルの四隅が `(0,0,0)` → `(0,0,0,0)` になり gdal2tiles と一致した。
  なお完全不透明なタイルは WebP 側でアルファが落ちて RGB になる（正常）。
- **NoData の色指定は rio-mbtiles では表現できない。** `--src-nodata` は
  単一 FLOAT で、このリポジトリが使う `"255 255 255"` のような RGB 指定を
  受け付けない。透過は Step 2 の前処理でアルファバンドを付け、Step 4 は
  4 バンドを検出したら `--rgba` を渡す、という既存の流れに乗せる。
  `--rgba` は PNG / WEBP のみ・入力 4 バンド以上が条件。
- **`python3 -m http.server` は Range 非対応なので PMTiles を配信できない。**
  PMTiles は 1 ファイルの中を Range で部分読みする。標準の http.server は
  Range を実装しておらず常に全体を 200 で返すため読めない。
  プレビュー用に `tools/serve_range.py` を用意した。
- PMTiles v3 の `tile_type` は WebP = 4（PNG = 2 / JPEG = 3 / AVIF = 5）。
  `pmtiles show` の `tile type: webp` で確認できる。

## 開発時の注意

- スクリプトは `set -euo pipefail` 前提。`common.sh` を `source` してから使う。
- 設定値の既定は `common.sh` の冒頭にまとめてある。新しい設定を足す場合は
  そこに既定値を書き、`config/sample.conf.example` にコメント付きで追記する。
- ファイル名の空白・日本語に耐えるよう、入力列挙は `find -print0` + `mapfile -d ''`
  で NUL 区切りにしている。この方針を崩さないこと。
- ステップ間の受け渡しはファイル経由（`inspect/inputs.json`、`tiles_meta.json`）。
  環境変数で暗黙に渡さない（`prepare_one.sh` へのワーカー引数だけは例外）。
- 長時間ジョブの進捗を `print` で出す場合は `flush=True` を付ける。
  ログにリダイレクトするとブロックバッファリングされ、数時間何も見えなくなる。

## 実測メモ（性能）

オープンデータでの実測値。高速化の検討はここが出発点。

- **図郭 ZIP のダウンロードは回線帯域が律速**。単一接続 9.3 MB/s、6 並列 11.2 MB/s、
  12 並列で実効 67 図郭/分（約 8 MB/s）。24 並列にすると 50 図郭/分に**低下**する。
  `FETCH_JOBS` は 8〜12 が妥当で、増やしても意味がない。
  なお `/mnt/c`（drvfs）への書き込みは 209 MB/s 出ており律速ではない。
- **タイル生成は 12 図郭（1.44 km²・GSD 0.20 m/px）で 8 秒**（16 並列、ZL9-19、
  WebP 品質85、556 枚 9.3 MB）。線形換算で 8,840 図郭なら約 1.6 時間。
- **PMTiles 経路は同条件で 30 秒**（`rio mbtiles -j 16` が 30 秒、
  `pmtiles convert` が 1.2 秒）。同じ 556 枚・ZL9-19 で 9.2 MB。
  つまり **gdal2tiles の約 3.7 倍遅い**。線形換算で 8,840 図郭なら約 6 時間。
  gdal2tiles が最大ZLのタイルを作ってからピラミッドを縮小で積むのに対し、
  rio-mbtiles は ZL ごとに元データから warp し直すため。
  なお rio-mbtiles の公式ドキュメントは
  "suited for small to medium (~1 GB) sized sources" と明記している。
  大規模データセットに使う前に、この 2 点（所要時間・想定サイズ）を確認すること。
