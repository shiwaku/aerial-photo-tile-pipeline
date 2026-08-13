#!/usr/bin/env python3
"""図郭索引ベクトルタイルから、対象範囲に含まれる図郭のリストを作る。

オルソ画像がタイルダウンロード方式（図郭ポリゴンのベクトルタイルに
ダウンロード URL 属性が入っている形式）で公開されている場合に、
指定範囲の図郭コードとダウンロード URL を機械的に洗い出す。

出力:
  - CSV        … mesh_no,url（`scripts/00_fetch_data.sh` の入力）
  - GeoJSON    … 選定した図郭ポリゴン（範囲を目視確認するため／任意）
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from osgeo import gdal, ogr, osr
except ImportError:  # pragma: no cover
    sys.exit("GDAL の Python バインディング（osgeo）が必要です")

gdal.UseExceptions()
ogr.UseExceptions()


def deg2tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    n = 2**z
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def load_boundary(path_or_url: str) -> ogr.Geometry:
    """境界 GeoJSON（Feature / FeatureCollection / Geometry）を 1 つの図形にまとめる。"""
    if path_or_url.startswith(("http://", "https://")):
        with urllib.request.urlopen(path_or_url, timeout=120) as r:
            obj = json.load(r)
    else:
        with open(path_or_url, encoding="utf-8") as f:
            obj = json.load(f)

    geoms = []
    if obj.get("type") == "FeatureCollection":
        geoms = [f["geometry"] for f in obj["features"] if f.get("geometry")]
    elif obj.get("type") == "Feature":
        geoms = [obj["geometry"]]
    else:
        geoms = [obj]

    union = None
    for g in geoms:
        geom = ogr.CreateGeometryFromJson(json.dumps(g))
        union = geom if union is None else union.Union(geom)
    if union is None:
        raise SystemExit(f"境界データに図形がありません: {path_or_url}")
    return union


def fetch_tile(url: str, dest: str) -> str | None:
    """索引タイルを取得してキャッシュする。存在しない場合は None。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):  # 範囲外のタイル
            return None
        raise
    if not data:
        return None
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return dest


