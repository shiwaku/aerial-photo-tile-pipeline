# パイプラインの実行環境（GDAL + pmtiles）。使い方は README の「Docker で実行する」。
# リポジトリはビルドに含めず、実行時に /work へマウントする。
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.13.2

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --no-cache-dir --break-system-packages pmtiles

WORKDIR /work
