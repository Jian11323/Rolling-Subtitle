#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CENC 烈度速报静态图绘制（Pillow）。
- 左侧：等震线/台站散点/震中
- 右侧：每个台站的烈度数据清单（尽量全量）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import tempfile
import json
import hashlib
import math

from PIL import Image, ImageDraw, ImageFont, ImageFilter

from utils.logger import get_logger
from utils.resource_path import get_cmt_weather_cache_root, get_resource_path

logger = get_logger()


_BG = (50, 50, 52, 255)
_MAP_BG = (50, 50, 52, 255)
_GRID = (70, 74, 86, 255)
_TEXT = (232, 236, 244, 255)
_TEXT_DIM = (170, 178, 194, 255)
_EPICENTER = (255, 70, 70, 255)
_STROKE = (10, 12, 16, 255)


def _extract_outline_rings(geojson_obj: Dict[str, Any]) -> List[List[Tuple[float, float]]]:
    """从行政区 GeoJSON 提取轮廓 ring（用于描边，不填充）。"""
    rings: List[List[Tuple[float, float]]] = []
    features = geojson_obj.get("features") or []
    if not isinstance(features, list):
        return rings

    for feat in features:
        if not isinstance(feat, dict):
            continue
        # 仅保留市级边界（level=city）
        props = feat.get("properties") or {}
        lvl = props.get("level")
        if lvl != "city":
            continue
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        if gtype == "Polygon":
            polys = [coords]
        elif gtype == "MultiPolygon":
            polys = coords
        else:
            continue
        for poly in polys:
            if not isinstance(poly, list):
                continue
            for ring in poly:
                pts: List[Tuple[float, float]] = []
                for p in ring:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        pts.append((_safe_float(p[0]), _safe_float(p[1])))
                if len(pts) >= 2:
                    rings.append(pts)
    return rings


def _bbox_intersects(
    ring: List[Tuple[float, float]],
    bbox: Tuple[float, float, float, float],
) -> bool:
    xmin, xmax, ymin, ymax = bbox
    rx = [p[0] for p in ring]
    ry = [p[1] for p in ring]
    if not rx or not ry:
        return False
    return not (max(rx) < xmin or min(rx) > xmax or max(ry) < ymin or min(ry) > ymax)


def _load_cn_map_rings() -> List[List[Tuple[float, float]]]:
    """读取 data/CN - Maps.geo.json 并返回可绘制 ring。"""
    map_path = get_resource_path("data/CN - Maps.geo.json")
    if not map_path.exists():
        logger.warning(f"[cenc-ir] 未找到地图文件: {map_path}")
        return []
    try:
        with open(map_path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            return []
        return _extract_outline_rings(obj)
    except Exception as e:
        logger.warning(f"[cenc-ir] 读取地图 GeoJSON 失败: {e}")
        return []


def _station_lon_lat(s: Dict[str, Any]) -> Tuple[float, float]:
    """兼容不同字段名提取台站经纬度。"""
    lon = _safe_float(
        s.get("stlo", s.get("stLon", s.get("stlng", s.get("lon", s.get("longitude", s.get("evlo", 0))))))
    )
    lat = _safe_float(
        s.get("stla", s.get("stLat", s.get("stlat", s.get("lat", s.get("latitude", s.get("evla", 0))))))
    )
    return lon, lat


def _station_name(s: Dict[str, Any]) -> str:
    return str(s.get("stName", s.get("stationName", s.get("stID", "--"))))


def _hex_to_rgba(hex_color: str, alpha: int = 220) -> Tuple[int, int, int, int]:
    hc = (hex_color or "").strip().lstrip("#")
    if len(hc) != 6:
        return (151, 199, 230, alpha)
    try:
        r = int(hc[0:2], 16)
        g = int(hc[2:4], 16)
        b = int(hc[4:6], 16)
        return (r, g, b, alpha)
    except ValueError:
        return (151, 199, 230, alpha)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                r"C:\Windows\Fonts\msyhbd.ttc",
                r"C:\Windows\Fonts\simhei.ttf",
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simsun.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
        ]
    )
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _intensity_color(i: float) -> Tuple[int, int, int, int]:
    # 对齐 PySide6：INT 1-12 离散色
    intensity_hex_by_level = {
        1: "#97C7E6",
        2: "#00A0E9",
        3: "#0068FF",
        4: "#4DBF73",
        5: "#1E9E5D",
        6: "#FFC132",
        7: "#FF9900",
        8: "#FF5E5E",
        9: "#FF4E00",
        10: "#FF0000",
        11: "#B01212",
        12: "#FF33CC",
    }
    try:
        lv = int(round(float(i)))
    except (TypeError, ValueError):
        lv = 1
    lv = max(1, min(12, lv))
    return _hex_to_rgba(intensity_hex_by_level.get(lv, "#97C7E6"), alpha=218)


