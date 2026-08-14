#!/usr/bin/env python3
"""生成タイルを抜き取り検査し、「不透明な黒」が混ざっていないか調べる。

整備範囲が不定形だと、外接矩形の内側に元データが無い穴ができる。VRT にアルファが
無いとその穴は (0,0,0) の不透明画素になり、地図上で黒く塗り潰される。
実際にこれを本番規模で作ってしまったことがあるため、生成後に必ず見る。

穴の画素は RGB=0 かつ アルファ=255 になる。航空写真の実データでこの状態が
広い面積を占めることは無いので、割合が高ければ穴が透過していない証拠になる。

タイルディレクトリと MBTiles のどちらでも検査できる。
出力はシェルで eval できる KEY=VALUE 形式。
"""

from __future__ import annotations

import argparse
import os
import random
import sqlite3
import sys

try:
    from osgeo import gdal
except ImportError:  # pragma: no cover
    sys.exit("GDAL の Python バインディング（osgeo）が必要です")

gdal.UseExceptions()

# これを超えたら穴が透過していないと判断する。実測では 3 バンド VRT で 30.5%、
# 4 バンド VRT で 0.0% だった。写真の実データが偶然これを超えることは考えにくい。
BLACK_WARN_RATIO = 2.0


def tile_stats(blob: bytes) -> tuple[int, int, int] | None:
    """1 タイルの (総画素数, 不透明な黒, 透過) を返す。読めなければ None。"""
    path = "/vsimem/check_tile"
    gdal.FileFromMemBuffer(path, blob)
    try:
        ds = gdal.Open(path)
        if ds is None:
            return None
        arr = ds.ReadAsArray()
        if arr is None:
            return None
        if arr.ndim == 2:  # グレースケール。アルファが無いので判定対象外
            return arr.size, 0, 0
        bands = arr.shape[0]
        rgb_max = arr[: min(3, bands)].max(axis=0)
        if bands >= 4:
            alpha = arr[3]
            opaque = alpha == 255
            transparent = int((alpha == 0).sum())
        else:
            # アルファが無いタイルは全画素が不透明
            opaque = rgb_max >= 0
            transparent = 0
        black_opaque = int(((rgb_max == 0) & opaque).sum())
        return int(rgb_max.size), black_opaque, transparent
    finally:
        gdal.Unlink(path)


def sample_from_dir(tiles_dir: str, ext: str, n: int, rng: random.Random) -> list[bytes]:
    paths: list[str] = []
    for root, _dirs, files in os.walk(tiles_dir):
        for f in files:
            if f.endswith(f".{ext}"):
                paths.append(os.path.join(root, f))
        # 全走査は本番規模だと重いので、十分な母数が集まったら打ち切る
        if len(paths) > n * 50:
            break
    if not paths:
        return []
    picked = rng.sample(paths, min(n, len(paths)))
    out = []
    for p in picked:
        with open(p, "rb") as fh:
            out.append(fh.read())
    return out


def sample_from_mbtiles(path: str, n: int) -> list[bytes]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT tile_data FROM tiles ORDER BY random() LIMIT ?", (n,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--tiles-dir")
    src.add_argument("--mbtiles")
    p.add_argument("--format", default="webp", help="タイルディレクトリの拡張子")
    p.add_argument("--sample", type=int, default=200)
    p.add_argument("--seed", type=int, default=0, help="抽出を再現可能にする")
    args = p.parse_args()

    rng = random.Random(args.seed)
    blobs = (
        sample_from_mbtiles(args.mbtiles, args.sample)
        if args.mbtiles
        else sample_from_dir(args.tiles_dir, args.format, args.sample, rng)
    )
    if not blobs:
        print("check_sampled=0")
        print("check_ok=unknown")
        return 0

    total = black = trans = 0
    read_ok = 0
    for blob in blobs:
        st = tile_stats(blob)
        if st is None:
            continue
        read_ok += 1
        total += st[0]
        black += st[1]
        trans += st[2]

    black_ratio = black / total * 100 if total else 0.0
    trans_ratio = trans / total * 100 if total else 0.0
    ok = black_ratio <= BLACK_WARN_RATIO

    print(f"check_sampled={read_ok}")
    print(f"check_black_ratio={black_ratio:.2f}")
    print(f"check_transparent_ratio={trans_ratio:.2f}")
    print(f"check_ok={'true' if ok else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
