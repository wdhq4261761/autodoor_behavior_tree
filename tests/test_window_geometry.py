"""window_geometry 单元测试

纯几何逻辑与 win32 解耦：所有函数都接受矩形参数，便于在任意平台断言。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bt_utils.window_geometry import (
    DEFAULT_CONTENT_OFFSET_TOP,
    clamp_region_to_size,
    content_point_to_screen,
    content_region_to_screen,
    get_content_rect,
    offset_rect,
)


class TestOffsetRect:
    def test_offset_applied_to_top_only(self):
        """偏移只作用于顶边，底边保持不动（窗口尺寸不变）"""
        assert offset_rect((10, 20, 110, 220), 38) == (10, 58, 110, 220)

    def test_zero_offset_is_identity(self):
        assert offset_rect((10, 20, 110, 220), 0) == (10, 20, 110, 220)

    def test_negative_offset_clamped_to_zero(self):
        assert offset_rect((10, 20, 110, 220), -5) == (10, 20, 110, 220)

    def test_none_rect_returns_none(self):
        assert offset_rect(None, 38) is None


class TestPointAndRegion:
    def test_point_relative_to_content(self):
        assert content_point_to_screen((5, 6), (100, 200, 300, 400)) == (105, 206)

    def test_point_none_inputs(self):
        assert content_point_to_screen(None, (0, 0, 10, 10)) is None
        assert content_point_to_screen((1, 2), None) is None

    def test_region_relative_to_content(self):
        assert content_region_to_screen((0, 0, 50, 60), (100, 200, 300, 400)) == (
            100, 200, 150, 260,
        )

    def test_region_none_inputs(self):
        assert content_region_to_screen(None, (0, 0, 10, 10)) is None
        assert content_region_to_screen((0, 0, 1, 1), None) is None


class TestClampRegion:
    def test_within_bounds_unchanged(self):
        assert clamp_region_to_size((10, 10, 20, 20), (50, 60)) == (10, 10, 20, 20)

    def test_right_bottom_clamped(self):
        assert clamp_region_to_size((0, 0, 100, 100), (50, 60)) == (0, 0, 50, 60)

    def test_left_top_clamped(self):
        assert clamp_region_to_size((-5, -5, 100, 200), (50, 60)) == (0, 0, 50, 60)

    def test_none_region_returns_none(self):
        assert clamp_region_to_size(None, (50, 60)) is None

    def test_degenerate_region_returns_none(self):
        assert clamp_region_to_size((30, 30, 10, 10), (50, 60)) is None


class TestGetContentRect:
    def test_default_offset_is_38(self):
        assert DEFAULT_CONTENT_OFFSET_TOP == 38

    @patch("bt_utils.window_geometry.get_client_rect_screen",
           return_value=(100, 200, 300, 400))
    def test_default_offset_used(self, _):
        assert get_content_rect(123) == (100, 238, 300, 400)

    @patch("bt_utils.window_geometry.get_client_rect_screen",
           return_value=(100, 200, 300, 400))
    def test_custom_offset(self, _):
        assert get_content_rect(123, 0) == (100, 200, 300, 400)

    @patch("bt_utils.window_geometry.get_client_rect_screen", return_value=None)
    def test_none_when_client_rect_unavailable(self, _):
        assert get_content_rect(123) is None
