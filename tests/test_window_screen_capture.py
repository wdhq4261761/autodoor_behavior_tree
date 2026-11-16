"""window_screen_capture 单元测试

用注入的 grabber / sampler 替代真实屏幕与窗口，保证在无桌面的 CI 上可跑。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bt_utils.window_screen_capture import (
    capture_window_content,
    is_window_occluded,
)


class FakeGrabber:
    """记录调用参数的假截图器"""

    def __init__(self, size=(400, 600), color="white"):
        self.size = size
        self.color = color
        self.calls = []

    def __call__(self, bbox=None, all_screens=False):
        self.calls.append({"bbox": bbox, "all_screens": all_screens})
        return Image.new("RGB", self.size, self.color)


class TestCaptureWindowContent:
    @patch("bt_utils.window_screen_capture.get_content_rect",
           return_value=(100, 200, 500, 800))
    def test_grab_bbox_is_content_rect(self, _):
        """抓图范围必须是内容区（已扣除顶部偏移）的屏幕矩形"""
        grabber = FakeGrabber()
        img = capture_window_content(1, None, 38, grabber=grabber)

        assert grabber.calls == [{"bbox": (100, 200, 500, 800), "all_screens": True}]
        assert img.size == (400, 600)

    @patch("bt_utils.window_screen_capture.get_content_rect",
           return_value=(100, 200, 500, 800))
    def test_region_is_cropped(self, _):
        img = capture_window_content(1, (10, 20, 60, 80), 38, grabber=FakeGrabber())
        assert img.size == (50, 60)

    @patch("bt_utils.window_screen_capture.get_content_rect",
           return_value=(100, 200, 500, 800))
    def test_out_of_bounds_region_is_clamped(self, _):
        """区域越界不应抛异常，按内容区尺寸钳制"""
        img = capture_window_content(1, (350, 550, 900, 900), 38, grabber=FakeGrabber())
        assert img.size == (50, 50)

    @patch("bt_utils.window_screen_capture.get_content_rect",
           return_value=(100, 200, 500, 800))
    def test_degenerate_region_raises(self, _):
        with pytest.raises(ValueError):
            capture_window_content(1, (60, 80, 10, 20), 38, grabber=FakeGrabber())

    @patch("bt_utils.window_screen_capture.get_content_rect", return_value=None)
    def test_missing_geometry_raises(self, _):
        with pytest.raises(RuntimeError):
            capture_window_content(1, None, 38, grabber=FakeGrabber())


class TestOcclusion:
    def test_not_occluded_when_all_points_hit_target(self):
        assert is_window_occluded(999, (0, 0, 300, 300), sampler=lambda x, y: 999) is False

    def test_occluded_when_any_point_hits_other_window(self):
        def sampler(x, y):
            return 1 if (x, y) == (0, 0) else 999

        assert is_window_occluded(999, (0, 0, 300, 300), sampler=sampler) is True

    def test_empty_rect_returns_false(self):
        assert is_window_occluded(999, (10, 10, 10, 10), sampler=lambda x, y: 1) is False

    def test_none_rect_returns_false(self):
        assert is_window_occluded(999, None, sampler=lambda x, y: 1) is False
