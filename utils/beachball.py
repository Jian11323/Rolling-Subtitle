#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
震源机制沙滩球绘制（不依赖 ObsPy/matplotlib）
优先 PyGMT，不可用时使用 Pillow 自绘。由节面参数 [Strike, Dip, Rake] 生成沙滩球图，
按深度着色，保存为透明 PNG 供滚动字幕图标使用。
"""

import re
import math
import tempfile
import hashlib
from pathlib import Path
from typing import Optional, Tuple

from utils.logger import get_logger
from utils.resource_path import get_cmt_weather_cache_root

logger = get_logger()

BEACHBALL_SIZE_PX = 96


def _parse_nodal_plane(nodal_plane_str: str) -> Optional[tuple]:
    """解析节面字符串 "strike/dip/rake" 为 (strike, dip, rake) 浮元组。"""
    if not nodal_plane_str or not isinstance(nodal_plane_str, str):
        return None
    parts = nodal_plane_str.strip().split('/')
    if len(parts) != 3:
        return None
    try:
        strike, dip, rake = map(float, parts)
        return (strike, dip, rake)
    except (ValueError, TypeError):
        return None


def _depth_to_facecolor(depth_km: float) -> str:
    """根据震源深度(km)返回沙滩球填充颜色。"""
    if depth_km < 70:
        return 'red'
    if depth_km < 300:
        return 'green'
    return 'blue'


def _parse_depth_from_parsed_data(parsed_data: Optional[dict]) -> float:
    """从 parsed_data 或 raw_data 解析深度（km）。优先 centroidDepth。"""
    if not parsed_data:
        return 300.0
    raw = parsed_data.get('raw_data') or {}
    centroid = raw.get('centroidDepth') or parsed_data.get('centroidDepth')
    if centroid is not None:
        try:
            return float(centroid)
        except (ValueError, TypeError):
            pass
    depth_val = raw.get('depth', parsed_data.get('depth', 10.0))
    if isinstance(depth_val, (int, float)):
        return float(depth_val)
    if isinstance(depth_val, str):
        m = re.match(r'^([\d.]+)', depth_val.strip())
        if m:
            return float(m.group(1))
    return 10.0


def _facecolor_to_hex(color: str) -> str:
    """将颜色名转为 Pillow 可用的 hex。"""
    _map = {'red': '#ff0000', 'green': '#008000', 'blue': '#0000ff'}
    return _map.get(color.lower(), '#333333')


def _strike_dip_rake_to_p_t(
    strike_deg: float, dip_deg: float, rake_deg: float
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Aki & Richards：由节面 1 的 strike/dip/rake 计算 P 轴和 T 轴（NED 单位向量）。"""
    s = math.radians(strike_deg)
    d = math.radians(dip_deg)
    r = math.radians(rake_deg)
    nx = -math.sin(d) * math.sin(s)
    ny = math.sin(d) * math.cos(s)
    nz = -math.cos(d)
    sx = math.cos(r) * math.cos(s) + math.sin(r) * math.cos(d) * math.sin(s)
    sy = math.cos(r) * math.sin(s) - math.sin(r) * math.cos(d) * math.cos(s)
    sz = -math.sin(r) * math.sin(d)
    px, py, pz = nx + sx, ny + sy, nz + sz
    tx, ty, tz = nx - sx, ny - sy, nz - sz
    pl = math.sqrt(px * px + py * py + pz * pz) or 1e-10
    tl = math.sqrt(tx * tx + ty * ty + tz * tz) or 1e-10
    return ((px / pl, py / pl, pz / pl), (tx / tl, ty / tl, tz / tl))


