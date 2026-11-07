"""多尺度模板匹配的单元测试。

单尺度 ``cv2.matchTemplate`` 要求模板与目标像素尺寸严格一致，
DPI 变化或窗口缩放即失效。本测试锁定多尺度的补充能力。
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from bt_utils.image_processor import ImageProcessor

TARGET_BOX = (150, 100, 200, 150)   # 目标块位置（50x50）
TRUE_CENTER = (175, 125)


def _scene(seed: int = 7) -> Image.Image:
    """随机纹理背景 + 一个独特纹理目标块。

    用随机纹理而非纯色块，是因为纯色块缩放后边缘位置变化有限，
    无法体现单尺度的失效；纹理错位才能反映真实场景。
    """
    rng = np.random.default_rng(seed)
    src = Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))
    patch = Image.fromarray(rng.integers(0, 255, (50, 50, 3), dtype=np.uint8))
    src.paste(patch, (TARGET_BOX[0], TARGET_BOX[1]))
    return src


class TestBuildScales:
    def test_even_steps(self):
        assert ImageProcessor.build_scales((0.8, 1.2), 5) == [0.8, 0.9, 1.0, 1.1, 1.2]

    def test_single_step_returns_one(self):
        assert ImageProcessor.build_scales((0.8, 1.2), 1) == [1.0]

    def test_reversed_range_is_normalized(self):
        assert ImageProcessor.build_scales((1.2, 0.8), 5)[0] == 0.8

    def test_one_is_always_included(self):
        scales = ImageProcessor.build_scales((0.9, 1.2), 3)
        assert any(abs(s - 1.0) < 1e-6 for s in scales)

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError):
            ImageProcessor.build_scales((0, 1.0), 3)


class TestScaledMatch:
    def test_identity_scale_matches(self):
        src = _scene()
        tpl = src.crop(TARGET_BOX)
        found, pos, conf, scale = ImageProcessor.find_template_scaled(
            src, tpl, 0.8, scales=[1.0]
        )
        assert found and pos == TRUE_CENTER
        assert scale == 1.0

    def test_no_scales_falls_back_to_single(self):
        src = _scene()
        tpl = src.crop(TARGET_BOX)
        found, pos, conf, scale = ImageProcessor.find_template_scaled(
            src, tpl, 0.8, scales=None
        )
        assert found and pos == TRUE_CENTER
        assert scale == 1.0

    @pytest.mark.parametrize("factor", [1.15, 1.2])
    def test_multiscale_recovers_after_zoom(self, factor):
        src = _scene()
        tpl = src.crop(TARGET_BOX)
        big = src.resize(
            (int(src.width * factor), int(src.height * factor)), Image.LANCZOS
        )
        truth = (int(TRUE_CENTER[0] * factor), int(TRUE_CENTER[1] * factor))

        # 单尺度应失效
        single_found, _, single_conf, _ = ImageProcessor.find_template_scaled(
            big, tpl, 0.8, scales=None
        )
        assert single_found is False, (
            f"单尺度在 {factor}x 缩放后不应命中（conf={single_conf:.3f}）"
        )

        # 多尺度应恢复
        scales = ImageProcessor.build_scales((0.85, 1.25), 9)
        found, pos, conf, best = ImageProcessor.find_template_scaled(
            big, tpl, 0.8, scales=scales
        )
        assert found is True
        err = float(np.hypot(pos[0] - truth[0], pos[1] - truth[1]))
        assert err <= 5, f"多尺度误差 {err:.1f}px 过大"
        assert abs(best - factor) < 0.05, f"最佳缩放 {best} 与真值 {factor} 不符"

    def test_oversized_template_is_skipped(self):
        """缩放后超过源图尺寸时跳过，不应抛异常。"""
        src = Image.new("RGB", (40, 40), (10, 10, 10))
        tpl = Image.new("RGB", (35, 35), (200, 200, 200))
        found, pos, conf, scale = ImageProcessor.find_template_scaled(
            src, tpl, 0.8, scales=[2.0]
        )
        assert found is False
        assert pos is None