def _collect_polygon_units(geometry: Dict[str, Any]) -> List[List[List[Tuple[float, float]]]]:
    """
    兼容 PySide6 版本思路：统一提取 Polygon/MultiPolygon/GeometryCollection 中的多边形 ring。
    返回结构：[[ring1, ring2...], [ring1, ...], ...]（每个元素是一个 polygon）
    """
    out: List[List[List[Tuple[float, float]]]] = []
    if not isinstance(geometry, dict):
        return out
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon" and isinstance(coords, list):
        rings: List[List[Tuple[float, float]]] = []
        for ring in coords:
            if not isinstance(ring, list):
                continue
            pts: List[Tuple[float, float]] = []
            for p in ring:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    pts.append((_safe_float(p[0]), _safe_float(p[1])))
            if len(pts) >= 3:
                rings.append(pts)
        if rings:
            out.append(rings)
        return out
    if gtype == "MultiPolygon" and isinstance(coords, list):
        for poly in coords:
            if not isinstance(poly, list):
                continue
            rings: List[List[Tuple[float, float]]] = []
            for ring in poly:
                if not isinstance(ring, list):
                    continue
                pts: List[Tuple[float, float]] = []
                for p in ring:
                    if isinstance(p, (list, tuple)) and len(p) >= 2:
                        pts.append((_safe_float(p[0]), _safe_float(p[1])))
                if len(pts) >= 3:
                    rings.append(pts)
            if rings:
                out.append(rings)
        return out
    if gtype == "GeometryCollection":
        geoms = geometry.get("geometries") or []
        if isinstance(geoms, list):
            for g in geoms:
                if isinstance(g, dict):
                    out.extend(_collect_polygon_units(g))
    return out


def _extract_polygons(contour_geojson: Dict[str, Any]) -> List[Tuple[float, List[List[Tuple[float, float]]]]]:
    items: List[Tuple[float, List[List[Tuple[float, float]]]]] = []
    # FeatureCollection / Feature / Geometry 统一入口
    features: List[Dict[str, Any]] = []
    ctype = contour_geojson.get("type")
    if ctype == "FeatureCollection" and isinstance(contour_geojson.get("features"), list):
        features = [f for f in contour_geojson.get("features", []) if isinstance(f, dict)]
    elif ctype == "Feature":
        features = [contour_geojson]
    elif isinstance(contour_geojson.get("geometry"), dict):
        features = [{"properties": contour_geojson.get("properties") or {}, "geometry": contour_geojson.get("geometry")}]
    elif isinstance(contour_geojson.get("coordinates"), list):
        # 直接是 Geometry 对象
        features = [{"properties": contour_geojson.get("properties") or {}, "geometry": contour_geojson}]

    for f in features:
        props = f.get("properties") or {}
        iv_raw = (
            props.get("INT")
            if "INT" in props
            else props.get("intensity", props.get("Intensity", props.get("level", props.get("value", 0))))
        )
        try:
            iv = float(iv_raw or 0)
        except (TypeError, ValueError):
            iv = 0.0
        geom = f.get("geometry") or {}
        for poly_rings in _collect_polygon_units(geom):
            items.append((iv, poly_rings))
    return items


