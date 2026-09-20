"""品牌素材测试：logo / 吉祥物透明化处理的产物必须存在且真的透明

处理脚本 scripts/prepare_assets.py 负责生成；这里守住结果，
避免素材被误删或脚本改动后产出白底图（深色界面上会变成白块）。
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"


def _alpha_stats(path: Path):
    from PIL import Image
    img = Image.open(path)
    assert img.mode == "RGBA", f"{path.name} 缺少透明通道"
    alpha = img.getchannel("A")
    total = img.width * img.height
    transparent = alpha.tobytes().count(0)   # 每个像素 1 字节 alpha
    corners = [alpha.getpixel(p) for p in
               [(0, 0), (img.width - 1, 0),
                (0, img.height - 1), (img.width - 1, img.height - 1)]]
    return transparent / total, corners


@pytest.mark.parametrize("name", ["logo.png", "logo_light.png",
                                  "logo_light@2x.png", "mascot.png"])
def test_asset_exists_and_transparent(name):
    path = ASSETS / name
    assert path.exists(), f"缺少素材 {name}（运行 python scripts/prepare_assets.py 生成）"
    ratio, corners = _alpha_stats(path)
    assert corners == [0, 0, 0, 0], f"{name} 四角不是透明（白底没处理干净）"
    assert ratio > 0.25, f"{name} 透明像素占比仅 {ratio:.1%}，背景剥离可能失败"


def test_logo_light_is_brighter_than_original():
    """深色界面变体：藏青部分应被提亮，整体平均亮度高于原图"""
    from PIL import Image

    def mean_lum(path):
        img = Image.open(path).convert("RGBA")
        raw = img.tobytes()          # RGBA 连续 4 字节一组
        vals = [0.299 * raw[i] + 0.587 * raw[i + 1] + 0.114 * raw[i + 2]
                for i in range(0, len(raw), 4) if raw[i + 3] > 200]
        return sum(vals) / len(vals)

    assert mean_lum(ASSETS / "logo_light.png") > mean_lum(ASSETS / "logo.png")
