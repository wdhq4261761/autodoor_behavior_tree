"""模板匹配纯色假匹配缺陷的回归测试。

缺陷背景
--------
`ImageProcessor.find_template` 原先固定使用 ``cv2.TM_CCOEFF_NORMED``。
该方法的归一化相关系数为 ``cov(T,I)/(σ_T·σ_I)``，当源图局部区域方差
``σ_I = 0``（纯色块、纯白对话框、深色主题大面积留白）时出现 0/0，
OpenCV 将其置为 1.0，于是：

* 整张响应矩阵 ``min == max == 1.0``；
* ``minMaxLoc`` 返回首个位置 ``(0, 0)``；
* 函数返回 ``(0+半宽, 0+半高)`` 的错误坐标；
* 置信度为满分 1.0，无法用阈值过滤，且日志中看不出异常。

修复方式：定位改用 ``TM_SQDIFF_NORMED``（数值稳定），评分改用局部
Pearson 相关（语义与 CCOEFF 一致但不塌缩）；``ccoeff`` 兼容路径额外
增加"模板纯色"与"响应矩阵退化"两道降级。

测试构造约定：**模板必须从被测源图裁剪**，否则随机纹理不对应，
会造成间歇性失败。
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageEnhance

from bt_utils.image_processor import ImageProcessor

RED = (226, 59, 59)
BG = (20, 20, 20)
CANVAS = (400, 300)
BLOCK_A = (40, 40, 90, 90)      # 真值中心 (65, 65)
BLOCK_B = (300, 200, 350, 250)  # 同色干扰块，中心 (325, 225)
TRUE_CENTER = (65, 65)
PAD = 5                          # 裁剪模板时保留的背景边距
SEED = 20261105


def _canvas(textured: bool = False, second_block: bool = False) -> Image.Image:
    """生成基础画面（固定随机种子，保证可复现）。"""
    im = Image.new("RGB", CANVAS, BG)
    draw = ImageDraw.Draw(im)
    draw.rectangle(list(BLOCK_A), fill=RED)
    if second_block:
        draw.rectangle(list(BLOCK_B), fill=RED)

    if textured:
        rng = np.random.default_rng(SEED)
        arr = np.array(im).astype(np.int16)
        arr = np.clip(arr + rng.integers(-14, 14, arr.shape), 0, 255)
        im = Image.fromarray(arr.astype(np.uint8))
    return im


def _transform(im: Image.Image, bright: float = 1.0,
               scale: float = 1.0, noise: int = 0) -> Image.Image:
    """对画面施加变换，用于模拟真实环境变化。"""
    out = im
    if bright != 1.0:
        out = ImageEnhance.Brightness(out).enhance(bright)
    if scale != 1.0:
        out = out.resize(
            (int(out.width * scale), int(out.height * scale)), Image.LANCZOS
        )
    if noise:
        rng = np.random.default_rng(SEED + 1)
        arr = np.array(out).astype(np.int16)
        arr = np.clip(arr + rng.integers(-noise, noise, arr.shape), 0, 255)
        out = Image.fromarray(arr.astype(np.uint8))
    return out


def _crop_target(im: Image.Image) -> Image.Image:
    """按真实素材的方式裁剪模板：目标 + 一圈背景。

    只裁目标内部会得到一块纯色图，灰度标准差为 0，模板匹配无法定位
    （代码会正确判定为"无结构模板"并拒绝）。真实截图裁剪必然带背景，
    这里如实还原。
    """
    return im.crop((
        BLOCK_A[0] - PAD, BLOCK_A[1] - PAD,
        BLOCK_A[2] + 1 + PAD, BLOCK_A[3] + 1 + PAD,
    ))


def _dist(pos, expect=TRUE_CENTER) -> float:
    return float(np.hypot(pos[0] - expect[0], pos[1] - expect[1]))


def _scene(textured: bool = True, **kwargs):
    """返回 (源图, 从该源图裁出的模板)。"""
    src = _canvas(textured=textured, second_block=kwargs.pop("second_block", False))
    return src, _crop_target(src)


# ---------------------------------------------------------------------------
# 核心缺陷：纯色背景不得产生假匹配
# ---------------------------------------------------------------------------
class TestFlatBackgroundFalseMatch:
    def test_flat_background_returns_correct_position(self):
        src, tpl = _scene(textured=False)
        found, pos, _ = ImageProcessor.find_template(src, tpl, 0.8)
        assert found is True
        assert _dist(pos) == 0.0, f"期望 {TRUE_CENTER}，实际 {pos}（疑似纯色假匹配）"

    def test_flat_background_position_is_not_corner(self):
        """回归断言：曾被错误返回为 (25, 25)，即左上角 + 半模板。"""
        src, tpl = _scene(textured=False)
        _, pos, _ = ImageProcessor.find_template(src, tpl, 0.8)
        assert pos != (25, 25)

    def test_ccoeff_path_also_degrades_on_flat_background(self):
        """显式指定旧算法时，退化检测应把它救回来。"""
        src, tpl = _scene(textured=False)
        found, pos, _ = ImageProcessor.find_template(src, tpl, 0.8, method="ccoeff")
        assert found is True
        assert _dist(pos) == 0.0


# ---------------------------------------------------------------------------
# 误报抑制：完全无关的画面必须被拒绝
# ---------------------------------------------------------------------------
class TestFalsePositiveRejection:
    @pytest.mark.parametrize("color", [
        (7, 200, 250),      # 纯青：实测曾被 SQDIFF 误判为 0.906
        (226, 59, 59),      # 纯红：颜色一致但无结构
        (0, 0, 0),          # 纯黑
        (255, 255, 255),    # 纯白
    ])
    def test_flat_frames_are_rejected(self, color):
        """纯色画面不含目标结构，无论灰度是否接近都必须拒绝。"""
        _, tpl = _scene()
        blank = Image.new("RGB", CANVAS, color)
        found, pos, conf = ImageProcessor.find_template(blank, tpl, 0.8)
        assert found is False, f"纯色 {color} 画面被误报，conf={conf:.3f}"
        assert pos is None

    def test_random_noise_is_rejected(self):
        _, tpl = _scene()
        rng = np.random.default_rng(42)
        noise = Image.fromarray(
            rng.integers(0, 255, (CANVAS[1], CANVAS[0], 3), dtype=np.uint8)
        )
        found, _, conf = ImageProcessor.find_template(noise, tpl, 0.8)
        assert found is False, f"纯噪声被误报，conf={conf:.3f}"


# ---------------------------------------------------------------------------
# 常规鲁棒性：纹理 / 亮度 / 噪声
# ---------------------------------------------------------------------------
class TestRobustness:
    def test_textured_background(self):
        src, tpl = _scene()
        found, pos, _ = ImageProcessor.find_template(src, tpl, 0.8)
        assert found and _dist(pos) == 0.0

    def test_brightness_plus_25_percent(self):
        """Pearson 相关对线性亮度变化免疫。"""
        src, tpl = _scene()
        found, pos, conf = ImageProcessor.find_template(
            _transform(src, bright=1.25), tpl, 0.8
        )
        assert found and _dist(pos) == 0.0
        assert conf > 0.9

    def test_gaussian_noise(self):
        src, tpl = _scene()
        found, pos, _ = ImageProcessor.find_template(
            _transform(src, noise=18), tpl, 0.8
        )
        assert found and _dist(pos) == 0.0

    def test_scale_change_is_documented_weakness(self):
        """已知限制：单尺度匹配对整体缩放敏感。

        均匀色块缩放后误差有限，但带纹理的模板会显著失效，
        需要启用多尺度（见 test_template_multiscale.py）。
        """
        src, tpl = _scene()
        big = _transform(src, scale=1.1)
        found, pos, _ = ImageProcessor.find_template(big, tpl, 0.8)
        if found:
            expected = (int(TRUE_CENTER[0] * 1.1), int(TRUE_CENTER[1] * 1.1))
            assert _dist(pos, expected) <= 5


# ---------------------------------------------------------------------------
# 同色干扰：模板能区分，颜色检测会漂移
# ---------------------------------------------------------------------------
class TestSameColorInterference:
    def test_template_locates_correct_block(self):
        """两个同色块时，模板应精确定位到与模板一致的那一块。"""
        src, tpl = _scene(second_block=True)
        found, pos, _ = ImageProcessor.find_template(src, tpl, 0.8)
        assert found and _dist(pos) == 0.0, f"应命中 A 块 (65,65)，实际 {pos}"

    def test_color_detection_drifts(self):
        """对照实验：颜色检测取中位数，双块场景会漂移到非目标位置。

        这是 ColorConditionNode 的已知弱点，用模板匹配可以规避。
        """
        src = _canvas(textured=False, second_block=True)
        found, pos = ImageProcessor.find_color(src, RED, tolerance=50, min_pixels=8)
        assert found is True
        assert _dist(pos) > 100, (
            f"颜色检测在中位数逻辑下应产生明显偏移，实际 {pos} 距真值仅 "
            f"{_dist(pos):.1f}px"
        )


# ---------------------------------------------------------------------------
# 边界与接口语义
# ---------------------------------------------------------------------------
class TestInterfaceContract:
    def test_self_match_confidence_is_one(self):
        src, tpl = _scene()
        found, pos, conf = ImageProcessor.find_template(tpl, tpl, 0.8)
        assert found is True
        assert conf == pytest.approx(1.0, abs=1e-3)

    def test_source_smaller_than_template(self):
        _, tpl = _scene()
        small = Image.new("RGB", (10, 10), BG)
        found, pos, conf = ImageProcessor.find_template(small, tpl, 0.8)
        assert found is False
        assert pos is None
        assert conf == 0.0

    def test_threshold_rejects_non_match(self):
        _, tpl = _scene()
        blank = Image.new("RGB", CANVAS, (7, 200, 250))
        found, pos, conf = ImageProcessor.find_template(blank, tpl, 0.9)
        assert found is False
        assert pos is None
        assert 0.0 <= conf <= 1.0

    def test_pure_color_template_is_rejected(self):
        """纯色模板无灰度结构，模板匹配无法定位，必须明确拒绝而非返回假匹配。"""
        pure_tpl = Image.new("RGB", (30, 30), RED)
        src, _ = _scene(textured=False)
        src.paste(pure_tpl, (200, 100))
        found, pos, conf = ImageProcessor.find_template(
            src, pure_tpl, 0.8, method="ccoeff"
        )
        assert found is False
        assert pos is None
        assert conf == 0.0


# ---------------------------------------------------------------------------
# 粗定位精修（VLM → CV 级联）
# ---------------------------------------------------------------------------
class TestRefineBbox:
    """VLM grounding 精度只有 20~50px，必须用颜色连通域精修后才能裁剪。"""

    TRUTH = [120, 80, 200, 160]
    COARSE = [100, 100, 150, 150]   # 模拟 VLM 的粗框

    def _img(self):
        im = Image.new("RGB", (400, 300), (25, 30, 35))
        draw = ImageDraw.Draw(im)
        draw.rectangle([120, 80, 200, 160], fill=RED)
        draw.rectangle([300, 200, 340, 240], fill=(40, 120, 220))
        return im

    def test_refine_recovers_bbox(self):
        refined = ImageProcessor.refine_bbox(self._img(), self.COARSE, RED, expand=3.0)
        assert refined is not None
        for got, want in zip(refined, self.TRUTH):
            assert abs(got - want) <= 2, f"精修结果 {refined} 偏离真值 {self.TRUTH}"

    def test_small_expand_truncates_target(self):
        """外扩不足会让目标被边界截断，精修必然偏移 —— 参数约束而非缺陷。"""
        refined = ImageProcessor.refine_bbox(self._img(), self.COARSE, RED, expand=1.0)
        assert refined is not None
        width = refined[2] - refined[0]
        assert width < 80, f"外扩 1.0 时目标应被截断，实际宽度 {width}"

    def test_missing_color_returns_none(self):
        refined = ImageProcessor.refine_bbox(
            self._img(), self.COARSE, (10, 250, 10), expand=3.0
        )
        assert refined is None

    def test_invalid_bbox_returns_none(self):
        im = self._img()
        assert ImageProcessor.refine_bbox(im, None, RED) is None
        assert ImageProcessor.refine_bbox(im, [1, 2], RED) is None

    def test_bbox_near_edge_is_clamped(self):
        refined = ImageProcessor.refine_bbox(self._img(), [0, 0, 40, 40], RED, expand=3.0)
        # 左上角没有红色目标，应返回 None 而不是越界崩溃
        assert refined is None or (refined[0] >= 0 and refined[1] >= 0)