def _bbox_from_data(
    stations: List[Dict[str, Any]],
    polygons: List[Tuple[float, List[List[Tuple[float, float]]]]],
    epi_lon: float,
    epi_lat: float,
) -> Tuple[float, float, float, float]:
    xs = [epi_lon]
    ys = [epi_lat]
    for s in stations:
        lon, lat = _station_lon_lat(s)
        xs.append(lon)
        ys.append(lat)
    for _, rings in polygons:
        for ring in rings:
            for x, y in ring:
                xs.append(x)
                ys.append(y)
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if abs(xmax - xmin) < 0.05:
        xmin -= 0.05
        xmax += 0.05
    if abs(ymax - ymin) < 0.05:
        ymin -= 0.05
        ymax += 0.05
    padx = (xmax - xmin) * 0.12
    pady = (ymax - ymin) * 0.12
    return xmin - padx, xmax + padx, ymin - pady, ymax + pady


def _project(x: float, y: float, bbox: Tuple[float, float, float, float], rect: Tuple[int, int, int, int]) -> Tuple[float, float]:
    xmin, xmax, ymin, ymax = bbox
    l, t, r, b = rect
    w = max(1.0, xmax - xmin)
    h = max(1.0, ymax - ymin)
    px = l + (x - xmin) / w * (r - l)
    py = b - (y - ymin) / h * (b - t)
    return px, py