def read_tile(path: str, z: int, x: int, y: int, mesh_field: str, url_field: str) -> list[dict]:
    """索引タイル 1 枚から図郭コード・URL・ポリゴン（EPSG:4326）を取り出す。"""
    ds = gdal.OpenEx(
        f"MVT:{path}",
        gdal.OF_VECTOR,
        open_options=[f"X={x}", f"Y={y}", f"Z={z}", "CLIP=NO"],
    )
    src = osr.SpatialReference()
    src.ImportFromEPSG(3857)
    dst = osr.SpatialReference()
    dst.ImportFromEPSG(4326)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(src, dst)

    out = []
    for i in range(ds.GetLayerCount()):
        layer = ds.GetLayer(i)
        for feat in layer:
            mesh = feat.GetFieldAsString(mesh_field) if feat.GetFieldIndex(mesh_field) >= 0 else ""
            url = feat.GetFieldAsString(url_field) if feat.GetFieldIndex(url_field) >= 0 else ""
            geom = feat.GetGeometryRef()
            if not mesh or geom is None:
                continue
            geom = geom.Clone()
            geom.Transform(tr)
            out.append({"mesh_no": mesh, "url": url, "geom": geom})
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--index-url",
        required=True,
        help="索引ベクトルタイルの URL テンプレート（{z}/{x}/{y} を含む）",
    )
    p.add_argument("--boundary", help="対象範囲の境界 GeoJSON（ファイルまたは URL）")
    p.add_argument("--bbox", help="対象範囲（west,south,east,north）。--boundary の代わりに使う")
    p.add_argument("--zoom", type=int, default=12, help="索引タイルを取得する ZL（既定 12）")
    p.add_argument("--mesh-field", default="MESH_NO", help="図郭コードの属性名")
    p.add_argument("--url-field", default="URL", help="ダウンロード URL の属性名")
    p.add_argument("--cache-dir", default="output/_index_cache", help="索引タイルのキャッシュ先")
    p.add_argument("--jobs", type=int, default=8, help="索引タイル取得の並列数")
    p.add_argument("--out-csv", required=True)
    p.add_argument("--out-geojson", default=None)
    p.add_argument(
        "--near",
        default=None,
        help="この地点（lon,lat）に近い図郭だけを --count 件に絞る（サンプル抽出用）",
    )
    p.add_argument("--count", type=int, default=None, help="--near と併用する抽出件数")
    args = p.parse_args()

    if not args.boundary and not args.bbox:
        return _err("--boundary か --bbox のどちらかを指定してください")

    boundary = None
    if args.boundary:
        boundary = load_boundary(args.boundary)
        env = boundary.GetEnvelope()  # (minX, maxX, minY, maxY)
        bbox = (env[0], env[2], env[1], env[3])
        print(f"境界: {args.boundary}")
    else:
        bbox = tuple(float(v) for v in args.bbox.split(","))  # type: ignore[assignment]
        if len(bbox) != 4:
            return _err("--bbox は west,south,east,north の 4 値で指定してください")

    print(f"範囲: {bbox[0]:.5f},{bbox[1]:.5f} - {bbox[2]:.5f},{bbox[3]:.5f}")

    z = args.zoom
    x0, y1 = deg2tile(bbox[0], bbox[1], z)
    x1, y0 = deg2tile(bbox[2], bbox[3], z)
    tiles = [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]
    print(f"索引タイル: ZL{z} を {len(tiles)} 枚取得（並列 {args.jobs}）")

    def get(t: tuple[int, int, int]) -> tuple[tuple[int, int, int], str | None]:
        tz, tx, ty = t
        url = args.index_url.replace("{z}", str(tz)).replace("{x}", str(tx)).replace("{y}", str(ty))
        dest = os.path.join(args.cache_dir, str(tz), str(tx), f"{ty}.pbf")
        return t, fetch_tile(url, dest)

    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        fetched = list(ex.map(get, tiles))

    found = [(t, path) for t, path in fetched if path]
    print(f"  → {len(found)} 枚に図郭データあり")

    meshes: dict[str, dict] = {}
    for (tz, tx, ty), path in found:
        for rec in read_tile(path, tz, tx, ty, args.mesh_field, args.url_field):
            meshes.setdefault(rec["mesh_no"], rec)
    print(f"図郭（重複除去後）: {len(meshes)} 件")

    if boundary is not None:
        selected = {k: v for k, v in meshes.items() if v["geom"].Intersects(boundary)}
        print(f"境界と交差する図郭: {len(selected)} 件")
    else:
        selected = meshes

    if args.near:
        if not args.count:
            return _err("--near を使う場合は --count も指定してください")
        lon0, lat0 = (float(v) for v in args.near.split(","))
        origin = ogr.CreateGeometryFromJson(
            json.dumps({"type": "Point", "coordinates": [lon0, lat0]})
        )
        ranked = sorted(selected.items(), key=lambda kv: kv[1]["geom"].Distance(origin))
        selected = dict(ranked[: args.count])
        print(f"({lon0}, {lat0}) 近傍 {len(selected)} 件に絞り込み")

    if not selected:
        return _err("該当する図郭がありません（範囲・ZL・属性名を確認してください）")

    os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)
    with open(args.out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mesh_no", "url"])
        for mesh_no in sorted(selected):
            w.writerow([mesh_no, selected[mesh_no]["url"]])
    print(f"図郭リスト: {args.out_csv}（{len(selected)} 件）")

    if args.out_geojson:
        fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"mesh_no": m, "url": selected[m]["url"]},
                    "geometry": json.loads(selected[m]["geom"].ExportToJson()),
                }
                for m in sorted(selected)
            ],
        }
        os.makedirs(os.path.dirname(args.out_geojson) or ".", exist_ok=True)
        with open(args.out_geojson, "w", encoding="utf-8") as f:
            json.dump(fc, f, ensure_ascii=False)
        print(f"図郭ポリゴン: {args.out_geojson}")

    return 0


def _err(msg: str) -> int:
    print(f"ERROR: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
