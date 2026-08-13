#!/usr/bin/env python3
"""航空写真（正射画像）の受領データを検査し、タイル生成に必要な諸元をまとめる。

- GSD（地上解像度）・CRS・バンド構成・NoData 設定をファイルごとに読み取る
- ファイル間で不一致があれば警告する（バンド数混在・NoData 未設定など、
  gdalbuildvrt / gdal2tiles でつまずく典型パターンの事前検出）
- GSD から推奨最大ズームレベルを算出する

出力: inputs.json（機械可読）と report.md（人が読むレポート）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

try:
    from osgeo import gdal, osr
except ImportError:  # pragma: no cover
    sys.exit("GDAL の Python バインディング（osgeo）が必要です")

gdal.UseExceptions()

# Web メルカトルの赤道上 ZL0 解像度（256px タイル、m/px）
EQUATOR_RES_Z0 = 2 * math.pi * 6378137.0 / 256.0  # = 156543.033928...


def mercator_resolution(zoom: int, lat_deg: float) -> float:
    """指定緯度・ズームレベルでのタイル解像度（m/px）。"""
    return EQUATOR_RES_Z0 * math.cos(math.radians(lat_deg)) / (2**zoom)


def recommend_max_zoom(gsd: float, lat_deg: float) -> int:
    """GSD に最も近い解像度を持つ ZL を返す。

    タイル解像度が元画像の GSD に最も近い ZL を選ぶ（対数距離で最近傍）。
    これより低い ZL では元データの解像度を活かしきれず、高い ZL では
    補間で水増しするだけで情報は増えないため。
    """
    if gsd <= 0:
        raise ValueError(f"GSD が不正です: {gsd}")
    z = round(math.log2(EQUATOR_RES_Z0 * math.cos(math.radians(lat_deg)) / gsd))
    return max(0, min(24, int(z)))


def srs_code(wkt: str) -> str | None:
    if not wkt:
        return None
    srs = osr.SpatialReference()
    if srs.SetFromUserInput(wkt) != 0:
        return None
    auth = srs.GetAuthorityName(None)
    code = srs.GetAuthorityCode(None)
    if auth and code:
        return f"{auth}:{code}"
    return None


def world_file_for(path: str) -> str | None:
    """付随するワールドファイル（.tfw / .jgw など）を探す。"""
    base, ext = os.path.splitext(path)
    ext = ext.lower().lstrip(".")
    candidates = []
    if len(ext) >= 3:
        candidates.append(ext[0] + ext[-1] + "w")  # tif -> tfw, jpg -> jgw
    candidates += [ext + "w", "wld"]
    for c in candidates:
        for variant in (c, c.upper()):
            cand = f"{base}.{variant}"
            if os.path.exists(cand):
                return cand
    return None


def georef_source(path: str) -> str:
    """ジオリファレンス（GSD・原点）がどこから来ているかを判定する。

    画像内部のタグだけで開き直し、ジオトランスフォームが得られなければ
    ワールドファイル（.tfw / .jgw）由来と判断する。
    """
    try:
        ds = gdal.OpenEx(path, gdal.OF_RASTER, open_options=["GEOREF_SOURCES=INTERNAL"])
    except RuntimeError:
        return "world_file"
    gt = ds.GetGeoTransform(can_return_null=True)
    return "internal" if gt else "world_file"


def inspect_one(path: str, assume_srs: str | None) -> dict[str, Any]:
    ds = gdal.Open(path)
    info = gdal.Info(ds, format="json", computeMinMax=False, stats=False)

    gt = info.get("geoTransform")
    gsd_x = abs(gt[1]) if gt else None
    gsd_y = abs(gt[5]) if gt else None

    wkt = (info.get("coordinateSystem") or {}).get("wkt", "")
    code = srs_code(wkt)
    if code is None and assume_srs:
        code = assume_srs

    bands = info.get("bands", [])
    nodata = [b.get("noDataValue") for b in bands]
    color_interp = [b.get("colorInterpretation") for b in bands]

    # 代表緯度: CRS が判る場合はデータ中心の緯度を使う
    lat = None
    extent = info.get("wgs84Extent")
    if extent and extent.get("coordinates"):
        ring = extent["coordinates"][0]
        lats = [pt[1] for pt in ring]
        lat = (min(lats) + max(lats)) / 2
    elif assume_srs and gt:
        lat = _lat_from_assumed_srs(info, assume_srs)

    return {
        "file": os.path.basename(path),
        "driver": info.get("driverShortName"),
        "width": info.get("size", [None, None])[0],
        "height": info.get("size", [None, None])[1],
        "gsd_x": gsd_x,
        "gsd_y": gsd_y,
        "srs": code,
        "srs_embedded": srs_code(wkt) is not None,
        "band_count": len(bands),
        "color_interp": color_interp,
        "has_alpha": any(c == "Alpha" for c in color_interp),
        "nodata": nodata,
        "nodata_set": any(v is not None for v in nodata),
        "world_file": (
            os.path.basename(world_file_for(path)) if world_file_for(path) else None
        ),
        "georef_source": georef_source(path),
        "center_lat": lat,
    }


def _lat_from_assumed_srs(info: dict[str, Any], assume_srs: str) -> float | None:
    """CRS が埋め込まれていない場合、指定 CRS で中心座標を緯度経度に変換する。"""
    cc = info.get("cornerCoordinates") or {}
    center = cc.get("center")
    if not center:
        return None
    src = osr.SpatialReference()
    if src.SetFromUserInput(assume_srs) != 0:
        return None
    dst = osr.SpatialReference()
    dst.SetFromUserInput("EPSG:4326")
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    try:
        tr = osr.CoordinateTransformation(src, dst)
        lon, lat, _ = tr.TransformPoint(float(center[0]), float(center[1]))
    except RuntimeError:
        return None
    return lat


def summarize(files: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []

    gsds = sorted({round(f["gsd_x"], 6) for f in files if f["gsd_x"]})
    band_counts = sorted({f["band_count"] for f in files})
    srs_list = sorted({f["srs"] for f in files if f["srs"]})
    lats = [f["center_lat"] for f in files if f["center_lat"] is not None]

    if len(gsds) > 1:
        warnings.append(
            f"GSD がファイル間で異なります: {gsds} — 最も細かい値で最大ZLを算出します"
        )
    if len(band_counts) > 1:
        warnings.append(
            f"バンド数が混在しています: {band_counts} — gdalbuildvrt が失敗します。"
            "透過処理（02_prepare）でアルファバンドを揃えてください"
        )
    if len(srs_list) > 1:
        warnings.append(f"CRS がファイル間で異なります: {srs_list}")
    if not srs_list:
        warnings.append("CRS が判定できません — 設定の SRC_SRS で系番号を指定してください")

    no_srs = [f["file"] for f in files if not f["srs_embedded"]]
    if no_srs:
        warnings.append(
            f"CRS が画像に埋め込まれていないファイルが {len(no_srs)} 件あります"
            "（ワールドファイルのみ／.prj なし）。SRC_SRS の指定が必須です"
        )

    no_world = [f["file"] for f in files if not f["world_file"] and not f["srs_embedded"]]
    if no_world:
        warnings.append(
            f"ワールドファイルも CRS も見つからないファイルが {len(no_world)} 件あります: "
            f"{no_world[:5]}"
        )

    unset_nodata = [f["file"] for f in files if not f["nodata_set"] and not f["has_alpha"]]
    if unset_nodata:
        warnings.append(
            f"NoData 未設定かつアルファバンド無しのファイルが {len(unset_nodata)} 件あります。"
            "図郭外の色（白／黒）を確認し、設定の NODATA を指定してください"
        )

    gsd = min(gsds) if gsds else None
    lat = sum(lats) / len(lats) if lats else None
    max_zoom = recommend_max_zoom(gsd, lat) if (gsd and lat is not None) else None

    georef_sources = sorted({f["georef_source"] for f in files})
    if len(georef_sources) > 1:
        warnings.append(
            "ジオリファレンスの取得元がファイル間で混在しています"
            "（画像内部とワールドファイル）。GSD が一致しているか確認してください"
        )

    summary: dict[str, Any] = {
        "file_count": len(files),
        "gsd": gsd,
        "gsd_values": gsds,
        "band_counts": band_counts,
        "srs": srs_list[0] if len(srs_list) == 1 else None,
        "center_lat": lat,
        "recommended_max_zoom": max_zoom,
        "georef_sources": georef_sources,
        "has_alpha": all(f["has_alpha"] for f in files) if files else False,
        "nodata_all_set": all(f["nodata_set"] for f in files) if files else False,
        "total_pixels": sum(
            (f["width"] or 0) * (f["height"] or 0) for f in files
        ),
    }
    if max_zoom is not None:
        summary["zoom_resolution"] = mercator_resolution(max_zoom, lat)
    return summary, warnings


def render_report(summary: dict[str, Any], files: list[dict[str, Any]], warnings: list[str]) -> str:
    lines = ["# 入力データ検査レポート", ""]

    lines += ["## サマリ", "", "| 項目 | 値 |", "|------|-----|"]
    gsd = summary["gsd"]
    src_label = {
        "world_file": "ワールドファイル（.tfw / .jgw）",
        "internal": "画像内部のジオリファレンス",
    }
    georef = "／".join(src_label.get(s, s) for s in summary["georef_sources"])
    lines.append(f"| ファイル数 | {summary['file_count']} |")
    lines.append(f"| GSD（地上解像度） | {gsd if gsd is None else f'{gsd:.4f} m/px'} |")
    lines.append(f"| GSD・原点の取得元 | {georef} |")
    lines.append(f"| CRS | {summary['srs'] or '不明（要指定）'} |")
    lines.append(f"| バンド数 | {summary['band_counts']} |")
    lines.append(
        f"| アルファバンド | {'全ファイルにあり' if summary['has_alpha'] else 'なし／一部のみ'} |"
    )
    lines.append(
        f"| NoData 設定 | {'全ファイルに設定済み' if summary['nodata_all_set'] else '未設定あり'} |"
    )
    lat = summary["center_lat"]
    lines.append(f"| 代表緯度 | {'不明' if lat is None else f'{lat:.4f}°'} |")
    mz = summary["recommended_max_zoom"]
    if mz is not None:
        res = summary["zoom_resolution"]
        lines.append(f"| **推奨最大ズームレベル** | **ZL{mz}**（解像度 {res:.4f} m/px） |")
    else:
        lines.append("| 推奨最大ズームレベル | 算出不可（GSD または CRS 不明） |")
    lines.append("")

    if mz is not None and lat is not None:
        lines += [
            "### ズームレベル選定の根拠",
            "",
            "タイル解像度が元画像の GSD に最も近い ZL を採用する。",
            "",
            "| ZL | 解像度（m/px） | GSD 比 |",
            "|----|---------------|--------|",
        ]
        for z in range(max(0, mz - 2), mz + 3):
            res = mercator_resolution(z, lat)
            mark = " ←採用" if z == mz else ""
            lines.append(f"| {z}{mark} | {res:.4f} | {res / gsd:.2f}x |")
        lines.append("")

    if warnings:
        lines += ["## 警告", ""]
        lines += [f"- {w}" for w in warnings]
        lines.append("")
    else:
        lines += ["## 警告", "", "- なし", ""]

    lines += [
        "## ファイル別",
        "",
        "| ファイル | 形式 | サイズ(px) | GSD(m/px) | 取得元 | CRS | バンド | アルファ | NoData | ワールドファイル |",
        "|---------|------|-----------|-----------|-------|-----|-------|---------|--------|----------------|",
    ]
    short = {"world_file": "TFW/JGW", "internal": "画像内部"}
    for f in files:
        nodata = ", ".join("—" if v is None else f"{v:g}" for v in f["nodata"])
        lines.append(
            f"| {f['file']} | {f['driver']} | {f['width']}×{f['height']} | "
            f"{f['gsd_x']:.4f} | {short.get(f['georef_source'], f['georef_source'])} | "
            f"{f['srs'] or '—'} | {f['band_count']} | "
            f"{'○' if f['has_alpha'] else '—'} | {nodata} | {f['world_file'] or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs", nargs="+", help="検査する画像ファイル")
    p.add_argument("--assume-srs", default=None, help="CRS が無い場合に仮定する CRS（例: EPSG:6673）")
    p.add_argument("--out-json", required=True)
    p.add_argument("--out-report", required=True)
    args = p.parse_args()

    files = []
    for path in args.inputs:
        try:
            files.append(inspect_one(path, args.assume_srs))
        except RuntimeError as e:
            print(f"ERROR: {path} を読み込めません: {e}", file=sys.stderr)
            return 1

    if not files:
        print("ERROR: 入力ファイルがありません", file=sys.stderr)
        return 1

    summary, warnings = summarize(files)
    result = {"summary": summary, "warnings": warnings, "files": files}

    os.makedirs(os.path.dirname(args.out_json) or ".", exist_ok=True)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(args.out_report, "w", encoding="utf-8") as f:
        f.write(render_report(summary, files, warnings))

    print(render_report(summary, files, warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
