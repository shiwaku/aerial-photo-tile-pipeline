#!/usr/bin/env python3
"""XYZ タイルディレクトリから PMTiles を直接書き出す。

従来は `mb-util` で MBTiles を作り `pmtiles convert` で PMTiles にしていた。
中間の SQLite は `pmtiles convert` の入力を作るためだけに存在し、その工程で

  - mb-util が無条件に VACUUM する（7.65GB を丸ごと書き直す。捨てるファイルなので無駄）
  - pmtiles convert が、一度 SQLite に入れたものを読み直す

という二重の無駄が出ていた。PyPI の `pmtiles` パッケージの Writer は
タイルを直接書けるので、SQLite を挟まなければどちらも消える。

Writer について、実装（pmtiles 3.7.0）を読んで確認した前提:

  - 重複排除は Writer が持っている（同一バイト列は 1 度だけ格納される）
  - 連続する同一タイルは run-length でまとめられる
  - **tileid（ヒルベルト順）の昇順で書かないと clustered が false になる**。
    finalize() はエントリを並べ替えるがタイル本体の並びは書いた順のままなので、
    範囲リクエストの局所性が落ちる。よってここでは必ず昇順に並べてから書く
  - タイル本体は一時ファイルに溜めてから出力へコピーされる。一時ファイルは
    TMPDIR に作られるため、drvfs ではなく ext4 に置くと速い

metadata は現行（mb-util + mbtiles_meta.py + pmtiles convert）の出力に合わせる。
bounds と center はヘッダに入るため metadata JSON には入れない。

実行結果はシェルで eval できる KEY=VALUE 形式で標準出力に出す。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

TILE_TYPES = {
    "webp": TileType.WEBP,
    "png": TileType.PNG,
    "jpg": TileType.JPEG,
    "jpeg": TileType.JPEG,
    "avif": TileType.AVIF,
}


def scan_tiles(root: str, ext: str):
    """`{z}/{x}/{y}.{ext}` を走査して (z, x, y, path) を返す。

    gdal2tiles は同じディレクトリに openlayers.html や tilemapresource.xml も
    書く。Step 5 が tiles.json を置くこともある。数字でない名前は読み飛ばす。

    os.walk ではなく os.scandir を使う。drvfs 上では stat の回数が効くため。
    """
    with os.scandir(root) as zs:
        for zent in zs:
            if not zent.name.isdigit() or not zent.is_dir():
                continue
            z = int(zent.name)
            with os.scandir(zent.path) as xs:
                for xent in xs:
                    if not xent.name.isdigit() or not xent.is_dir():
                        continue
                    x = int(xent.name)
                    with os.scandir(xent.path) as ys:
                        for yent in ys:
                            stem, _, suffix = yent.name.partition(".")
                            if suffix != ext or not stem.isdigit():
                                continue
                            if not yent.is_file():
                                continue
                            yield z, x, int(stem), yent.path


def bounds_from_tiles(coords, zoom: int) -> tuple[float, float, float, float]:
    """最大 ZL のタイル座標から WGS84 の範囲を求める。

    XYZ の y は北が 0。タイルは面積を持つので、東端・南端は 1 タイル進めた線になる。
    """
    x_min = min(x for x, _ in coords)
    x_max = max(x for x, _ in coords)
    y_min = min(y for _, y in coords)  # 最北
    y_max = max(y for _, y in coords)  # 最南
    n = 2**zoom

    def lon(x: float) -> float:
        return x / n * 360.0 - 180.0

    def lat(y: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))

    return lon(x_min), lat(y_max + 1), lon(x_max + 1), lat(y_min)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tiles-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--format", default="webp", help="webp / png / jpg")
    p.add_argument("--name", default="")
    p.add_argument("--description", default="")
    p.add_argument("--attribution", default="")
    p.add_argument("--center-zoom", type=int, default=None,
                   help="center の初期 ZL。既定は実在する最小 ZL")
    p.add_argument("--progress-every", type=int, default=20000)
    args = p.parse_args()

    fmt = args.format.lower()
    if fmt not in TILE_TYPES:
        sys.exit(f"未対応のタイル形式です: {args.format}")

    started = time.monotonic()

    # --- 走査 ---------------------------------------------------------------
    # tileid に直してから並べ替える。ヒルベルト順で書くことで clustered=true になる。
    entries = []
    zooms = set()
    max_zoom_coords = []
    max_zoom = -1
    for z, x, y, path in scan_tiles(args.tiles_dir, fmt):
        entries.append((zxy_to_tileid(z, x, y), path))
        zooms.add(z)
        if z > max_zoom:
            max_zoom, max_zoom_coords = z, []
        if z == max_zoom:
            max_zoom_coords.append((x, y))

    if not entries:
        sys.exit(f"タイルが 1 枚もありません: {args.tiles_dir}")

    min_zoom = min(zooms)
    scanned = time.monotonic()
    print(f"走査: {len(entries)} 枚 / ZL {min_zoom}-{max_zoom} "
          f"（{scanned - started:.1f} 秒）", file=sys.stderr, flush=True)

    entries.sort(key=lambda e: e[0])

    # --- 範囲と中心 ---------------------------------------------------------
    west, south, east, north = bounds_from_tiles(max_zoom_coords, max_zoom)
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    center_zoom = args.center_zoom if args.center_zoom is not None else min_zoom

    def e7(deg: float) -> int:
        return round(deg * 10_000_000)

    # --- 書き出し -----------------------------------------------------------
    tmp_out = args.output + ".part"
    total_bytes = 0
    with open(tmp_out, "wb") as f:
        writer = Writer(f)
        for i, (tileid, path) in enumerate(entries, 1):
            with open(path, "rb") as tf:
                data = tf.read()
            total_bytes += len(data)
            writer.write_tile(tileid, data)
            if args.progress_every and i % args.progress_every == 0:
                rate = i / (time.monotonic() - scanned)
                print(f"  書き込み {i}/{len(entries)} 枚（{rate:.0f} 枚/秒）",
                      file=sys.stderr, flush=True)

        header = {
            "tile_type": TILE_TYPES[fmt],
            # WebP / PNG / JPEG は既に圧縮済みなので二重に圧縮しない
            "tile_compression": Compression.NONE,
            "min_lon_e7": e7(west),
            "min_lat_e7": e7(south),
            "max_lon_e7": e7(east),
            "max_lat_e7": e7(north),
            "center_zoom": center_zoom,
            "center_lon_e7": e7(center_lon),
            "center_lat_e7": e7(center_lat),
        }
        # bounds / center はヘッダが持つため metadata JSON には入れない
        # （現行の pmtiles convert 経由の出力に合わせる）
        metadata = {"format": fmt,
                    "minzoom": str(min_zoom),
                    "maxzoom": str(max_zoom)}
        for key, value in (("name", args.name),
                           ("description", args.description),
                           ("attribution", args.attribution)):
            if value:
                metadata[key] = value

        writer.finalize(header, metadata)

    os.replace(tmp_out, args.output)
    out_bytes = os.path.getsize(args.output)
    elapsed = time.monotonic() - started

    print(f"pm_tile_count={len(entries)}")
    print(f"pm_unique_tiles={len(writer.hash_to_offset)}")
    print(f"pm_source_bytes={total_bytes}")
    print(f"pm_bytes={out_bytes}")
    print(f"pm_min_zoom={min_zoom}")
    print(f"pm_max_zoom={max_zoom}")
    print(f"pm_zoom_levels='{','.join(str(z) for z in sorted(zooms))}'")
    print(f"pm_center='{center_lon:.7f},{center_lat:.7f},{center_zoom}'")
    print(f"pm_bounds='{west:.7f},{south:.7f},{east:.7f},{north:.7f}'")
    print(f"pm_clustered={'true' if writer.clustered else 'false'}")
    print(f"pm_elapsed={elapsed:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
