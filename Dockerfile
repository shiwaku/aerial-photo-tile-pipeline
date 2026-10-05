# パイプラインの実行環境（GDAL + pmtiles）とスクリプト一式。使い方は README の「Docker で実行する」。
# スクリプトはイメージに含めるので、実行時にマウントするのは data/ output/ config/ だけでよい。
FROM ghcr.io/osgeo/gdal:ubuntu-small-3.13.2

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m pip install --no-cache-dir --break-system-packages pmtiles

WORKDIR /work
COPY scripts/ scripts/
COPY tools/ tools/
COPY config/*.conf.example config/
# マウントしなくても書き込めるよう、任意の UID（docker run --user）に開けておく
RUN mkdir -p data output && chmod 1777 data output

# 引数なしで起動したときは使い方を出す
CMD ["sh", "-c", "echo '使い方: docker run ... <image> ./scripts/run_pipeline.sh config/<name>.conf [--from N] [--to N]'"]