def _bbox_around_epicenter_150km(epi_lon: float, epi_lat: float) -> Tuple[float, float, float, float]:
    """
    以震中为中心给出约 300km 对边视窗（半径约 150km）。
    使用经纬近似换算，满足快速静态图需求。
    """
    half_km = 150.0
    lat_deg_per_km = 1.0 / 111.32
    cos_lat = math.cos(math.radians(epi_lat))
    if abs(cos_lat) < 1e-4:
        cos_lat = 1e-4
    lon_deg_per_km = 1.0 / (111.32 * abs(cos_lat))
    dlat = half_km * lat_deg_per_km
    dlon = half_km * lon_deg_per_km
    return epi_lon - dlon, epi_lon + dlon, epi_lat - dlat, epi_lat + dlat


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _resolve_contour_geojson(parsed_data: Dict[str, Any], raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """兼容 contourGeoJson/contour_geojson，且支持字符串 JSON。"""
    candidates = [
        parsed_data.get("cenc_ir_contour_geojson"),
        parsed_data.get("contourGeoJson"),
        parsed_data.get("contour_geojson"),
        raw.get("contourGeoJson"),
        raw.get("contour_geojson"),
    ]
    for c in candidates:
        if isinstance(c, dict):
            return c
        if isinstance(c, str):
            s = c.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    return None


def _draw_station_intensity_fallback(
    img: Image.Image,
    stations: List[Dict[str, Any]],
    bbox: Tuple[float, float, float, float],
    map_rect: Tuple[int, int, int, int],
) -> None:
    """
    当上游未提供 contour_geojson 时，基于台站 estimateInt 生成近似烈度区域。
    说明：这是兜底可视化，不等同于官方等震线。
    """
    if not stations:
        return

    # 1) 预处理台站点（像素坐标 + 烈度），仅保留有效值
    pts: List[Tuple[float, float, float]] = []
    for s in stations:
        est = _safe_float(s.get("estimateInt", s.get("INT", 0)))
        if est <= 0.0:
            continue
        lon, lat = _station_lon_lat(s)
        px, py = _project(lon, lat, bbox, map_rect)
        pts.append((px, py, est))
    if not pts:
        return

    # 2) 在较低分辨率网格上做 IDW 插值，避免“泡泡圈”视觉
    ml, mt, mr, mb = map_rect
    map_w = max(1, mr - ml)
    map_h = max(1, mb - mt)
    grid_w = min(260, max(120, map_w // 3))
    grid_h = min(260, max(120, map_h // 3))

    # 预先转换到网格坐标，减少重复计算
    gpts: List[Tuple[float, float, float]] = []
    sx = grid_w / float(map_w)
    sy = grid_h / float(map_h)
    for px, py, est in pts:
        gpts.append(((px - ml) * sx, (py - mt) * sy, est))

    # IDW 参数：使用全局平滑场（不做硬半径截断），减少“泡泡圈”
    power = 2.1
    min_r2 = 2.2 * 2.2

    field: List[List[float]] = [[0.0 for _ in range(grid_w)] for _ in range(grid_h)]
    nearest_d2_grid: List[List[float]] = [[1e12 for _ in range(grid_w)] for _ in range(grid_h)]
    for gy in range(grid_h):
        for gx in range(grid_w):
            num = 0.0
            den = 0.0
            local_max = 0.0
            nearest_d2 = 1e12
            for sxp, syp, est in gpts:
                dx = gx - sxp
                dy = gy - syp
                d2 = dx * dx + dy * dy
                if d2 < nearest_d2:
                    nearest_d2 = d2
                d2 = max(d2, min_r2)
                w = 1.0 / (d2 ** (power * 0.5))
                num += est * w
                den += w
                if est > local_max:
                    local_max = est
            if den > 0.0:
                # 限幅到局部最大值附近，避免过度外推
                v = num / den
                # 远离台站时逐步衰减，避免全图被低烈度铺满
                falloff_start = (min(grid_w, grid_h) * 0.18) ** 2
                falloff_end = (min(grid_w, grid_h) * 0.34) ** 2
                if nearest_d2 > falloff_start:
                    t = (nearest_d2 - falloff_start) / max(1.0, (falloff_end - falloff_start))
                    t = max(0.0, min(1.0, t))
                    v = v * (1.0 - 0.95 * t)
                field[gy][gx] = min(v, local_max + 0.25)
                nearest_d2_grid[gy][gx] = nearest_d2

    # 对插值场做轻度数值平滑，避免使用 PIL 的 F 模式导致 "image has wrong mode"
    # 3x3 加权核（高斯近似）：1 2 1 / 2 4 2 / 1 2 1
    for _ in range(2):
        prev = [row[:] for row in field]
        for gy in range(grid_h):
            y0 = max(0, gy - 1)
            y1 = min(grid_h - 1, gy + 1)
            for gx in range(grid_w):
                x0 = max(0, gx - 1)
                x1 = min(grid_w - 1, gx + 1)
                v00 = prev[y0][x0]
                v01 = prev[y0][gx]
                v02 = prev[y0][x1]
                v10 = prev[gy][x0]
                v11 = prev[gy][gx]
                v12 = prev[gy][x1]
                v20 = prev[y1][x0]
                v21 = prev[y1][gx]
                v22 = prev[y1][x1]
                field[gy][gx] = (
                    v00 + 2.0 * v01 + v02
                    + 2.0 * v10 + 4.0 * v11 + 2.0 * v12
                    + v20 + 2.0 * v21 + v22
                ) / 16.0

    # 3) 分级填色（1-12），先低后高形成类等震面；每级单独蒙版后缩放到地图区域
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    # 从 2 级起绘制，避免 1 级导致整图铺蓝
    for lv in range(2, 13):
        mask_small = Image.new("L", (grid_w, grid_h), 0)
        mp = mask_small.load()
        count = 0
        for gy in range(grid_h):
            row = field[gy]
            for gx in range(grid_w):
                # 台站过远区域不绘制低级面，保留“范围感”
                near_d2 = nearest_d2_grid[gy][gx]
                far_limit = (min(grid_w, grid_h) * 0.30) ** 2
                if near_d2 > far_limit and lv <= 3:
                    continue
                if row[gx] >= float(lv):
                    mp[gx, gy] = 255
                    count += 1
        if count == 0:
            continue
        # 轻微羽化边缘，避免锯齿；不再做大范围模糊
        mask_small = mask_small.filter(ImageFilter.GaussianBlur(radius=1.15))
        mask_big = mask_small.resize((map_w, map_h), resample=Image.BILINEAR)
        color = _intensity_color(float(lv))
        fill = Image.new("RGBA", (map_w, map_h), (color[0], color[1], color[2], 170))
        level_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        level_layer.paste(fill, (ml, mt), mask_big)
        overlay.alpha_composite(level_layer)

    img.alpha_composite(overlay)


def render_cenc_station_map_to_file(parsed_data: Dict[str, Any]) -> Optional[str]:
    raw = parsed_data.get("raw_data") or {}
    if not isinstance(raw, dict):
        raw = {}
    stations = raw.get("instrument_intensity_json") or parsed_data.get("cenc_ir_instrument_intensity_json") or []
    if not isinstance(stations, list) or not stations:
        return None
    contour = _resolve_contour_geojson(parsed_data, raw)
    polygons: List[Tuple[float, List[List[Tuple[float, float]]]]] = []
    if isinstance(contour, dict):
        try:
            polygons = _extract_polygons(contour)
        except Exception:
            polygons = []
    logger.info(f"[cenc-ir] 烈度图要素统计: contour={'yes' if isinstance(contour, dict) else 'no'}, polygons={len(polygons)}, stations={len(stations)}")

    epi_lon = _safe_float(parsed_data.get("longitude", raw.get("epiLon", 0)))
    epi_lat = _safe_float(parsed_data.get("latitude", raw.get("epiLat", 0)))
    if abs(epi_lon) < 0.001 and abs(epi_lat) < 0.001 and stations:
        epi_lon = _safe_float(stations[0].get("evlo", stations[0].get("stlo", 0)))
        epi_lat = _safe_float(stations[0].get("evla", stations[0].get("stla", 0)))

    # 参考 PySide6 风格：纯地图展示，右侧不再放表格，突出等震线 + 台站 + 震中
    W, H = 1000, 1000
    map_rect = (12, 60, 988, 988)
    img = Image.new("RGBA", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(34, bold=True)
    f_row = _font(15)
    f_row_small = _font(14)

    org = str(parsed_data.get("organization") or "中国地震台网中心地震烈度速报")
    shock_time = str(parsed_data.get("shock_time") or "")
    place = str(parsed_data.get("place_name") or "")
    mag = _safe_float(parsed_data.get("magnitude", 0))
    title = f"{shock_time} {place} M{mag:.1f} 烈度速报".strip()
    if not title:
        title = f"{org} 烈度速报"
    # 顶部胶囊标题
    title_x, title_y = 14, 10
    tw, th = draw.textbbox((0, 0), title, font=f_title)[2:]
    draw.rounded_rectangle(
        (title_x - 8, title_y - 4, title_x + tw + 8, title_y + th + 4),
        radius=8,
        fill=(32, 34, 42, 235),
        outline=(230, 232, 236, 220),
        width=2,
    )
    draw.text((title_x, title_y), title, fill=(245, 247, 250, 255), font=f_title)

    draw.rounded_rectangle(map_rect, radius=10, fill=_MAP_BG, outline=_GRID, width=2)

    # 固定为震中 150km 半径范围
    bbox = _bbox_around_epicenter_150km(epi_lon, epi_lat)
    map_rings = _load_cn_map_rings()

    # 行政区边界（来自 data/CN - Maps.geo.json）
    for ring in map_rings:
        if not _bbox_intersects(ring, bbox):
            continue
        pts = [_project(x, y, bbox, map_rect) for x, y in ring]
        if len(pts) >= 2:
            draw.line(pts, fill=(150, 154, 164, 200), width=1, joint="curve")

    # 按需求：去掉烈度区域底色，仅保留台站标注

    # 台站点（叠加在地图上）：按烈度颜色显示圆点 + 烈度数字（参考 PySide6 风格）
    max_est = max((_safe_float(s.get("estimateInt", s.get("INT", 0))) for s in stations), default=0.0)
    f_station_num = _font(24, bold=True)
    for s in sorted(stations, key=lambda x: _safe_float(x.get("estimateInt", x.get("INT", 0))), reverse=True):
        lon, lat = _station_lon_lat(s)
        est = _safe_float(s.get("estimateInt", s.get("INT", 0)))
        px, py = _project(lon, lat, bbox, map_rect)
        level = max(1, min(12, int(round(est))))
        fill = _intensity_color(float(level))
        r = 16
        draw.ellipse((px - r, py - r, px + r, py + r), fill=(fill[0], fill[1], fill[2], 240), outline=(208, 214, 224, 230), width=2)
        num_text = str(level)
        tb = draw.textbbox((0, 0), num_text, font=f_station_num)
        tw = max(1, tb[2] - tb[0])
        th = max(1, tb[3] - tb[1])
        # 注意 textbbox 可能含非 0 左上偏移，这里一并扣除确保严格居中
        tx = px - tw / 2 - tb[0]
        ty = py - th / 2 - tb[1]
        # 高烈度底色较深时统一白字，低烈度时深色字增强对比
        txt_color = (245, 248, 252, 255) if level >= 4 else (20, 28, 36, 255)
        draw.text((tx, ty), num_text, fill=txt_color, font=f_station_num)

    # 震中
    ex, ey = _project(epi_lon, epi_lat, bbox, map_rect)
    draw.line((ex - 12, ey, ex + 12, ey), fill=(250, 250, 250, 255), width=4)
    draw.line((ex, ey - 12, ex, ey + 12), fill=(250, 250, 250, 255), width=4)
    draw.line((ex - 12, ey, ex + 12, ey), fill=_EPICENTER, width=2)
    draw.line((ex, ey - 12, ex, ey + 12), fill=_EPICENTER, width=2)
    draw.ellipse((ex - 3, ey - 3, ex + 3, ey + 3), fill=_EPICENTER)
    draw.text((ex + 10, ey - 20), "震中", fill=(255, 255, 255, 240), font=f_row_small)

    foot = f"台站数: {len(stations)} | 最大估计烈度: {max_est:.1f}"
    # 左上角显示，位于时间标题下方
    foot_y = max(map_rect[1] + 6, title_y + th + 18)
    fb = draw.textbbox((0, 0), foot, font=f_row)
    fw = max(1, fb[2] - fb[0])
    fh = max(1, fb[3] - fb[1])
    draw.rounded_rectangle(
        (14, foot_y - 3, 14 + fw + 8, foot_y + fh + 3),
        radius=5,
        fill=(36, 38, 46, 180),
        outline=(120, 126, 138, 180),
        width=1,
    )
    draw.text((18, foot_y), foot, fill=_TEXT_DIM, font=f_row)

    # 标题与统计信息置顶重绘，避免被地图线条/台站标记干扰
    draw.rounded_rectangle(
        (title_x - 8, title_y - 4, title_x + tw + 8, title_y + th + 4),
        radius=8,
        fill=(32, 34, 42, 235),
        outline=(230, 232, 236, 220),
        width=2,
    )
    draw.text((title_x, title_y), title, fill=(245, 247, 250, 255), font=f_title)
    draw.rounded_rectangle(
        (14, foot_y - 3, 14 + fw + 8, foot_y + fh + 3),
        radius=5,
        fill=(36, 38, 46, 180),
        outline=(120, 126, 138, 180),
        width=1,
    )
    draw.text((18, foot_y), foot, fill=_TEXT_DIM, font=f_row)

    cache_root = get_cmt_weather_cache_root()
    write_dir = Path(cache_root) if cache_root is not None else Path(tempfile.gettempdir())
    try:
        write_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        write_dir = Path(tempfile.gettempdir())

    event_id = str(parsed_data.get("event_id") or "")
    key_src = f"{event_id}|{shock_time}|{place}|{mag}|{len(stations)}"
    digest = hashlib.md5(key_src.encode("utf-8", errors="ignore")).hexdigest()[:10]
    out_path = write_dir / f"cenc_ir_map_{digest}.png"
    try:
        img.save(out_path, format="PNG")
        return str(out_path.resolve())
    except Exception as e:
        logger.warning(f"[cenc-ir] 保存烈度图失败: {e}")
        return None

