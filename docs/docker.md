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

## 1. イメージを用意する

macOS と Windows では、先に Docker Desktop を起動しておいてください。起動していないと、`docker` コマンドもラッパーも `failed to connect to the docker API` で止まります（macOS では次のとおり）。

```
failed to connect to the docker API at unix:///Users/<user>/.docker/run/docker.sock; ... connect: no such file or directory
```

```bash
open -a Docker   # macOS。Windows はスタートメニューから Docker Desktop を起動する
docker info      # エラーが出なければ起動済み
```

公開イメージ（`ghcr.io/shiwaku/aerial-photo-tile-pipeline`、amd64 / arm64）があるので、ビルドしなくても使えます。手元に `aerial-tile-pipeline` が無ければ、ラッパーが自動でこちらを取得して使います。main の最新に追従する `latest` と、コミットごとの `sha-<短いハッシュ>` があります。

```bash
docker pull ghcr.io/shiwaku/aerial-photo-tile-pipeline:latest
```

結果を再現したい場合は、`IMAGE=ghcr.io/shiwaku/aerial-photo-tile-pipeline:sha-xxxxxxx` のようにタグを固定してください。

スクリプトを変更して試す場合は、手元でビルドします。手元のイメージがあればそちらが優先されます。

```bash
git clone https://github.com/shiwaku/aerial-photo-tile-pipeline.git
cd aerial-photo-tile-pipeline
docker build -t aerial-tile-pipeline .
```

スクリプトはイメージに入るので、リポジトリを更新したら作り直してください（作り直さないと古いスクリプトのまま動きます）。

## 2. 動作確認（selftest）

新しい環境では、まず `selftest` で動くことを確かめてください。オープンデータ（[VIRTUAL SHIZUOKA 静岡県 中・西部](https://www.geospatial.jp/ckan/dataset/virtual-shizuoka-mw)のオルソ画像、CC BY 4.0）を 4 図郭（約 30 MB）だけ取得し、Step 0〜5 を通して PMTiles まで作ります。最後に、PMTiles ができているか、タイルがあるか、不透明な黒が混ざっていないか、PMTiles を読めるかを判定します。

空のフォルダで実行します。

```bash
# macOS / Linux / WSL2
mkdir ~/aerial-selftest && cd ~/aerial-selftest
/path/to/aerial-photo-tile-pipeline/docker-run.sh selftest
```

```powershell
# Windows PowerShell
mkdir $HOME\aerial-selftest; cd $HOME\aerial-selftest
C:\path\to\aerial-photo-tile-pipeline\docker-run.ps1 selftest
```

最後に `=== 動作確認: すべて OK ===` と出れば成功です。Apple Silicon の Mac で 20 秒前後です。図郭数は `selftest --count 12` のように変えられます。

## 3. 自分のデータで実行する

作業フォルダは次の形にします。リポジトリの中でも外でも構いません。

```
<作業フォルダ>/
├── config/<name>.conf   # SRC_DIR="data/<name>" のように作業フォルダからの相対で書く
├── data/<name>/         # 入力画像を平置き
└── output/              # 出力先（無ければ作る）
```

設定ファイルは `config/sample.conf.example` をコピーして作ります（[設定リファレンス](config.md)）。S3 などにあるデータは、先に手元へ取得しておきます（例: `aws s3 sync s3://<bucket>/<prefix>/ data/<name>/`）。

```bash
cd <作業フォルダ>
docker-run.sh config/<name>.conf                       # Step 1〜5
docker-run.sh config/<name>.conf --from 4              # 途中から
docker-run.sh ./scripts/01_inspect.sh config/<name>.conf   # 個別ステップ
```

PowerShell では `docker-run.ps1` を同じ引数で使います。パスの区切りは `\` でも構いません。

作業フォルダは環境変数 `PROJECT_DIR`、イメージ名は `IMAGE` で変えられます。ビューワのビルドとプレビュー（`serve.sh`）はホスト側で実行します。

### ラッパーを使わない場合

`--user` を付けないと、Linux では `output/` 以下が root 所有で作られます。

```bash
docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/data":/work/data -v "$PWD/output":/work/output -v "$PWD/config":/work/config:ro \
  aerial-tile-pipeline ./scripts/run_pipeline.sh config/<name>.conf
```

## OS ごとの注意

### macOS

- 実行中は `caffeinate` でスリープを抑止します。
- Docker Desktop に割り当てたメモリの範囲でしか動きません（Settings → Resources）。

### Linux

- systemd があれば `systemd-inhibit` でスリープを抑止します。

### Windows

- **WSL2 を推奨します。** WSL の Ubuntu などで clone し、作業フォルダも WSL 側（`~/` 以下）に置いてください。Windows 側（`C:\` や `/mnt/c`）に置くと、入力の読み込みが大幅に遅くなります（[性能実測](benchmarks.md#入力の置き場所drvfs--ext4)）。Docker Desktop の Settings → Resources → WSL integration で、使うディストリビューションを有効にしてください。
- **PowerShell の場合**、作業フォルダは Windows 側になるため、大きなデータでは WSL2 より遅くなります。`docker-run.ps1` は実行中だけスリープを抑止します。スクリプトの実行がブロックされる場合は、`powershell -ExecutionPolicy Bypass -File .\docker-run.ps1 selftest` のように起動してください。
- **改行コード**: `.gitattributes` で、コンテナの中で読むファイル（`*.sh`・`*.py`・`Dockerfile` など）は Windows で clone しても LF のままになります。設定ファイル（`config/*.conf`）は CRLF で保存しても読めます。
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
