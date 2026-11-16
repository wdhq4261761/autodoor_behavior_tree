"""ExecutionContext 截图通道与坐标换算测试

覆盖三种截图模式、帧缓存、以及内容区顶部偏移对坐标的影响。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bt_core.context import ExecutionContext


@pytest.fixture
def ctx():
    c = ExecutionContext(project_root=str(ROOT))
    c.bind_window(12345)
    c.tick_count = 1
    return c


class TestCaptureMode:
    def test_default_mode_is_printwindow(self, ctx):
        assert ctx.get_capture_mode() == "printwindow"

    def test_invalid_mode_rejected(self, ctx):
        with pytest.raises(ValueError):
            ctx.set_capture_mode("nope")

    @patch("bt_utils.window_capture.WindowCapture.capture_window",
           return_value=Image.new("RGB", (10, 10)))
    def test_printwindow_is_default(self, mock_capture, ctx):
        ctx.get_screenshot()
        mock_capture.assert_called_once_with(12345)

    @patch("bt_utils.window_screen_capture.capture_window_content",
           return_value=Image.new("RGB", (10, 10)))
    def test_screengrab_uses_content_offset(self, mock_capture, ctx):
        ctx.set_capture_mode("screengrab")
        ctx.set_content_offset_top(38)

        ctx.get_screenshot()

        mock_capture.assert_called_once_with(12345, None, 38)

    @patch("bt_utils.window_screen_capture.capture_window_content",
           return_value=Image.new("RGB", (10, 10)))
    def test_screengrab_with_region(self, mock_capture, ctx):
        ctx.set_capture_mode("screengrab")
        ctx.get_screenshot((1, 2, 30, 40))
        mock_capture.assert_called_once_with(12345, (1, 2, 30, 40), 0)

    @patch("bt_utils.window_screen_capture.capture_window_content",
           return_value=Image.new("RGB", (10, 10)))
    def test_same_tick_screenshot_cached(self, mock_capture, ctx):
        ctx.set_capture_mode("screengrab")
        ctx.get_screenshot()
        ctx.get_screenshot()
        assert mock_capture.call_count == 1


class TestCoordinateConversion:
    def test_unbound_window_returns_region_unchanged(self):
        c = ExecutionContext(project_root=str(ROOT))
        c.set_content_offset_top(38)
        assert c.convert_to_screen_coords((5, 6)) == (5, 6)
        assert c.convert_to_screen_coords((1, 2, 3, 4)) == (1, 2, 3, 4)

    @patch("bt_utils.window_geometry.get_content_rect",
           return_value=(100, 238, 400, 800))
    def test_point_adds_content_origin(self, _, ctx):
        ctx.set_content_offset_top(38)
        assert ctx.convert_to_screen_coords((5, 6)) == (105, 244)

    @patch("bt_utils.window_geometry.get_content_rect",
           return_value=(100, 238, 400, 800))
    def test_region_adds_content_origin(self, _, ctx):
        ctx.set_content_offset_top(38)
        assert ctx.convert_to_screen_coords((0, 0, 10, 10)) == (100, 238, 110, 248)

    @patch("bt_utils.coordinate.CoordinateConverter.client_to_absolute",
           return_value=(11, 22))
    def test_zero_offset_keeps_legacy_path(self, mock_legacy, ctx):
        """偏移为 0 时必须走旧路径，保证 PC 行为零变化"""
        ctx.set_content_offset_top(0)
        assert ctx.convert_to_screen_coords((1, 2)) == (11, 22)
        mock_legacy.assert_called_once_with(1, 2, 12345)

    @patch("bt_utils.window_geometry.get_content_rect", return_value=None)
    def test_geometry_failure_falls_back(self, _, ctx):
        """取不到内容区时退回旧路径，不抛异常"""
        ctx.set_content_offset_top(38)
        with patch("bt_utils.coordinate.CoordinateConverter.client_to_absolute",
                   return_value=(7, 8)):
            assert ctx.convert_to_screen_coords((1, 2)) == (7, 8)
