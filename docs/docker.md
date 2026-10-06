# Docker で実行する

同梱の `Dockerfile` のイメージには、実行環境（GDAL 3.13 + `pmtiles`）とスクリプト一式が入っています。手元に要るのは Docker と作業フォルダだけで、GDAL や Python を入れる必要はありません。

## 対応環境

| 環境 | ラッパー | 確認状況 |
|---|---|---|
| macOS（Apple Silicon / Intel） | `docker-run.sh` | Apple Silicon の実機で確認 |
| Linux（amd64 / arm64） | `docker-run.sh` | CI（GitHub Actions のクラウド上の Ubuntu）で PR ごとに selftest まで確認 |
| Windows + WSL2 | `docker-run.sh`（WSL の Ubuntu などから） | 実機で確認（Ubuntu 24.04）。CI では見ていない |
| Windows + PowerShell | `docker-run.ps1` | 実機で確認（Windows PowerShell 5.1 / PowerShell 7.6）。CI（クラウド上の Windows Server）で見ているのは改行と構文だけ |

Windows の実機確認は、Windows 11 Pro（10.0.26200）・Docker Desktop 4.38.0・AMD Ryzen 7 5700X で行いました（#17）。selftest の所要は、WSL2 で 9 秒、PowerShell で 16〜19 秒です。

イメージは Linux コンテナなので、どの OS でも中身は同じように動きます。OS ごとに違うのは、ホストとコンテナのつなぎ方（ラッパー・マウント・改行コード・スリープ抑止）だけです。

## 1. 準備する

以降のコマンドは、上から順にそのままコピーして実行できるように書いています。リポジトリはホームフォルダ（`~/aerial-photo-tile-pipeline`）に置く前提です。

### Docker Desktop を起動する

macOS と Windows では、先に Docker Desktop を起動しておいてください。起動していないと、`docker` コマンドもラッパーも `failed to connect to the docker API` で止まります（macOS では次のとおり）。

```
failed to connect to the docker API at unix:///Users/<user>/.docker/run/docker.sock; ... connect: no such file or directory
```

```bash
open -a Docker   # macOS。Windows はスタートメニューから Docker Desktop を起動する
docker info      # エラーが出なければ起動済み
```

### リポジトリを取得する

実行用のラッパー（`docker-run.sh` / `docker-run.ps1`）を使うために、リポジトリをホームフォルダに clone します。

```bash
# macOS / Linux / WSL2
cd ~
git clone https://github.com/shiwaku/aerial-photo-tile-pipeline.git
```

```powershell
# Windows PowerShell
cd $HOME
git clone https://github.com/shiwaku/aerial-photo-tile-pipeline.git
```

### イメージを用意する

公開イメージ（`ghcr.io/shiwaku/aerial-photo-tile-pipeline`、amd64 / arm64）があるので、ビルドしなくても使えます。手元に `aerial-tile-pipeline` が無ければ、ラッパーが自動でこちらを取得して使います。main の最新に追従する `latest` と、コミットごとの `sha-<短いハッシュ>` があります。先に取得しておく場合は次のとおりです。

```bash
docker pull ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest
```

結果を再現したい場合は、`IMAGE=ghcr.io/shiwaku/aerial-photo-tile-pipeline:sha-xxxxxxx` のようにタグを固定してください。

スクリプトを変更して試す場合だけ、手元でビルドします。手元のイメージがあれば、公開イメージよりそちらが優先されます。

```bash
cd ~/aerial-photo-tile-pipeline
docker build -t aerial-tile-pipeline .
```

スクリプトはイメージに入るので、リポジトリを更新したら作り直してください（作り直さないと古いスクリプトのまま動きます）。公開イメージに戻すときは `docker rmi aerial-tile-pipeline` で手元のイメージを消します。

## 2. 動作確認（selftest）

