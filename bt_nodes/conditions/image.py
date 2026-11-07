from bt_core.nodes import ConditionNode
from bt_core.config import NodeConfig
from typing import Dict, Any, Tuple, Optional
from PIL import Image
import os
from bt_utils.image_processor import ImageProcessor


class ImageConditionNode(ConditionNode):
    NODE_TYPE = "ImageConditionNode"

    # 类级别模板缓存，避免每次 tick 重新从磁盘加载
    _template_cache: Dict[str, Image.Image] = {}

    def __init__(self, node_id: str = None, config: NodeConfig = None):
        super().__init__(node_id, config)

    def _check_condition(self, context) -> bool:
        try:
            resolved_path = self._resolve_template_path(context)
            if resolved_path is None:
                return False

            screenshot = self._get_region_image(context)
            if screenshot is None:
                return False

            template_path = self.config.get("template_path", "")
            if not os.path.exists(resolved_path):
                self._log_condition_result(False, f"模板文件不存在: {template_path}")
                return False

            template = self._load_template(resolved_path)
            if template is None:
                self._log_condition_result(False, f"无法加载模板文件: {template_path}")
                return False

            raw_threshold = self.config.get_float("threshold", 80)
            threshold = raw_threshold / 100.0 if raw_threshold > 1 else raw_threshold

            scales = self._resolve_scales()
            found, position, confidence, best_scale = ImageProcessor.find_template_scaled(
                screenshot, template, threshold, scales=scales
            )

            if found:
                actual_position = self._adjust_position(position, context)
                self._save_position(context, actual_position)
                if scales and abs(best_scale - 1.0) > 1e-6:
                    self._log_condition_result(
                        True, f"多尺度命中 scale={best_scale:.2f}"
                    )
                else:
                    self._log_condition_result(True)
                return True
            else:
                self._log_condition_result(False, f"未找到匹配模板 (阈值: {threshold}, 最高置信度: {confidence:.2f})")
                return False
        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"ImageConditionNode '{self.name}'")
            self._log_condition_result(False, "检测异常，详情见终端日志")
            return False

    def _resolve_scales(self) -> Optional[list]:
        """解析多尺度配置，返回缩放比列表；未启用则返回 None。

        配置方式：
            multi_scale: true
            scale_range: "0.85,1.15"   （或 [0.85, 1.15]）
            scale_steps: 5
        """
        if not self.config.get_bool("multi_scale", False):
            return None

        raw_range = self.config.get("scale_range", "0.85,1.15")
        try:
            if isinstance(raw_range, (list, tuple)) and len(raw_range) >= 2:
                low, high = float(raw_range[0]), float(raw_range[1])
            else:
                parts = [p.strip() for p in str(raw_range).replace("，", ",").split(",")
                         if p.strip()]
                if len(parts) < 2:
                    return None
                low, high = float(parts[0]), float(parts[1])
        except (TypeError, ValueError):
            return None

        steps = self.config.get_int("scale_steps", 5)
        try:
            from bt_utils.image_processor import ImageProcessor
            return ImageProcessor.build_scales((low, high), steps)
        except ValueError:
            return None

    def _load_template(self, resolved_path: str) -> Optional[Image.Image]:
        """加载模板图像（带缓存）

        Args:
            resolved_path: 模板文件的绝对路径

        Returns:
            PIL.Image 图像对象，加载失败返回None
        """
        if resolved_path not in self._template_cache:
            try:
                self._template_cache[resolved_path] = Image.open(resolved_path)
            except Exception:
                return None
        return self._template_cache[resolved_path]

    @classmethod
    def clear_template_cache(cls):
        """清除模板缓存（项目切换时调用）"""
        cls._template_cache.clear()

    def _resolve_template_path(self, context) -> Optional[str]:
        """解析模板路径

        Args:
            context: 执行上下文

        Returns:
            解析后的绝对路径，或None
        """
        template_path = self.config.get("template_path", "")
        if not template_path:
            self._log_condition_result(False, "未设置模板路径")
            return None

        if template_path.startswith("./") and hasattr(context, 'resolve_path'):
            return context.resolve_path(template_path)

        return template_path