def _render_pillow(
    strike: float, dip: float, rake: float,
    facecolor: str, out_path: Path, size: int, linewidth: int
) -> bool:
    """使用 Pillow 绘制沙滩球（下半球等面积投影）。"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return False

    P, T = _strike_dip_rake_to_p_t(strike, dip, rake)
    comp_color = _facecolor_to_hex(facecolor)
    ext_color = "#ffffff"
    pen_color = "#333333"
    internal = min(max(size, 64), 128)
    w = h = internal
    cx, cy = w / 2.0, h / 2.0
    margin = max(2, linewidth + 2)
    radius = min(cx, cy) - margin

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for iy in range(w):
        for ix in range(h):
            x = (ix - cx) / radius
            y = (cy - iy) / radius
            r2 = x * x + y * y
            if r2 > 1.0:
                continue
            z = 1.0 - r2
            if z < 0:
                continue
            fac = math.sqrt(2.0 - r2)
            X, Y, Z = x * fac, y * fac, z
            dot_p = X * P[0] + Y * P[1] + Z * P[2]
            dot_t = X * T[0] + Y * T[1] + Z * T[2]
            if dot_p * dot_p >= dot_t * dot_t:
                draw.point((ix, iy), fill=comp_color)
            else:
                draw.point((ix, iy), fill=ext_color)

    bbox = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(bbox, outline=pen_color, width=max(1, linewidth))

    if size != internal:
        resample = getattr(Image, "Resampling", Image)
        lanczos = getattr(resample, "LANCZOS", Image.LANCZOS)
        img = img.resize((size, size), lanczos)
    try:
        img.save(str(out_path), "PNG")
        return True
    except Exception as e:
        logger.warning(f"[沙滩球] Pillow 保存失败: {e}")
        return False


def _render_pygmt(
    strike: float, dip: float, rake: float,
    facecolor: str, depth_km: float, out_path: Path, size: int, linewidth: int
) -> bool:
    """使用 PyGMT 绘制沙滩球，透明 PNG。"""
    try:
        import pygmt
    except ImportError:
        return False
    except Exception:
        return False

    scale_cm = max(0.5, min(5.0, size / 80.0))
    try:
        fig = pygmt.Figure()
        fig.basemap(region=[-1.5, 1.5, -1.5, 1.5], projection=f"M{scale_cm}c", frame=False)
        fig.meca(
            spec={"strike": strike, "dip": dip, "rake": rake, "magnitude": 5.0},
            scale=f"{scale_cm}c",
            longitude=0,
            latitude=0,
            depth=depth_km,
            convention="aki",
            compression_fill=facecolor,
            extension_fill="white",
            pen=f"{linewidth}p",
        )
        fig.savefig(str(out_path), transparent=True)
        return True
    except Exception as e:
        logger.debug(f"[沙滩球] PyGMT 绘制失败: {e}")
        return False


def render_beachball_to_file(
    nodal_plane_1: str,
    parsed_data: Optional[dict] = None,
    event_id: Optional[str] = None,
    size: int = 200,
    linewidth: int = 2,
) -> Optional[str]:
    """
    根据节面 1 绘制沙滩球，保存为透明 PNG，返回路径。
    优先 PyGMT，不可用时使用 Pillow；均不可用时返回 None。
    """
    focal = _parse_nodal_plane(nodal_plane_1)
    if focal is None:
        logger.warning(f"[沙滩球] 无法解析节面: {nodal_plane_1}")
        return None
    strike, dip, rake = focal
    depth_km = _parse_depth_from_parsed_data(parsed_data)
    facecolor = _depth_to_facecolor(depth_km)

    cache_root = get_cmt_weather_cache_root()
    write_dir = Path(cache_root) if cache_root is not None else Path(tempfile.gettempdir())
    try:
        write_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        write_dir = Path(tempfile.gettempdir())

    if event_id:
        safe_id = re.sub(r'[^\w\-]', '_', str(event_id))[:32]
        name = f"cmt_beachball_{safe_id}.png"
    else:
        h = hashlib.md5(f"{strike}_{dip}_{rake}".encode()).hexdigest()[:12]
        name = f"cmt_beachball_{h}.png"
    out_path = write_dir / name

    try:
        if _render_pygmt(strike, dip, rake, facecolor, depth_km, out_path, size, linewidth):
            return str(out_path.resolve())
        if _render_pillow(strike, dip, rake, facecolor, out_path, size, linewidth):
            return str(out_path.resolve())
    except Exception as e:
        logger.error(f"[沙滩球] 绘制失败: {e}", exc_info=True)
    if out_path.exists():
        try:
            out_path.unlink()
        except OSError:
            pass
    logger.warning("[沙滩球] PyGMT 与 Pillow 均不可用或失败")
    return None


def beachball_backend_available() -> bool:
    """检测是否有可用的沙滩球绘制后端（PyGMT 或 Pillow）。"""
    try:
        import pygmt
        return True
    except ImportError:
        pass
    try:
        from PIL import Image, ImageDraw
        return True
    except ImportError:
        pass
    return False


def draw_beachball(
    nodal_plane_1: str,
    depth_km: Optional[float] = None,
    centroid_depth: Optional[str] = None,
    event_id: str = "",
    size_px: int = BEACHBALL_SIZE_PX,
    dpi: int = 96,
) -> Optional[str]:
    """
    绘制沙滩球并保存为 PNG，返回路径。兼容旧接口，内部调用 render_beachball_to_file。
    """
    parsed = None
    if depth_km is not None or centroid_depth is not None:
        raw = {}
        if centroid_depth is not None:
            raw["centroidDepth"] = centroid_depth
        if depth_km is not None:
            raw["depth"] = depth_km
        parsed = {"raw_data": raw}
    return render_beachball_to_file(
        nodal_plane_1,
        parsed_data=parsed,
        event_id=event_id or None,
        size=max(100, min(200, size_px)),
        linewidth=2,
    )
