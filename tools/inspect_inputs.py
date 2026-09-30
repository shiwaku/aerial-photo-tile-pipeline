#!/usr/bin/env python3
"""航空写真（正射画像）の受領データを検査し、タイル生成に必要な諸元をまとめる。

- GSD（地上解像度）・CRS・バンド構成・NoData 設定をファイルごとに読み取る
- ファイル間で不一致があれば警告する（バンド数混在・NoData 未設定など、
  gdalbuildvrt / gdal raster tile でつまずく典型パターンの事前検出）
- GSD から推奨最大ズームレベルを算出する
- 案件ごとに違う値を実データから推定する
  - CRS が無い場合の平面直角座標系の系番号（座標値と図郭コードの両方から）
  - 図郭外の余白色（外周画素の実測。透過処理が必要かどうかの判断材料）
  - 図郭サイズから地図情報レベル

出力: inputs.json（機械可読）と report.md（人が読むレポート）
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

try:
    import numpy as np
    from osgeo import gdal, osr
except ImportError:  # pragma: no cover
    sys.exit("GDAL の Python バインディング（osgeo）と numpy が必要です")

gdal.UseExceptions()

# Web メルカトルの赤道上 ZL0 解像度（256px タイル、m/px）
EQUATOR_RES_Z0 = 2 * math.pi * 6378137.0 / 256.0  # = 156543.033928...

# JGD2011 平面直角座標系。第 n 系 = EPSG:(6668 + n)
JGD2011_ZONE_EPSG_BASE = 6668
JGD2011_ZONES = range(1, 20)

# 国土基本図の図郭サイズ（縦 m × 横 m）→ 地図情報レベル
MAP_LEVELS = [
    (300.0, 400.0, "500（1/500）"),
    (600.0, 800.0, "1000（1/1,000）"),
    (1500.0, 2000.0, "2500（1/2,500）"),
    (3000.0, 4000.0, "5000（1/5,000）"),
]


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


def plausible_plane_zones(info: dict[str, Any]) -> list[dict[str, Any]]:
    """座標値だけから見て「ありえる」平面直角座標系の一覧を返す。

    注意: これは系番号の**選定**には使えない。平面直角座標系は各系の原点が
    自系の適用範囲内にあるため、ある (x, y) は多くの系で自系の範囲内に落ちる。
    ここで求めるのは候補の絞り込みと、指定・推定した系の妥当性検証まで。
    """
    cc = info.get("cornerCoordinates") or {}
    center = cc.get("center")
    if not center:
        return []

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    out = []
    for zone in JGD2011_ZONES:
        epsg = JGD2011_ZONE_EPSG_BASE + zone
        srs = osr.SpatialReference()
        try:
            srs.ImportFromEPSG(epsg)
        except RuntimeError:
            continue
        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
        try:
            tr = osr.CoordinateTransformation(srs, wgs84)
            lon, lat, _ = tr.TransformPoint(float(center[0]), float(center[1]))
        except RuntimeError:
            continue

        area = srs.GetAreaOfUse()
        if area is None:
            continue
        if (
            area.west_lon_degree <= lon <= area.east_lon_degree
            and area.south_lat_degree <= lat <= area.north_lat_degree
        ):
            out.append(
                {
                    "zone": zone,
                    "epsg": f"EPSG:{epsg}",
                    "lon": lon,
                    "lat": lat,
                    "area_name": area.name,
                }
            )
    return out


def resolve_srs_candidate(
    info: dict[str, Any], name_zone: int | None
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str]:
    """CRS が無い画像について、採用する系と根拠を決める。

    図郭コード先頭 2 桁は国土基本図の図郭コードで系番号を表す規約なので、
    これを第一の根拠にする。座標値から見た候補一覧で妥当性を検証する。
    """
    plausible = plausible_plane_zones(info)
    by_zone = {c["zone"]: c for c in plausible}

    if name_zone is not None and name_zone in by_zone:
        return by_zone[name_zone], plausible, "図郭コード先頭2桁（座標値の適用範囲とも整合）"
    if name_zone is not None and plausible:
        return None, plausible, (
            f"図郭コード先頭2桁は第{name_zone}系を示すが、座標値がその系の適用範囲に収まらない"
        )
    if len(plausible) == 1:
        return plausible[0], plausible, "座標値から見て候補が1系のみ"
    if plausible:
        return None, plausible, f"座標値だけでは {len(plausible)} 系に絞れない"
    return None, plausible, "座標値がどの系の適用範囲にも収まらない"


def zone_from_filename(path: str) -> int | None:
    """図郭コードの先頭 2 桁を系番号として読む（例: 08ND7783 → 第8系）。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    if len(stem) >= 2 and stem[:2].isdigit():
        zone = int(stem[:2])
        if zone in JGD2011_ZONES:
            return zone
    return None


