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

実行結果はシェルで eval できる KEY=VALUE 形式で標準出力に出す。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

# PMTiles v3 が center / bounds に使う int32 E7 表現の上限
INT32_MAX = 2**31 - 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mbtiles", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--description", default="")
    p.add_argument("--attribution", default="")
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
    if not bounds:
        sys.exit("metadata に bounds がありません。PMTiles の範囲を決められません")
    west, south, east, north = (float(v) for v in bounds.split(","))
    center_lon = (west + east) / 2
    center_lat = (south + north) / 2
    center_zoom = args.center_zoom if args.center_zoom is not None else min_zoom

    would_overflow = abs(west + east) * 1e7 > INT32_MAX

    updates = {
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
        "center": f"{center_lon:.7f},{center_lat:.7f},{center_zoom}",
    }
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