新しい環境では、まず `selftest` で動くことを確かめてください。オープンデータ（[VIRTUAL SHIZUOKA 静岡県 中・西部](https://www.geospatial.jp/ckan/dataset/virtual-shizuoka-mw)のオルソ画像、CC BY 4.0）を 4 図郭（約 30 MB）だけ取得し、Step 0〜5 を通して PMTiles まで作ります。最後に、PMTiles ができているか、タイルがあるか、不透明な黒が混ざっていないか、PMTiles を読めるかを判定します。

空のフォルダ `~/aerial-selftest` を作って、その中で実行します。

```bash
# macOS / Linux / WSL2
mkdir ~/aerial-selftest && cd ~/aerial-selftest
~/aerial-photo-tile-pipeline/docker-run.sh selftest
```

```powershell
# Windows PowerShell
mkdir $HOME\aerial-selftest; cd $HOME\aerial-selftest
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" selftest
```

最後に `=== 動作確認: すべて OK ===` と出れば成功です。Apple Silicon の Mac で 20 秒前後です。図郭数は `selftest --count 12` のように変えられます。

## 3. 自分のデータで実行する

ここでは、作業フォルダを `~/aerial-work`（PowerShell では `$HOME\aerial-work`）、データセット名を `mydata` として説明します。別の名前にする場合は、以下のコマンドと設定ファイルの `mydata` をそろえて変えてください。コマンドは macOS / Linux / WSL2 と Windows PowerShell の両方を並べています。作業フォルダは次の形になります。

```
~/aerial-work/
├── config/mydata.conf   # 設定ファイル
├── data/mydata/         # 入力画像を平置き
└── output/              # 出力先（ラッパーが作る）
```

作業フォルダを作り、設定ファイルのひな形をコピーします。

```bash
# macOS / Linux / WSL2
mkdir -p ~/aerial-work/config ~/aerial-work/data/mydata
cd ~/aerial-work
cp ~/aerial-photo-tile-pipeline/config/sample.conf.example config/mydata.conf
```

```powershell
# Windows PowerShell
New-Item -ItemType Directory -Force $HOME\aerial-work\config, $HOME\aerial-work\data\mydata | Out-Null
cd $HOME\aerial-work
Copy-Item $HOME\aerial-photo-tile-pipeline\config\sample.conf.example config\mydata.conf
```

設定ファイルの `DATASET_ID` と `SRC_DIR` の 2 行を、`mydata` 用に書き換えます。ほかの項目は `auto` のままで、実データから判定されます（[設定リファレンス](config.md)）。

```bash
# macOS / Linux / WSL2
sed -i.bak -e 's/^DATASET_ID=.*/DATASET_ID="mydata"/' -e 's#^SRC_DIR=.*#SRC_DIR="data/mydata"#' config/mydata.conf
rm config/mydata.conf.bak
grep -E '^(DATASET_ID|SRC_DIR)=' config/mydata.conf   # DATASET_ID="mydata" と SRC_DIR="data/mydata" が出れば OK
```

```powershell
# Windows PowerShell
(Get-Content -Encoding UTF8 config\mydata.conf) -replace '^DATASET_ID=.*', 'DATASET_ID="mydata"' -replace '^SRC_DIR=.*', 'SRC_DIR="data/mydata"' | Set-Content -Encoding UTF8 config\mydata.conf
Select-String '^(DATASET_ID|SRC_DIR)=' config\mydata.conf   # DATASET_ID="mydata" と SRC_DIR="data/mydata" が出れば OK
```

エディタで書き換えても構いません（macOS なら `open -e config/mydata.conf`、Windows なら `notepad config\mydata.conf`）。`SRC_DIR` の区切りは、Windows でも `/` で書きます（コンテナの中の Linux が読むため）。設定ファイルは CRLF でも BOM 付きの UTF-8 でも読めます。書き換えずに実行すると、「設定ファイルがひな形のままです」と出て止まります。

入力画像を `data/mydata/` に置きます（エクスプローラーや Finder でコピーしても構いません）。S3 にある場合は、AWS CLI で取得します。`s3://` 以降は、データを置いた場所（バケットとフォルダ）です。コマンドは macOS / Linux / WSL2 / PowerShell で共通です。

```bash
aws s3 sync s3://バケット名/フォルダ/ data/mydata/
```

実行します。Step 1〜5 を通して流します。

```bash
# macOS / Linux / WSL2
cd ~/aerial-work
~/aerial-photo-tile-pipeline/docker-run.sh config/mydata.conf
```

```powershell
# Windows PowerShell
cd $HOME\aerial-work
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" config\mydata.conf
```

やり直すときは、途中のステップから始めたり、1 ステップだけ流したりできます。

```bash
# macOS / Linux / WSL2
~/aerial-photo-tile-pipeline/docker-run.sh config/mydata.conf --from 4                 # Step 4 から
~/aerial-photo-tile-pipeline/docker-run.sh ./scripts/01_inspect.sh config/mydata.conf  # Step 1 だけ
```

```powershell
# Windows PowerShell
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" config\mydata.conf --from 4                 # Step 4 から
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" ./scripts/01_inspect.sh config/mydata.conf  # Step 1 だけ
```

成果物は、PMTiles（`~/aerial-work/output/mydata/mydata.pmtiles`）と、同じタイルの XYZ ディレクトリ（`~/aerial-work/output/mydata/tiles/{z}/{x}/{y}.webp`）の両方です。最後に `出力:` の行で場所が表示されます。XYZ ディレクトリが要らない場合は、設定ファイルの `PMTILES_KEEP_TILES` を `"false"` にすると、PMTiles を作ったあとに消します。判定の根拠は `output/mydata/inspect/report.md` に残るので、確認してください。

XYZ ディレクトリだけでよい場合は、設定ファイルの `TILE_OUTPUT="pmtiles"` を `TILE_OUTPUT="dir"` に書き換えます。

作業フォルダは環境変数 `PROJECT_DIR`、イメージ名は `IMAGE` で変えられます。ラッパーは、実行の最初に使うイメージを表示します（「公開イメージ … を使います」または「手元でビルドしたイメージ … を使います」）。

### ビューワで確認する

できたタイルは、イメージに入っているビューワ（MapLibre）で確認できます。手元に Node.js などを入れる必要はありません。作業フォルダで、ラッパーに `serve` と設定ファイルを渡します。

```bash
# macOS / Linux / WSL2
cd ~/aerial-work
~/aerial-photo-tile-pipeline/docker-run.sh serve config/mydata.conf
```

```powershell
# Windows PowerShell
cd $HOME\aerial-work
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" serve config\mydata.conf
```

`http://localhost:8080/ を開いてください` と出たら、ブラウザで http://localhost:8080/ を開きます。終わったら、ターミナルで Ctrl+C を押して止めます。

- ビューワのファイル（`index.html`・`assets/` など）は、`serve` を実行したときに `output/mydata/` へ置かれます。成果物と同じフォルダにあるので、フォルダごと静的ホスティングに置けば、そのまま公開できます。
- ポートを変えるときは、最後に番号を付けます（例: `serve config/mydata.conf 3000`）。8080 をほかのアプリが使っていて起動できないときにも使います。
- 開けるのは自分の PC からだけです（`127.0.0.1` で待ち受けます）。同じネットワークのほかの PC からは見えません。
- 背景地図（国土地理院）はインターネットから読み込みます。つながっていない場合でも、生成したタイルは表示されます。
- PMTiles はブラウザが部分的に読み込む仕組みなので、`index.html` をダブルクリックして開いても表示されません。`serve` を使ってください。

ビューワの機能（背景地図の切替、不透明度、整備範囲へのフィット）は、[ビューワ](viewer.md)を参照してください。

### ラッパーを使わない場合

`--user` を付けないと、Linux では `output/` 以下が root 所有で作られます。

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/data":/work/data -v "$PWD/output":/work/output -v "$PWD/config":/work/config:ro \
  aerial-tile-pipeline ./scripts/run_pipeline.sh config/mydata.conf
```

## 4. 公開イメージが更新されたら

main が更新されると、公開イメージ `latest` も作り直されます。ただし、手元に一度取得したイメージは**自動では更新されません**。更新はリポジトリのコミット履歴か、[パッケージのページ](https://github.com/users/shiwaku/packages/container/package/aerial-photo-tile-pipeline)の更新日時で分かります。

次の順で、手元を最新にしてから流し直します。

```bash
# macOS / Linux / WSL2
# 1. リポジトリを最新にする（ラッパーと手順書も変わることがあるため）
git -C ~/aerial-photo-tile-pipeline pull

# 2. 公開イメージを取り直す
docker pull ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest

# 3. 動作確認
cd ~/aerial-selftest
~/aerial-photo-tile-pipeline/docker-run.sh selftest
```

```powershell
# Windows PowerShell
git -C $HOME\aerial-photo-tile-pipeline pull
docker pull ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest
cd $HOME\aerial-selftest
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" selftest
```

実行の最初に「公開イメージ ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest を使います」と出ることを確認してください。「手元でビルドしたイメージ aerial-tile-pipeline を使います」と出る場合は、更新されていない手元のビルドが優先されています。`docker rmi aerial-tile-pipeline` で消してからやり直してください。

自分のデータは、前回の出力を消してから流し直します。Step 2（前処理）は、前処理済みのファイルがあると作り直さずにそのまま使います。前回の出力を残したままだと、更新した処理が反映されないことがあります。

```bash
# macOS / Linux / WSL2
cd ~/aerial-work
rm -r output/mydata
~/aerial-photo-tile-pipeline/docker-run.sh config/mydata.conf
```

```powershell
# Windows PowerShell
cd $HOME\aerial-work
Remove-Item -Recurse output\mydata
& "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" config\mydata.conf
```

作業フォルダの設定ファイル（`config/mydata.conf`）は、更新では書き換わりません。ひな形（`config/sample.conf.example`）に新しい項目や既定値の変更があっても、手元の設定ファイルには入りません。ひな形の変更を取り込むときは、次のように差分を見て、必要な行を手で反映してください。

```bash
# macOS / Linux / WSL2
git diff --no-index ~/aerial-photo-tile-pipeline/config/sample.conf.example config/mydata.conf
```

```powershell
# Windows PowerShell
git diff --no-index $HOME\aerial-photo-tile-pipeline\config\sample.conf.example config\mydata.conf
```

Windows PowerShell 5.1 の `Set-Content -Encoding UTF8` や、メモ帳の「UTF-8 (BOM 付き)」で保存した設定ファイルは、先頭に BOM が付きます。そのため、1 行目が同じ内容でも差分として表示されます（PowerShell 7 では BOM は付きません）。読み込みには影響しないので、無視して構いません。

Windows では、差分の前に `warning: ... LF will be replaced by CRLF the next time Git touches it` と出ることがあります。Windows の Git の改行コードの設定（`core.autocrlf`）による表示で、ファイルは変わらないので無視して構いません。

## OS ごとの注意

### macOS

- 実行中は `caffeinate` でスリープを抑止します。
- Docker Desktop に割り当てたメモリの範囲でしか動きません（Settings → Resources）。

### Linux

- systemd があれば `systemd-inhibit` でスリープを抑止します。

### Windows

- **WSL2 を推奨します。** WSL の Ubuntu などで clone し、作業フォルダも WSL 側（`~/` 以下）に置いてください。Windows 側（`C:\` や `/mnt/c`）に置くと、入力の読み込みが大幅に遅くなります（[性能実測](benchmarks.md#入力の置き場所drvfs--ext4)）。Docker Desktop の Settings → Resources → WSL integration で、使うディストリビューションを有効にしてください。
- **PowerShell の場合**、作業フォルダは Windows 側になるため、大きなデータでは WSL2 より遅くなります。`docker-run.ps1` は実行中だけスリープを抑止します。スクリプトの実行がブロックされる場合は、`powershell -ExecutionPolicy Bypass -File "$HOME\aerial-photo-tile-pipeline\docker-run.ps1" selftest` のように起動してください。
- **改行コード**: `.gitattributes` で、コンテナの中で読むファイル（`*.sh`・`*.py`・`Dockerfile` など）は Windows で clone しても LF のままになります。設定ファイル（`config/*.conf`）は CRLF で保存しても、BOM 付きの UTF-8 で保存しても読めます。
- WSL2 では、スリープは Windows 側の電源設定に従います。

## 大きなデータを流すときの注意

- **メモリ**: 足りないとタイル生成が `EXIT=137` で落ちます。`JOBS` を下げるとメモリ消費も下がります。
- **ディスク**: 入力に加えて中間ファイル（整形済み画像・XYZ ディレクトリ）の分が要ります。PMTiles の書き出しでは、コンテナ内の `/tmp` に成果物と同じ容量を一時的に使います。
- **Docker Desktop のライセンス**: 従業員 250 人超、または年間売上 1,000 万ドル超の組織で使う場合は、有償のサブスクリプションが必要です（[Docker Desktop license agreement](https://docs.docker.com/subscription/desktop-license/)）。Linux や WSL2 に直接入れた Docker Engine は対象外です。

## 新しい環境で確認すること

CI でカバーできない環境（Windows の実機など）で確かめるときのチェックリストです。業務データは使わず、`selftest` のオープンデータで確認できます。

- [ ] `docker build -t aerial-tile-pipeline .` が通る
- [ ] `docker-run.sh selftest`（PowerShell は `docker-run.ps1 selftest`）が `すべて OK` で終わる
- [ ] `output/selftest/selftest.pmtiles` が手元のユーザーで開ける・消せる（ファイルの持ち主の確認）
- [ ] 作業フォルダのパスに空白や日本語を含めても動く
- [ ] 設定ファイルを CRLF で保存しても動く
