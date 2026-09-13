"""素材处理：把白底 logo / 吉祥物转成透明背景 PNG（供深色界面使用）

做法：从四边向内做洪水填充（阈值内视为背景），只清除与边缘连通的白色区域，
因此吉祥物脸部/眼睛等内部的白色不会被误伤。同时裁掉多余留白。
用法：python scripts/prepare_assets.py
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

THRESHOLD = 236      # 高于此亮度视为“白”
TOLERANCE = 26       # 与种子色差的容差


def _is_bg(px, seed):
    return all(abs(px[i] - seed[i]) <= TOLERANCE and px[i] >= THRESHOLD
               for i in range(3))


def strip_white(src: Path, dst: Path, crop_pad=8):
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    px = img.load()
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]

    # 洪水填充（迭代式栈，避免递归深度限制）
    stack = list(seeds)
    visited = set()
    while stack:
        x, y = stack.pop()
        if (x, y) in visited or not (0 <= x < w and 0 <= y < h):
            continue
        visited.add((x, y))
        seed = (255, 255, 255)
        if not _is_bg(px[x, y], seed) and px[x, y][3] != 0:
            continue
        px[x, y] = (255, 255, 255, 0)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]

    bbox = img.getbbox()
    if bbox:
        img = img.crop((max(bbox[0] - crop_pad, 0), max(bbox[1] - crop_pad, 0),
                        min(bbox[2] + crop_pad, w), min(bbox[3] + crop_pad, h)))
    img.save(dst)
    print(f"  {src.name} → {dst.name}  尺寸 {img.size}")


def to_light_variant(src: Path, dst: Path, lum_max=92, light=(214, 233, 255)):
    """深色界面专用：把深色（藏青）部分提亮为浅蓝，保留青绿与橙色

    按亮度分界——藏青的亮度约 52、青绿约 117、橙星更高，阈值取 92 可干净分开。
    边缘抗锯齿像素做线性过渡，避免生硬描边。
    """
    img = Image.open(src).convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            if lum >= lum_max:
                continue
            t = min(1.0, (lum_max - lum) / 45)        # 越暗越接近目标色（陡峭过渡，保持锐利）
            px[x, y] = (round(r + (light[0] - r) * t),
                        round(g + (light[1] - g) * t),
                        round(b + (light[2] - b) * t), a)
    img.save(dst)
    print(f"  {src.name} → {dst.name}（深色界面变体）")


def downscale(src: Path, dst: Path, width: int):
    """预缩放到目标像素宽（2 倍于展示尺寸），避免浏览器大幅降采样产生毛刺"""
    img = Image.open(src)
    ratio = width / img.width
    img = img.resize((width, max(1, round(img.height * ratio))), Image.LANCZOS)
    img.save(dst)
    print(f"  {src.name} → {dst.name}  {img.size}")


def strip_white_global(src: Path, dst: Path, lo=198, hi=246, crop_pad=8):
    """全局剥离白底：把接近白色的像素变透明。

    与洪水填充的区别：连字符内部的封闭白色「字腔」也一并处理（用洪水填充时
    这些区域到不了、会在深色底上留成白块）。用 min(R,G,B) 判定白度，
    青绿(#2f8fa8 的 min≈47)与橙色不会被误伤。
    """
    img = Image.open(src).convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            whiteness = min(r, g, b)
            if whiteness >= hi:
                px[x, y] = (r, g, b, 0)
            elif whiteness > lo:
                px[x, y] = (r, g, b, round(a * (hi - whiteness) / (hi - lo)))
    bbox = img.getbbox()
    if bbox:
        img = img.crop((max(bbox[0] - crop_pad, 0), max(bbox[1] - crop_pad, 0),
                        min(bbox[2] + crop_pad, w), min(bbox[3] + crop_pad, h)))
    img.save(dst)
    print(f"  {src.name} → {dst.name}  尺寸 {img.size}（全局白底剥离）")


def main():
    # logo：全局剥离白底（含字腔）；吉祥物：保留白色脸部，用洪水填充
    strip_white_global(ASSETS / "logo_src.jpg", ASSETS / "logo.png")
    strip_white(ASSETS / "mascot_src.jpg", ASSETS / "mascot.png")
    to_light_variant(ASSETS / "logo.png", ASSETS / "logo_light.png")
    downscale(ASSETS / "logo_light.png", ASSETS / "logo_light@2x.png", 400)
    downscale(ASSETS / "mascot.png", ASSETS / "mascot@2x.png", 160)
    print("完成")


if __name__ == "__main__":
    sys.exit(main())
