#!/usr/bin/env python3
"""MBTiles の metadata を PMTiles 変換前に整える。

rio-mbtiles は metadata に minzoom / maxzoom / center を書かない。そのまま
`pmtiles convert` に渡すと go-pmtiles が bounds から center を計算するが、
その実装は経度を E7 の int32 で「先に加算してから 2 で割る」ため桁があふれる。

    (min_lon + max_lon) * 1e7 > 2^31 - 1  … 経度の和が 214.7483647 度を超える

日本（東経 138 度前後なら和は約 277 度）はすべて該当し、center の経度が
-76 度あたりに化ける。PMTiles v3 は center を int32 の E7 で持つ仕様なので
値そのものは表現できる。あふれるのは go-pmtiles 側の途中計算だけ。

metadata に center が入っていれば go-pmtiles はそれを使い計算しないため、
ここで明示的に書き込んで回避する。

mb-util（タイルディレクトリ → MBTiles）は metadata を一切書かないため、
bounds も format も無い。その場合は tiles テーブルのタイル座標から bounds を
逆算し、format は --format で受け取る。これが無いと PMTiles の tile type が
空になり、bounds が世界全体、center が (0, 0) になる。

実行結果はシェルで eval できる KEY=VALUE 形式で標準出力に出す。
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys

# PMTiles v3 が center / bounds に使う int32 E7 表現の上限
INT32_MAX = 2**31 - 1


def bounds_from_tiles(cur, zoom: int) -> tuple[float, float, float, float]:
    """最大ZLのタイル座標から WGS84 の範囲を逆算する。

    MBTiles の tile_row は TMS（南が原点）なので XYZ の y に直してから解く。
    """
    x_min, x_max, row_min, row_max = cur.execute(
        "SELECT min(tile_column), max(tile_column), min(tile_row), max(tile_row) "
        "FROM tiles WHERE zoom_level = ?", (zoom,)).fetchone()
    n = 2 ** zoom

    def lon(x: float) -> float:
        return x / n * 360.0 - 180.0

    def lat(y: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))

    # TMS row → XYZ y（上下反転）。row_max が最北、row_min が最南になる
    y_north, y_south = n - 1 - row_max, n - 1 - row_min
    # タイルは範囲を持つので、東端・南端は 1 タイル分進めた位置が境界
    return lon(x_min), lat(y_south + 1), lon(x_max + 1), lat(y_north)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mbtiles", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--description", default="")
    p.add_argument("--attribution", default="")
    p.add_argument("--format", default="",
                   help="タイル画像形式（webp / png 等）。metadata に無い場合に補う")
    p.add_argument("--center-zoom", type=int, default=None,
                   help="center の初期ZL。既定は実在する最小ZL")
    args = p.parse_args()

    conn = sqlite3.connect(args.mbtiles)
    cur = conn.cursor()

    # --- 実在するタイルから ZL 範囲と規模を数える -----------------------------
    zooms = [z for (z,) in cur.execute(
        "SELECT DISTINCT zoom_level FROM tiles ORDER BY zoom_level")]
    if not zooms:
        sys.exit(f"タイルが 1 枚もありません: {args.mbtiles}")
    min_zoom, max_zoom = zooms[0], zooms[-1]

    tile_count, total_bytes = cur.execute(
        "SELECT count(*), coalesce(sum(length(tile_data)), 0) FROM tiles").fetchone()

    meta = dict(cur.execute("SELECT name, value FROM metadata"))

    # --- center を明示する（go-pmtiles の桁あふれ回避） -----------------------
    bounds = meta.get("bounds")
    bounds_derived = False
    if bounds:
        west, south, east, north = (float(v) for v in bounds.split(","))
    else:
        # mb-util 経由だと metadata が空なのでタイル座標から逆算する
        west, south, east, north = bounds_from_tiles(cur, max_zoom)
        bounds_derived = True
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    center_zoom = args.center_zoom if args.center_zoom is not None else min_zoom

    would_overflow = abs(west + east) * 1e7 > INT32_MAX

    updates = {
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
        "center": f"{center_lon:.7f},{center_lat:.7f},{center_zoom}",
    }
    if bounds_derived:
        updates["bounds"] = f"{west:.7f},{south:.7f},{east:.7f},{north:.7f}"
    # format が無いと PMTiles の tile type が空になる
    if not meta.get("format") and args.format:
        updates["format"] = args.format
    for key, value in (("name", args.name),
                       ("description", args.description),
                       ("attribution", args.attribution)):
        if value:
            updates[key] = value

    cur.executemany(
        "INSERT OR REPLACE INTO metadata(name, value) VALUES(?, ?)",
        list(updates.items()))
    conn.commit()
    conn.close()

    # --- 呼び出し元（bash）へ返す --------------------------------------------
    print(f"mb_min_zoom={min_zoom}")
    print(f"mb_max_zoom={max_zoom}")
    print(f"mb_zoom_levels='{','.join(str(z) for z in zooms)}'")
    print(f"mb_tile_count={tile_count}")
    print(f"mb_total_bytes={total_bytes}")
    print(f"mb_center='{updates['center']}'")
    print(f"mb_center_overflow_avoided={'true' if would_overflow else 'false'}")
    print(f"mb_bounds_derived={'true' if bounds_derived else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
