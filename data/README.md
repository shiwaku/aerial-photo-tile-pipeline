# data/ — 入力データの置き場

**このディレクトリの中身は `.gitignore` 済みで、リポジトリにはコミットされません。**
検証に使うのはオープンデータのみとし、業務で受領したデータ・顧客提供データは置かないこと。

## 配置ルール

データセットごとに 1 ディレクトリを作り、**画像とワールドファイルを平置き**する
（サブディレクトリは辿らないため、ZIP を展開したあと階層を平らにする）。

```
data/
└── <dataset-id>/          ← 設定ファイルの SRC_DIR に指定する
    ├── xxxx.tif
    ├── xxxx.tfw           ← 画像に CRS が埋め込まれていない場合に必要
    ├── yyyy.tif
    ├── yyyy.tfw
    └── ...
```

JPEG の場合は `.jpg` + `.jgw` の組。1 データセット内で拡張子は揃えること
（`SRC_EXT` で 1 つだけ指定するため）。

## 置いたあとの手順

```bash
cp config/sample.conf.example config/<dataset-id>.conf
# SRC_DIR / SRC_EXT / SRC_SRS / NODATA を編集

./scripts/01_inspect.sh config/<dataset-id>.conf   # まず検査だけ実行して諸元を確認
./scripts/run_pipeline.sh config/<dataset-id>.conf # 問題なければ通しで実行
```

`01_inspect.sh` が CRS・GSD・バンド構成・NoData を読み取って
`output/<dataset-id>/inspect/report.md` に出すので、
設定値（特に `SRC_SRS` と `NODATA`）はそのレポートを見てから確定させる。

## オープンデータの入手先（参考）

| 提供元 | 内容 | 備考 |
|--------|------|------|
| [国土地理院 基盤地図情報ダウンロード](https://fgd.gsi.go.jp/download/menu.php) | 数値標高モデル等 | 要利用者登録 |
| [G空間情報センター](https://front.geospatial.jp/) | 自治体のオルソ画像等 | データセットごとにライセンス確認 |
| [国土地理院 地理院タイル](https://maps.gsi.go.jp/development/ichiran.html) | 全国のシームレス空中写真 | 配信済みタイルのため本パイプラインの入力ではなく比較用 |

いずれもライセンス・出典表記の条件を確認し、`ATTRIBUTION` に反映する。
