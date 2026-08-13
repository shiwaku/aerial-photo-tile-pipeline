#!/usr/bin/env python3
"""生成済みタイルと VRT の情報から TileJSON（tiles.json）を組み立てる。"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from osgeo import gdal
except ImportError:  # pragma: no cover
    sys.exit("GDAL の Python バインディング（osgeo）が必要です")

gdal.UseExceptions()


def bounds_from_raster(path: str) -> list[float]:
    """ラスターの WGS84 範囲を [west, south, east, north] で返す。"""
    info = gdal.Info(path, format="json")
    extent = info.get("wgs84Extent")
    if not extent or not extent.get("coordinates"):
        raise SystemExit(f"WGS84 範囲を取得できません（CRS 未設定の可能性）: {path}")
    ring = extent["coordinates"][0]
    lons = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    return [min(lons), min(lats), max(lons), max(lats)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", required=True, help="範囲算出に使うラスター（VRT）")
    p.add_argument("--tiles-meta", required=True, help="04_make_tiles.sh が出力した tiles_meta.json")
    p.add_argument("--name", required=True)
    p.add_argument("--tile-url", required=True, help="タイル URL テンプレート（{z}/{x}/{y}）")
    p.add_argument("--attribution", default="")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    with open(args.tiles_meta, encoding="utf-8") as f:
        meta = json.load(f)

    bounds = bounds_from_raster(args.source)
    center_lon = (bounds[0] + bounds[2]) / 2
    center_lat = (bounds[1] + bounds[3]) / 2

    tilejson = {
        "tilejson": "2.2.0",
        "name": args.name,
        "version": "1.0.0",
        "scheme": "xyz",
        "format": meta["format"],
        "tiles": [args.tile_url],
        "bounds": [round(v, 7) for v in bounds],
        "center": [round(center_lon, 7), round(center_lat, 7), meta["min_zoom"]],
        "minzoom": meta["min_zoom"],
        "maxzoom": meta["max_zoom"],
        "attribution": args.attribution,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(tilejson, f, ensure_ascii=False, indent=2)
    print(json.dumps(tilejson, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