def map_level_from_extent(width_m: float, height_m: float) -> str | None:
    """図郭の地上サイズから地図情報レベルを推定する（縦横は入れ替わりを許容）。"""
    for ns, ew, label in MAP_LEVELS:
        for a, b in ((ns, ew), (ew, ns)):
            if abs(height_m - a) / a < 0.02 and abs(width_m - b) / b < 0.02:
                return label
    return None


def border_fill(ds: gdal.Dataset, target: int = 512, ring: int = 2) -> dict[str, Any]:
    """外周の画素を実測し、図郭外の余白として塗られている色を推定する。

    余白があれば外周にその色が現れる。外周に占める最多色の割合と、
    純白・純黒それぞれの割合、および画像全体で占める割合を返す。

    純白・純黒を別に測るのは、航空写真では実際の地物が全バンド 255（または 0）に
    飽和することがほとんど無く、余白の強い証拠になるため。

    読み出しは**間引きした全体読み 1 回だけ**にしている。オルソ画像の GeoTIFF は
    1 行 1 ブロック（Block=幅×1）で格納されていることが多く、幅数 px の左右列を
    読むだけでも全ストリップを走査してファイル全体を読むことになる。
    間引き読みは最近傍抽出なので画素値は変化せず、純白・純黒の判定に影響しない。
    """
    w, h = ds.RasterXSize, ds.RasterYSize
    bands = min(ds.RasterCount, 3)

    step = max(1, min(w, h) // target)
    a = np.asarray(
        ds.ReadAsArray(
            buf_xsize=max(1, w // step),
            buf_ysize=max(1, h // step),
            band_list=list(range(1, bands + 1)),
        )
    )
    if a.ndim == 2:  # 単バンド
        a = a[np.newaxis, :, :]

    key = np.zeros(a.shape[1:], dtype=np.int64)
    for b in range(bands):
        key = (key << 8) | a[b].astype(np.int64)

    def decode(k: int) -> list[int]:
        return [int((k >> (8 * (bands - 1 - b))) & 0xFF) for b in range(bands)]

    r = max(1, min(ring, key.shape[0] // 2, key.shape[1] // 2))
    edge_keys = np.concatenate(
        [
            key[:r].ravel(),
            key[-r:].ravel(),
            key[:, :r].ravel(),
            key[:, -r:].ravel(),
        ]
    )
    values, counts = np.unique(edge_keys, return_counts=True)
    top_i = int(np.argmax(counts))
    top_key, top_count = int(values[top_i]), int(counts[top_i])
    n = edge_keys.size

    white_key = int((1 << (8 * bands)) - 1)
    black_key = 0

    def edge_share(k: int) -> float:
        i = int(np.searchsorted(values, k))
        return float(counts[i]) / n if i < values.size and values[i] == k else 0.0

    whole = key.ravel()

    def whole_share(k: int) -> float:
        return float((whole == k).mean())

    return {
        "border_color": decode(top_key),
        "border_ratio": round(top_count / n, 4),
        "border_white_ratio": round(edge_share(white_key), 4),
        "border_black_ratio": round(edge_share(black_key), 4),
        "whole_ratio": round(whole_share(top_key), 6),
        "whole_white_ratio": round(whole_share(white_key), 6),
        "whole_black_ratio": round(whole_share(black_key), 6),
    }


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
    embedded = srs_code(wkt)

    # CRS が画像に無い場合は図郭コード（規約）を根拠に、座標値で妥当性を検証して決める
    name_zone = zone_from_filename(path)
    inferred: dict[str, Any] | None = None
    plausible: list[dict[str, Any]] = []
    basis = "画像に CRS が埋め込まれている"
    if not embedded:
        inferred, plausible, basis = resolve_srs_candidate(info, name_zone)

    code = embedded or assume_srs or (inferred["epsg"] if inferred else None)

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
    elif inferred:
        lat = inferred["lat"]
    elif assume_srs and gt:
        lat = _lat_from_assumed_srs(info, assume_srs)

    width = info.get("size", [None, None])[0]
    height = info.get("size", [None, None])[1]
    ground_w = width * gsd_x if (width and gsd_x) else None
    ground_h = height * gsd_y if (height and gsd_y) else None

    return {
        "file": os.path.basename(path),
        "driver": info.get("driverShortName"),
        "width": width,
        "height": height,
        "gsd_x": gsd_x,
        "gsd_y": gsd_y,
        "ground_size_m": [ground_w, ground_h],
        "map_level": (
            map_level_from_extent(ground_w, ground_h) if (ground_w and ground_h) else None
        ),
        "srs": code,
        "srs_embedded": embedded is not None,
        "srs_inferred": inferred["epsg"] if inferred else None,
        "srs_inferred_area": inferred["area_name"] if inferred else None,
        "srs_basis": basis,
        "srs_plausible": [c["epsg"] for c in plausible],
        "zone_from_filename": (
            f"EPSG:{JGD2011_ZONE_EPSG_BASE + name_zone}" if name_zone else None
        ),
        "border": border_fill(ds),
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


# 外周に純白／純黒がこの割合以上あれば余白とみなす（航空写真の地物は飽和しにくい）
EXTREME_BORDER_THRESHOLD = 0.02
# 純白・純黒以外の色の場合は、外周がほぼ単色で埋まっていることを要求する
FILL_BORDER_THRESHOLD = 0.5


def suggest_nodata(files: list[dict[str, Any]]) -> tuple[str, str]:
    """外周画素の実測から、透過処理に使う NoData 値を提案する。

    戻り値は (提案値, 理由)。透過処理が不要なら提案値は空文字。
    """
    n = len(files)
    white_hits = [f for f in files if f["border"]["border_white_ratio"] >= EXTREME_BORDER_THRESHOLD]
    black_hits = [f for f in files if f["border"]["border_black_ratio"] >= EXTREME_BORDER_THRESHOLD]

    def extreme_reason(hits: list[dict[str, Any]], label: str, key: str) -> str:
        ratios = [f["border"][key] for f in hits]
        return (
            f"{len(hits)}/{n} ファイルの外周に{label}が "
            f"{min(ratios) * 100:.0f}〜{max(ratios) * 100:.0f}% 含まれる"
            f"（しきい値 {EXTREME_BORDER_THRESHOLD * 100:.0f}%）。"
            "航空写真の地物は全バンド飽和しにくいため余白と判断"
        )

    if white_hits and black_hits:
        return "", (
            f"外周に純白を含むファイル {len(white_hits)}/{n} 件と、"
            f"純黒を含むファイル {len(black_hits)}/{n} 件が混在している。"
            "どちらが図郭外かを確認し NODATA を手動で指定してください"
        )
    if white_hits:
        return "255 255 255", extreme_reason(white_hits, "純白", "border_white_ratio")
    if black_hits:
        return "0 0 0", extreme_reason(black_hits, "純黒", "border_black_ratio")

    # 純白・純黒以外の色で塗られているケース
    filled = [f for f in files if f["border"]["border_ratio"] >= FILL_BORDER_THRESHOLD]
    if filled:
        counter = collections.Counter(tuple(f["border"]["border_color"]) for f in filled)
        color, count = counter.most_common(1)[0]
        value = " ".join(str(v) for v in color)
        return value, (
            f"{count}/{n} ファイルの外周が {value} でほぼ埋まっている"
            f"（しきい値 {FILL_BORDER_THRESHOLD * 100:.0f}%）。"
            "純白・純黒ではないため、地物の色でないことを確認してください"
        )

    top = max(files, key=lambda f: f["border"]["border_ratio"])
    return "", (
        f"外周に純白・純黒がほとんど無く（各 {EXTREME_BORDER_THRESHOLD * 100:.0f}% 未満）、"
        f"単色で埋まってもいない（最多色でも {top['border']['border_ratio'] * 100:.0f}%）ため、"
        "図郭外の余白は無いと判断（透過処理は不要）"
    )


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

    no_srs = [f for f in files if not f["srs_embedded"]]
    if no_srs and all(f["srs_inferred"] for f in no_srs):
        warnings.append(
            f"CRS が画像に埋め込まれていないファイルが {len(no_srs)} 件あります"
            f"（ワールドファイルのみ／.prj なし）。{no_srs[0]['srs_basis']}により "
            f"{no_srs[0]['srs_inferred']} と判定しました。異なる場合は SRC_SRS を明示してください"
        )

    undecided = [f for f in files if not f["srs_embedded"] and not f["srs_inferred"]]
    if undecided:
        f0 = undecided[0]
        warnings.append(
            f"系番号を自動で確定できないファイルが {len(undecided)} 件あります"
            f"（理由: {f0['srs_basis']}／座標値から見た候補: "
            f"{', '.join(f0['srs_plausible']) or 'なし'}）。SRC_SRS を明示してください"
        )

    no_world = [f["file"] for f in files if not f["world_file"] and not f["srs_embedded"]]
    if no_world:
        warnings.append(
            f"ワールドファイルも CRS も見つからないファイルが {len(no_world)} 件あります: "
            f"{no_world[:5]}"
        )

    nodata_suggestion, nodata_reason = suggest_nodata(files)
    unset_nodata = [f["file"] for f in files if not f["nodata_set"] and not f["has_alpha"]]
    if unset_nodata and nodata_suggestion:
        warnings.append(
            f"NoData 未設定かつアルファバンド無しのファイルが {len(unset_nodata)} 件あります。"
            f"外周画素の実測から NODATA=\"{nodata_suggestion}\" を推奨します（{nodata_reason}）"
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

    inferred = sorted({f["srs_inferred"] for f in files if f["srs_inferred"]})
    name_zones = sorted({f["zone_from_filename"] for f in files if f["zone_from_filename"]})
    map_levels = sorted({f["map_level"] for f in files if f["map_level"]})

    summary: dict[str, Any] = {
        "file_count": len(files),
        "gsd": gsd,
        "gsd_values": gsds,
        "band_counts": band_counts,
        "srs": srs_list[0] if len(srs_list) == 1 else None,
        "srs_inferred": inferred[0] if len(inferred) == 1 else None,
        "srs_inferred_values": inferred,
        "srs_basis": sorted({f["srs_basis"] for f in files})[0] if files else "",
        "srs_plausible": sorted({e for f in files for e in f["srs_plausible"]}),
        "srs_from_filename": name_zones[0] if len(name_zones) == 1 else None,
        "map_level": map_levels[0] if len(map_levels) == 1 else None,
        "map_levels": map_levels,
        "center_lat": lat,
        "recommended_max_zoom": max_zoom,
        "georef_sources": georef_sources,
        "srs_embedded_all": all(f["srs_embedded"] for f in files) if files else False,
        "has_alpha": all(f["has_alpha"] for f in files) if files else False,
        "nodata_all_set": all(f["nodata_set"] for f in files) if files else False,
        "nodata_suggestion": nodata_suggestion,
        "nodata_reason": nodata_reason,
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
    sizes = sorted({tuple(round(v) for v in f["ground_size_m"]) for f in files if all(f["ground_size_m"])})
    size_txt = "／".join(f"{w}×{h}m" for w, h in sizes) if sizes else "不明"
    level = summary["map_level"] or "／".join(summary["map_levels"])
    lines.append(
        f"| 図郭の地上サイズ | {size_txt}"
        f"{f'（地図情報レベル {level}）' if level else '（国土基本図の標準図郭サイズには一致せず）'} |"
    )
    lines.append(f"| CRS | {summary['srs'] or '不明（要指定）'} |")
    if not summary["srs_embedded_all"]:
        lines.append(
            f"| **自動判定した CRS** | "
            f"**{summary['srs_inferred'] or '確定できず（要 SRC_SRS 指定）'}** |"
        )
        lines.append(f"| 判定根拠 | {summary['srs_basis']} |")
        lines.append(
            f"| 座標値から見てありえる系 | {', '.join(summary['srs_plausible']) or 'なし'}"
            "（平面直角座標系は座標値だけでは一意に決まらない） |"
        )
    lines.append(
        f"| NoData の推奨値 | {summary['nodata_suggestion'] or '不要（余白なし）'} |"
    )
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

    lines += [
        "### 図郭外の余白（NoData）の判定",
        "",
        f"{summary['nodata_reason']}",
        "",
        "外周 4px の最多色が外周に占める割合（`border_ratio`）が高いファイルを"
        "「余白あり」とみなす。余白が無いデータに NoData を設定すると、"
        "影（純黒）や白飽和部分を誤って透過させてしまう。",
        "",
    ]

    if warnings:
        lines += ["## 警告", ""]
        lines += [f"- {w}" for w in warnings]
        lines.append("")
    else:
        lines += ["## 警告", "", "- なし", ""]

    lines += [
        "## ファイル別",
        "",
        "| ファイル | サイズ(px) | 地上サイズ(m) | GSD(m/px) | 取得元 | CRS | バンド | NoData | 外周の純白 | 外周の純黒 | 外周最多色 |",
        "|---------|-----------|--------------|-----------|-------|-----|-------|--------|-----------|-----------|-----------|",
    ]
    short = {"world_file": "TFW/JGW", "internal": "画像内部"}
    for f in files:
        nodata = ", ".join("—" if v is None else f"{v:g}" for v in f["nodata"])
        gw, gh = f["ground_size_m"]
        ground = f"{gw:.0f}×{gh:.0f}" if (gw and gh) else "—"
        b = f["border"]
        lines.append(
            f"| {f['file']} | {f['width']}×{f['height']} | {ground} | "
            f"{f['gsd_x']:.4f} | {short.get(f['georef_source'], f['georef_source'])} | "
            f"{f['srs'] or '—'} | {f['band_count']}{'(A)' if f['has_alpha'] else ''} | {nodata} | "
            f"{b['border_white_ratio'] * 100:.0f}% | {b['border_black_ratio'] * 100:.0f}% | "
            f"{b['border_ratio'] * 100:.0f}% {tuple(b['border_color'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("inputs", nargs="+", help="検査する画像ファイル")
    p.add_argument("--assume-srs", default=None, help="CRS が無い場合に仮定する CRS（例: EPSG:6673）")
    p.add_argument("--jobs", type=int, default=1, help="並列数（ファイル数が多い場合に指定）")
    p.add_argument("--out-json", required=True)
    p.add_argument("--out-report", required=True)
    args = p.parse_args()

    # 1ファイルあたり画素の実測を伴うため、数千ファイル規模では並列化する。
    # GDAL のデータセットはファイルごとに開くので共有していない。
    def run(path: str) -> dict[str, Any]:
        return inspect_one(path, args.assume_srs)

    try:
        if args.jobs > 1 and len(args.inputs) > 1:
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                files = list(ex.map(run, args.inputs))
        else:
            files = [run(path) for path in args.inputs]
    except RuntimeError as e:
        print(f"ERROR: 入力を読み込めません: {e}", file=sys.stderr)
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
