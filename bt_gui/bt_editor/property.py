from typing import Any, Callable, Dict, Optional, List
import os
import json

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

from ..theme import Theme
from .constants import CONDITION_NODES, ACTION_NODES, COMPOSITE_NODES, INTERFACE_NODES
from bt_utils.log_manager import LogManager


def _subtree_dirs_identical(src_dir: str, dst_dir: str) -> bool:
    """判断两个目录内容是否一致（相对路径 + 文件大小）

    用于子树引用的幂等判断：同一子树重复引用时，若目标已存在且内容一致，
    则直接复用，避免重复复制导致后缀堆叠或覆盖破坏。

    Args:
        src_dir: 源目录
        dst_dir: 目标目录

    Returns:
        内容一致返回 True，否则 False
    """
    try:
        def _snapshot(root: str) -> dict:
            result = {}
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    full = os.path.join(dirpath, f)
                    rel = os.path.relpath(full, root).replace(os.sep, "/")
                    try:
                        result[rel] = os.path.getsize(full)
                    except OSError:
                        result[rel] = -1
            return result

        return _snapshot(src_dir) == _snapshot(dst_dir)
    except Exception:
        return False


NODE_CONFIG_SCHEMAS = {
    "OCRConditionNode": [
        {"key": "region_mode", "label": "区域选择方式", "type": "select", "options": ["fixed", "dynamic"], "display_names": {"fixed": "固定区域检测", "dynamic": "动态区域检测"}, "default": "fixed"},
        {"key": "region", "label": "检测区域", "type": "region", "hide_if": {"field": "region_mode", "value": "dynamic"}},
        {"key": "region_use_last_pos", "label": "锚点设置最近检测点", "type": "bool", "default": True, "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_anchor", "label": "位置变量名", "type": "text", "default": "", "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_offset", "label": "区域偏移量", "type": "region_offset", "default": [-50, -50, 50, 50], "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "keywords", "label": "关键词", "type": "text"},
        {"key": "language", "label": "语言", "type": "select", "options": ["简体中文", "English", "繁体中文"], "default": "简体中文"},
        {"key": "preprocess_mode", "label": "图像预处理", "type": "select", "options": ["默认", "复杂色彩", "自适应", "自动调优"], "default": "默认"},
        {"key": "search_direction", "label": "识别起点", "type": "select", "options": ["左上", "右上", "左下", "右下"], "default": "左上"},
        {"key": "position_key", "label": "位置变量名", "type": "text", "default": ""},
        {"key": "offset", "label": "坐标偏移", "type": "offset"},
    ],
    "ImageConditionNode": [
        {"key": "region_mode", "label": "区域选择方式", "type": "select", "options": ["fixed", "dynamic"], "display_names": {"fixed": "固定区域检测", "dynamic": "动态区域检测"}, "default": "fixed"},
        {"key": "region", "label": "检测区域", "type": "region", "hide_if": {"field": "region_mode", "value": "dynamic"}},
        {"key": "region_use_last_pos", "label": "锚点设置最近检测点", "type": "bool", "default": True, "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_anchor", "label": "位置变量名", "type": "text", "default": "", "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_offset", "label": "区域偏移量", "type": "region_offset", "default": [-50, -50, 50, 50], "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "template_path", "label": "模板路径", "type": "screenshot", "width": 120, "filetypes": [("图像文件", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")]},
        {"key": "threshold", "label": "匹配阈值(%)", "type": "number", "min": 0, "max": 100, "default": 80},
        {"key": "multi_scale", "label": "多尺度匹配", "type": "bool", "default": False},
        {"key": "scale_range", "label": "缩放范围", "type": "text", "default": "0.85,1.15", "hide_if": {"field": "multi_scale", "value": False}},
        {"key": "scale_steps", "label": "缩放步数", "type": "number", "min": 1, "max": 20, "default": 5, "hide_if": {"field": "multi_scale", "value": False}},
        {"key": "position_key", "label": "位置变量名", "type": "text", "default": ""},
        {"key": "offset", "label": "坐标偏移", "type": "offset"},
    ],
    "ColorConditionNode": [
        {"key": "region_mode", "label": "区域选择方式", "type": "select", "options": ["fixed", "dynamic"], "display_names": {"fixed": "固定区域检测", "dynamic": "动态区域检测"}, "default": "fixed"},
        {"key": "region", "label": "检测区域", "type": "region", "hide_if": {"field": "region_mode", "value": "dynamic"}},
        {"key": "region_use_last_pos", "label": "锚点设置最近检测点", "type": "bool", "default": True, "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_anchor", "label": "位置变量名", "type": "text", "default": "", "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_offset", "label": "区域偏移量", "type": "region_offset", "default": [-50, -50, 50, 50], "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "target_color", "label": "目标颜色", "type": "color"},
        {"key": "tolerance", "label": "容差", "type": "number", "min": 0, "max": 100, "default": 10},
        {"key": "min_pixels", "label": "最小像素数", "type": "number", "min": 1, "default": 1},
        {"key": "position_key", "label": "位置变量名", "type": "text", "default": ""},
        {"key": "offset", "label": "坐标偏移", "type": "offset"},
    ],
    "NumberConditionNode": [
        {"key": "region_mode", "label": "区域选择方式", "type": "select", "options": ["fixed", "dynamic"], "display_names": {"fixed": "固定区域检测", "dynamic": "动态区域检测"}, "default": "fixed"},
        {"key": "region", "label": "检测区域", "type": "region", "hide_if": {"field": "region_mode", "value": "dynamic"}},
        {"key": "region_use_last_pos", "label": "锚点设置最近检测点", "type": "bool", "default": True, "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_anchor", "label": "位置变量名", "type": "text", "default": "", "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_offset", "label": "区域偏移量", "type": "region_offset", "default": [-50, -50, 50, 50], "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "preprocess_mode", "label": "图像预处理", "type": "select", "options": ["默认", "复杂色彩", "自适应", "自动调优"], "default": "默认"},
        {"key": "extract_mode", "label": "提取模式", "type": "select", "options": ["无规则", "x/y", "自定义"], "default": "无规则"},
        {"key": "extract_pattern", "label": "自定义模式", "type": "text", "hide_if": {"field": "extract_mode", "value": ["无规则", "x/y"]}},
        {"key": "compare_mode", "label": "比较模式", "type": "select", "options": ["<", "<=", ">", ">=", "==", "!="], "default": "=="},
        {"key": "threshold", "label": "比较值", "type": "number", "default": 0},
        {"key": "min_confidence", "label": "置信度阈值(%)", "type": "number", "min": 0, "max": 100, "default": 50},
        {"key": "search_direction", "label": "识别起点", "type": "select", "options": ["左上", "右上", "左下", "右下"], "default": "左上"},
        {"key": "value_key", "label": "值变量名", "type": "text", "default": "last_number_value"},
        {"key": "position_key", "label": "位置变量名", "type": "text", "default": ""},
        {"key": "offset", "label": "坐标偏移", "type": "offset"},
    ],
    "VariableConditionNode": {
        "variable_name": {
            "type": "text",
            "label": "变量名",
            "default": ""
        },
        "operator": {
            "type": "select",
            "label": "运算符",
            "options": ["==", "!=", ">", ">=", "<", "<=", "exists", "not_exists"],
            "display_names": {
                "==": "等于",
                "!=": "不等于",
                ">": "大于",
                ">=": "大于等于",
                "<": "小于",
                "<=": "小于等于",
                "exists": "存在",
                "not_exists": "不存在"
            },
            "default": "=="
        },
        "compare_type": {
            "type": "select",
            "label": "比较值类型",
            "options": ["constant", "variable"],
            "display_names": {
                "constant": "常量值",
                "variable": "变量名"
            },
            "default": "constant",
            "hide_if": {"field": "operator", "value": ["exists", "not_exists"]}
        },
        "compare_value": {
            "type": "text",
            "label": "比较值",
            "default": "",
            "hide_if": [
                {"field": "operator", "value": ["exists", "not_exists"]},
                {"field": "compare_type", "value": "variable"}
            ]
        },
        "compare_variable": {
            "type": "variable_select",
            "label": "比较变量",
            "default": "",
            "hide_if": [
                {"field": "compare_type", "value": "constant"},
                {"field": "operator", "value": ["exists", "not_exists"]}
            ]
        }
    },
    "KeyPressNode": [
        {"key": "key", "label": "按键", "type": "key"},
        {"key": "action", "label": "动作", "type": "select", "options": ["press", "down", "up"], "default": "press"},
        {"key": "duration", "label": "按住时长(ms)", "type": "number", "default": 100, "hide_if": {"field": "action", "value": ["down", "up"]}},
        {"key": "duration_random", "label": "时长随机范围(±ms)", "type": "number", "min": 0, "default": 0, "hide_if": {"field": "action", "value": ["down", "up"]}},
    ],
    "MouseClickNode": [
        {"key": "button", "label": "按钮", "type": "select", "options": ["left", "right", "middle"], "default": "left"},
        {"key": "action", "label": "动作", "type": "select", "options": ["press", "down", "up"], "default": "press"},
        {"key": "duration", "label": "按住时长(ms)", "type": "number", "default": 100, "hide_if": {"field": "action", "value": ["down", "up"]}},
        {"key": "duration_random", "label": "时长随机范围(±ms)", "type": "number", "min": 0, "default": 0, "hide_if": {"field": "action", "value": ["down", "up"]}},
        {"key": "position", "label": "位置", "type": "position"},
        {"key": "use_blackboard", "label": "点击最近检测点", "type": "bool", "default": False},
        {"key": "position_key", "label": "位置变量名", "type": "text", "default": ""},
        {"key": "click_count", "label": "点击次数(-1无限)", "type": "number", "min": -1, "max": 10, "default": 1},
        {"key": "click_interval", "label": "点击间隔(ms)", "type": "number", "default": 100},
        {"key": "click_interval_random", "label": "间隔随机范围(±ms)", "type": "number", "min": 0, "default": 0},
        {"key": "x_float", "label": "X坐标随机范围(±px)", "type": "number", "min": 0, "default": 0},
        {"key": "y_float", "label": "Y坐标随机范围(±px)", "type": "number", "min": 0, "default": 0},
    ],
    "MouseMoveNode": [
        {"key": "position", "label": "起点位置", "type": "position"},
        {"key": "use_blackboard", "label": "起点使用最近检测点", "type": "bool", "default": False},
        {"key": "position_key", "label": "起点黑板变量名", "type": "text", "default": ""},
        {"key": "move_type", "label": "操作类型", "type": "select", "options": ["移动", "拖拽"], "default": "移动"},
        {"key": "drag_button", "label": "拖拽按键", "type": "select", "options": ["left", "right", "middle"], "default": "left", "hide_if": {"field": "move_type", "value": "移动"}},
        {"key": "relative", "label": "增量移动", "type": "bool", "default": False},
        {"key": "offset", "label": "增量值", "type": "offset", "hide_if": {"field": "relative", "value": False}},
        {"key": "end_position", "label": "终点", "type": "position", "hide_if": {"field": "relative", "value": True}},
        {"key": "use_blackboard_end", "label": "终点使用最近检测点", "type": "bool", "default": False, "hide_if": {"field": "relative", "value": True}},
        {"key": "position_key_end", "label": "终点黑板变量名", "type": "text", "default": "", "hide_if": {"field": "relative", "value": True}},
        {"key": "move_duration", "label": "移动时长(ms)", "type": "number", "default": 0},
        {"key": "move_duration_random", "label": "移动时长随机范围(±ms)", "type": "number", "min": 0, "default": 0},
        {"key": "x_float", "label": "X坐标随机范围(±px)", "type": "number", "min": 0, "default": 0},
        {"key": "y_float", "label": "Y坐标随机范围(±px)", "type": "number", "min": 0, "default": 0},
    ],
    "MouseScrollNode": [
        {"key": "distance", "label": "滚动距离", "type": "number", "default": 5},
        {"key": "clicks", "label": "滚动次数", "type": "number", "default": 1},
        {"key": "direction", "label": "滚动方向", "type": "select", "options": ["向上", "向下", "向左", "向右"], "default": "向上"},
    ],
    "DelayNode": [
        {"key": "duration_ms", "label": "延时时长(ms)", "type": "number", "default": 1000},
        {"key": "duration_ms_random", "label": "延时随机范围(±ms)", "type": "number", "min": 0, "default": 0},
    ],
    "SetVariableNode": {
        "variable_name": {
            "type": "text",
            "label": "变量名",
            "default": ""
        },
        "operation": {
            "type": "select",
            "label": "操作",
            "options": ["set", "increment", "delete"],
            "display_names": {
                "set": "赋值",
                "increment": "递增",
                "delete": "删除"
            },
            "default": "set"
        },
        "value_type": {
            "type": "select",
            "label": "赋值方式",
            "options": ["constant", "variable"],
            "display_names": {
                "constant": "常量值",
                "variable": "变量名"
            },
            "default": "constant",
            "hide_if": [
                {"field": "operation", "value": ["increment", "delete"]}
            ]
        },
        "value": {
            "type": "text",
            "label": "常量值",
            "default": "",
            "hide_if": [
                {"field": "operation", "value": "delete"},
                {"field": "value_type", "value": "variable"}
            ]
        },
        "source_variable": {
            "type": "variable_select",
            "label": "来源变量",
            "default": "",
            "hide_if": [
                {"field": "value_type", "value": "constant"},
                {"field": "operation", "value": ["increment", "delete"]}
            ]
        }
    },
    "ScriptNode": [
        {"key": "script_path", "label": "脚本路径", "type": "file", "width": 120, "filetypes": [("所有文件", "*.*")]},
        {"key": "convert_coords", "label": "", "type": "script_convert"},
        {"key": "loop", "label": "循环执行", "type": "bool", "default": False},
    ],
    "CodeNode": [
        {"key": "code_path", "label": "代码路径", "type": "file", "width": 120, "filetypes": [("所有文件", "*.*")]},
        {"key": "code_type", "label": "代码类型", "type": "select", "options": ["auto", "python", "batch", "powershell"], "default": "auto"},
        {"key": "args", "label": "命令行参数", "type": "text"},
        {"key": "wait_complete", "label": "等待执行完成", "type": "bool", "default": True},
    ],
    "AlarmNode": [
        {"key": "sound_path", "label": "音频文件", "type": "file", "width": 120, "filetypes": [("所有文件", "*.*")]},
        {"key": "volume", "label": "音量(0-100,空用全局)", "type": "number", "min": 0, "max": 100, "default": 70},
        {"key": "wait_complete", "label": "等待播放完成", "type": "bool", "default": True},
    ],
    "StartTreeNode": [
        {"key": "target_tree", "label": "目标行为树", "type": "tree_select", "default": ""},
        {"key": "sound_path", "label": "启动音效", "type": "file", "width": 120, "filetypes": [("音频文件", "*.mp3 *.wav *.ogg"), ("所有文件", "*.*")]},
        {"key": "volume", "label": "音量(0-100)", "type": "number", "min": 0, "max": 100, "default": 70},
    ],
    "StopTreeNode": [
        {"key": "target_tree", "label": "目标行为树", "type": "tree_select", "default": ""},
        {"key": "sound_path", "label": "停止音效", "type": "file", "width": 120, "filetypes": [("音频文件", "*.mp3 *.wav *.ogg"), ("所有文件", "*.*")]},
        {"key": "volume", "label": "音量(0-100)", "type": "number", "min": 0, "max": 100, "default": 70},
    ],
    "TextInputNode": [
        {"key": "input_mode", "label": "输入模式", "type": "select", "options": ["文本提取值", "预设文本", "文件"], "default": "文本提取值"},
        {"key": "preset_texts", "label": "预设文本(每行一条)", "type": "text_list", "hide_if": {"field": "input_mode", "value": ["文本提取值", "文件"]}},
        {"key": "execution_mode", "label": "执行模式", "type": "select", "options": ["顺序", "随机"], "default": "顺序", "hide_if": {"field": "input_mode", "value": ["文本提取值", "文件"]}},
        {"key": "blackboard_key", "label": "黑板变量名", "type": "text", "default": "last_extracted_text", "hide_if": {"field": "input_mode", "value": ["预设文本", "文件"]}},
        {"key": "file_path", "label": "文件路径", "type": "file", "width": 120, "filetypes": [("文本文件", "*.txt"), ("所有文件", "*.*")], "hide_if": {"field": "input_mode", "value": ["文本提取值", "预设文本"]}},
        {"key": "input_delay", "label": "输入间隔(ms)", "type": "number", "min": 0, "default": 0},
        {"key": "clear_before_input", "label": "输入前清空", "type": "bool", "default": False},
        {"key": "save_input_text", "label": "保存输入文本", "type": "bool", "default": False},
        {"key": "output_key", "label": "输出变量名", "type": "text", "default": "last_input_text", "hide_if": {"field": "save_input_text", "value": False}},
    ],
    "TextExtractNode": [
        {"key": "region_mode", "label": "区域选择方式", "type": "select", "options": ["fixed", "dynamic"], "display_names": {"fixed": "固定区域检测", "dynamic": "动态区域检测"}, "default": "fixed"},
        {"key": "region", "label": "检测区域", "type": "region", "hide_if": {"field": "region_mode", "value": "dynamic"}},
        {"key": "region_use_last_pos", "label": "锚点设置最近检测点", "type": "bool", "default": True, "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_anchor", "label": "位置变量名", "type": "text", "default": "", "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "region_offset", "label": "区域偏移量", "type": "region_offset", "default": [-50, -50, 50, 50], "hide_if": {"field": "region_mode", "value": "fixed"}},
        {"key": "extract_mode", "label": "提取模式", "type": "select", "options": ["all", "keywords"], "default": "all"},
        {"key": "keywords", "label": "关键词", "type": "text", "hide_if": {"field": "extract_mode", "value": "all"}},
        {"key": "language", "label": "语言", "type": "select", "options": ["简体中文", "English", "繁体中文"], "default": "简体中文"},
        {"key": "preprocess_mode", "label": "图像预处理", "type": "select", "options": ["默认", "复杂色彩", "自适应", "自动调优"], "default": "默认"},
        {"key": "output_key", "label": "输出变量名", "type": "text", "default": "last_extracted_text"},
        {"key": "save_all_text", "label": "保存全部文本", "type": "bool", "default": False},
        {"key": "all_text_key", "label": "全部文本变量名", "type": "text", "default": "all_ocr_text", "hide_if": {"field": "save_all_text", "value": False}},
        {"key": "save_position", "label": "保存位置", "type": "bool", "default": True},
        {"key": "position_key", "label": "位置变量名", "type": "text", "default": ""},
        {"key": "offset", "label": "坐标偏移", "type": "offset"},
    ],
    "ParallelNode": [
        {"key": "success_policy", "label": "成功策略", "type": "select", "options": ["require_all", "require_one"], "default": "require_all"},
    ],
    "RandomNode": [
        {"key": "success_policy", "label": "成功策略", "type": "select", "options": ["require_all", "require_one"], "default": "require_all"},
        {"key": "continue_on_failure", "label": "失败后继续执行", "type": "bool", "default": False},
        {"key": "fully_random", "label": "完全随机", "type": "bool", "default": False},
    ],
    "SequenceNode": [
        {"key": "childinterval", "label": "子节点间隔(ms)", "type": "number", "min": 0, "default": 0},
        {"key": "childinterval_random", "label": "子节点间隔随机范围(±ms)", "type": "number", "min": 0, "default": 0},
        {"key": "continue_on_failure", "label": "失败后继续执行", "type": "bool", "default": False},
    ],
    "SelectorNode": [
        {"key": "childinterval", "label": "子节点间隔(ms)", "type": "number", "min": 0, "default": 0},
        {"key": "childinterval_random", "label": "子节点间隔随机范围(±ms)", "type": "number", "min": 0, "default": 0},
    ],
    "StartNode": [
        {"key": "bind_window", "label": "绑定窗口", "type": "bool", "default": False},
        {"key": "window_title", "label": "窗口标题", "type": "window_select", "default": "", "hide_if": {"field": "bind_window", "value": False}},
        {"key": "window_pid", "label": "窗口PID", "type": "number", "default": 0, "hidden": True},
        {"key": "window_hwnd", "label": "窗口句柄", "type": "number", "default": 0, "hidden": True},
    ],
    "SubtreeNode": [
        {"key": "subtree_path", "label": "子树项目文件夹", "type": "folder", "width": 150},
        {"key": "blackboard_mode", "label": "黑板模式", "type": "select", "options": ["inherit", "isolated", "namespaced"], "default": "inherit"},
        {"key": "namespace", "label": "命名空间", "type": "text", "hide_if": {"field": "blackboard_mode", "value": ["inherit", "isolated"]}},
        {"key": "auto_reload", "label": "自动重载", "type": "bool", "default": False},
        {"key": "_aut_parameter_file", "label": "加密参数文件", "type": "file", "width": 150, "filetypes": [("参数文件", "*.json"), ("所有文件", "*.*")], "hidden": True},
    ],
    "HTTPRequestNode": [
        {"key": "url", "label": "请求URL", "type": "text", "default": ""},
        {"key": "method", "label": "请求方法", "type": "select", "options": ["GET", "POST", "PUT", "DELETE"], "default": "GET"},
        {"key": "body", "label": "请求体", "type": "text", "hide_if": {"field": "method", "value": ["GET", "DELETE"]}},
        {"key": "headers", "label": "请求头(JSON)", "type": "text", "default": "{}"},
        {"key": "timeout_ms", "label": "超时时间(ms)", "type": "number", "min": 100, "default": 5000},
        {"key": "expected_status", "label": "期望状态码(0不检查)", "type": "number", "min": 0, "max": 599, "default": 0},
        {"key": "response_key", "label": "响应变量名", "type": "text", "default": "http_response"},
    ],
    "APIConditionNode": [
        {"key": "url", "label": "请求URL", "type": "text", "default": ""},
        {"key": "method", "label": "请求方法", "type": "select", "options": ["GET", "POST"], "default": "GET"},
        {"key": "body", "label": "请求体", "type": "text", "hide_if": {"field": "method", "value": "GET"}},
        {"key": "headers", "label": "请求头(JSON)", "type": "text", "default": "{}"},
        {"key": "timeout_ms", "label": "超时时间(ms)", "type": "number", "min": 100, "default": 5000},
        {"key": "expected_status", "label": "期望状态码(0不检查)", "type": "number", "min": 0, "max": 599, "default": 0},
        {"key": "json_path", "label": "JSON路径", "type": "text", "default": ""},
        {"key": "expected_value", "label": "期望字段值", "type": "text", "default": ""},
    ],
    "MessagePublishNode": [
        {"key": "topic", "label": "主题", "type": "text", "default": ""},
        {"key": "payload", "label": "静态负载(JSON)", "type": "text", "default": "{}"},
        {"key": "payload_key", "label": "黑板键名", "type": "text", "default": ""},
        {"key": "prefix_tree_id", "label": "自动添加树ID前缀", "type": "bool", "default": True},
    ],
    "MessageSubscribeNode": [
        {"key": "topic", "label": "订阅主题", "type": "text", "default": ""},
        {"key": "payload_key", "label": "输出变量名", "type": "text", "default": "last_message"},
        {"key": "wait_mode", "label": "等待模式", "type": "select", "options": ["nonblocking", "blocking"], "display_names": {"nonblocking": "非阻塞", "blocking": "阻塞"}, "default": "nonblocking"},
        {"key": "timeout_ms", "label": "超时时间(ms)", "type": "number", "min": 0, "default": 0},
    ],
    "WebSocketNode": [
        {"key": "url", "label": "WebSocket地址", "type": "text", "default": ""},
        {"key": "action", "label": "操作", "type": "select", "options": ["send", "recv"], "display_names": {"send": "发送", "recv": "接收"}, "default": "send"},
        {"key": "message", "label": "发送消息", "type": "text", "default": "", "hide_if": {"field": "action", "value": "recv"}},
        {"key": "payload_key", "label": "输出变量名", "type": "text", "default": "ws_message", "hide_if": {"field": "action", "value": "send"}},
        {"key": "timeout_ms", "label": "超时时间(ms)", "type": "number", "min": 100, "default": 1000, "hide_if": {"field": "action", "value": "send"}},
    ],
}

CONDITION_DECORATOR_FIELDS = [
    {"key": "invert", "label": "结果取反", "type": "bool", "default": False},
    {"key": "retry_count", "label": "失败重试次数(-1无限)", "type": "number", "min": -1, "default": 0},
    {"key": "timeout_ms", "label": "超时时间(ms,0不限)", "type": "number", "min": 0, "default": 0},
    {"key": "check_interval_ms", "label": "检测间隔(ms)", "type": "number", "min": 30, "default": 300},
]

ACTION_DECORATOR_FIELDS = [
    {"key": "repeat_count", "label": "重复次数(0不重复,-1无限)", "type": "number", "min": -1, "default": 0},
    {"key": "repeat_interval_ms", "label": "重复间隔(ms)", "type": "number", "min": 0, "default": 100},
    {"key": "repeat_interval_ms_random", "label": "重复间隔随机范围(±ms)", "type": "number", "min": 0, "default": 0},
    {"key": "timeout_ms", "label": "超时时间(ms,0不限)", "type": "number", "min": 0, "default": 0},
]

COMPOSITE_DECORATOR_FIELDS = [
    {"key": "retry_count", "label": "失败重试次数(-1无限)", "type": "number", "min": -1, "default": 0},
    {"key": "repeat_count", "label": "重复次数(0不重复,-1无限)", "type": "number", "min": -1, "default": 0},
    {"key": "repeat_interval_ms", "label": "重复间隔(ms)", "type": "number", "min": 0, "default": 100},
    {"key": "repeat_interval_ms_random", "label": "重复间隔随机范围(±ms)", "type": "number", "min": 0, "default": 0},
    {"key": "timeout_ms", "label": "超时时间(ms,0不限)", "type": "number", "min": 0, "default": 0},
]


# ── 插件节点 schema 动态注册 ──
# NODE_CONFIG_SCHEMAS 是模块级 dict，运行时可变。
# 插件启动时调用 register_plugin_schemas() 注册其节点 schema，
# 停止时调用 unregister_plugin_schemas() 清理，保证属性面板能正确渲染插件节点配置。
_plugin_schema_index: Dict[str, str] = {}  # node_type → plugin_name（用于按插件名清理）


def register_plugin_schemas(plugin_name: str, schemas: Dict[str, list]) -> None:
    """注册插件节点 schema 到全局 NODE_CONFIG_SCHEMAS

    Args:
        plugin_name: 插件名（用于按插件名批量清理）
        schemas: {prefixed_node_type: [schema_item, ...]}
    """
    for node_type, schema in (schemas or {}).items():
        NODE_CONFIG_SCHEMAS[node_type] = schema
        _plugin_schema_index[node_type] = plugin_name


def unregister_plugin_schemas(plugin_name: str) -> None:
    """按插件名清理已注册的 schema"""
    keys_to_remove = [nt for nt, pn in _plugin_schema_index.items() if pn == plugin_name]
    for key in keys_to_remove:
        NODE_CONFIG_SCHEMAS.pop(key, None)
        _plugin_schema_index.pop(key, None)


def unregister_all_plugin_schemas() -> None:
    """清理所有插件 schema（应用退出时调用）"""
    for key in list(_plugin_schema_index.keys()):
        NODE_CONFIG_SCHEMAS.pop(key, None)
    _plugin_schema_index.clear()


class FieldWidget(ctk.CTkFrame):
    def __init__(self, master, label: str, key: str, on_change: Callable, **kwargs):
        super().__init__(master, **kwargs)
        self.label = label
        self.key = key
        self.on_change = on_change
        
        self._dark_colors = Theme.get_dark_colors()
        self.configure(fg_color="transparent")
        
        self._create_label()
    
    def _create_label(self):
        self.label_widget = ctk.CTkLabel(
            self,
            text=self.label,
            font=Theme.get_font('sm'),
            text_color=self._dark_colors['text_secondary'],
            anchor="w"
        )
        self.label_widget.pack(fill="x", pady=(Theme.DIMENSIONS['spacing_sm'], Theme.DIMENSIONS['spacing_xs']))
    
    def set_value(self, value: Any):
        pass
    
    def get_value(self) -> Any:
        return None
    
    def validate_and_save(self):
        """验证并保存当前值，子类可重写此方法实现自定义验证逻辑"""
        if hasattr(self, 'var'):
            self.on_change(self.key, self.var.get())


class TextField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, **kwargs):
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        self.var = tk.StringVar()
        self.entry = ctk.CTkEntry(
            self,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.entry.pack(fill="x")
        self.entry.bind("<FocusOut>", lambda e: self.on_change(self.key, self.var.get()))
        self.entry.bind("<Return>", self._on_return)
    
    def _on_return(self, event):
        self.on_change(self.key, self.var.get())
        self.entry.selection_clear()
        self.master.focus_set()
        return "break"
    
    def set_value(self, value: Any):
        if value is not None:
            self.var.set(str(value))
        else:
            self.var.set("")
    
    def get_value(self) -> Any:
        return self.var.get()


class NumberField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, 
                 min_val: float = None, max_val: float = None, step: float = 1, default: float = None, **kwargs):
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.default = default
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        self.var = tk.StringVar()
        self.entry = ctk.CTkEntry(
            self,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.entry.pack(fill="x")
        self.entry.bind("<FocusOut>", lambda e: self._on_change())
        self.entry.bind("<Return>", self._on_return)
    
    def _on_change(self):
        try:
            value = float(self.var.get()) if "." in self.var.get() else int(self.var.get())
            if self.min_val is not None:
                value = max(self.min_val, value)
            if self.max_val is not None:
                value = min(self.max_val, value)
            self.on_change(self.key, value)
        except ValueError:
            pass
    
    def _on_return(self, event):
        self._on_change()
        self.entry.selection_clear()
        self.master.focus_set()
        return "break"
    
    def set_value(self, value: Any):
        if value is not None:
            self.var.set(str(value))
        elif self.default is not None:
            self.var.set(str(self.default))
        elif self.min_val is not None:
            self.var.set(str(self.min_val))
        else:
            self.var.set("0")
    
    def get_value(self) -> Any:
        try:
            value = float(self.var.get()) if "." in self.var.get() else int(self.var.get())
            if self.min_val is not None:
                value = max(self.min_val, value)
            if self.max_val is not None:
                value = min(self.max_val, value)
            return value
        except ValueError:
            if self.default is not None:
                return self.default
            elif self.min_val is not None:
                return self.min_val
            else:
                return 0


class SelectField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, options: List[str] = None, display_names: Dict[str, str] = None, **kwargs):
        self.options = options or []
        self.display_names = display_names or {}
        self._reverse_names = {v: k for k, v in self.display_names.items()}
        self._display_options = [self.display_names.get(opt, opt) for opt in self.options]
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        self.var = tk.StringVar(value=self._display_options[0] if self._display_options else "")
        self.menu = ctk.CTkOptionMenu(
            self,
            variable=self.var,
            values=self._display_options,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            button_color=self._dark_colors['border'],
            button_hover_color=self._dark_colors['node_selected'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=lambda choice: self.on_change(self.key, self._reverse_names.get(choice, choice))
        )
        self.menu.pack(fill="x")
    
    def set_value(self, value: Any):
        display = self.display_names.get(str(value), str(value))
        if display in self._display_options:
            self.var.set(display)
    
    def get_value(self) -> Any:
        current = self.var.get()
        return self._reverse_names.get(current, current)


class TreeSelectField(FieldWidget):
    """行为树选择字段 — 动态获取已加载的 Tab 列表"""

    def __init__(self, master, label: str, key: str, on_change: Callable, default: str = "", **kwargs):
        self._default = default or ""
        self._tree_names = []
        self._display_options = []
        super().__init__(master, label, key, on_change, **kwargs)
        # super().__init__ 之后 self.master 才可用
        self._tree_names = self._get_available_trees()
        self._display_options = list(self._tree_names)
        self._create_widget()

    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")

        self.var = tk.StringVar(value=self._default)

        # 清空按钮
        self.clear_btn = ctk.CTkButton(
            input_frame,
            text="清空",
            font=Theme.get_font('sm'),
            width=50,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['info'],
            hover_color=self._dark_colors['info_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=self._on_clear
        )
        self.clear_btn.pack(side="right", padx=(Theme.DIMENSIONS['spacing_xs'], 0))

        # 下拉框
        self.menu = ctk.CTkOptionMenu(
            input_frame,
            variable=self.var,
            values=self._display_options,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            button_color=self._dark_colors['border'],
            button_hover_color=self._dark_colors['node_selected'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=lambda choice: self.on_change(self.key, choice)
        )
        self.menu.pack(side="left", fill="x", expand=True)

        # 通过内部 Menu 的 postcommand 在菜单弹出前刷新选项列表
        try:
            internal_menu = self.menu._dropdown_menu
            if internal_menu:
                internal_menu.configure(postcommand=lambda: self.refresh_options())
        except Exception:
            # 回退方案：绑定点击事件刷新
            self.menu.bind("<ButtonPress-1>", lambda e: self.refresh_options())

    def _on_clear(self):
        """点击清空按钮时清空当前选择"""
        self.var.set("")
        self.on_change(self.key, "")

    def _get_available_trees(self) -> list:
        """获取当前已加载的行为树名称列表"""
        try:
            # 向上遍历找到 PropertyPanel 实例，通过其 app 获取 editor
            widget = self.master
            while widget:
                if isinstance(widget, PropertyPanel):
                    app = getattr(widget, 'app', None)
                    if app and hasattr(app, 'behavior_tree'):
                        tab_manager = app.behavior_tree.tab_manager
                        if tab_manager:
                            return [inst.name for inst in tab_manager._trees.values()]
                    break
                widget = widget.master if hasattr(widget, 'master') else None
        except Exception:
            pass
        return []

    def refresh_options(self):
        """刷新下拉选项"""
        current_value = self.var.get() if hasattr(self, 'var') else ""
        self._tree_names = self._get_available_trees()
        self._display_options = list(self._tree_names)
        self.menu.configure(values=self._display_options)
        # 始终恢复之前选中的值（包括空值），防止 CTkOptionMenu 自动选择第一项
        self.var.set(current_value)

    def set_value(self, value: Any):
        val = str(value) if value else ""
        if val in self._display_options:
            self.var.set(val)

    def get_value(self) -> Any:
        return self.var.get()


class _SelectionOverlay:
    """全屏区域选取遮罩的通用底座。

    RegionField / PositionField / OffsetField / ScreenshotField /
    RegionOffsetField 原先各自复制了同一套"最小化主窗口 → 按多显示器边界铺满
    遮罩 → 放大镜跟随 → Esc 取消 → 清理"的逻辑；任何一处漏掉清理都会造成遮罩
    残留或放大镜滞留在桌面。此底座集中实现该公共逻辑，并保证 close() 幂等。

    典型用法::

        overlay = _SelectionOverlay(app, alpha=0.3, cursor="cross")
        try:
            overlay.open()
            def on_up(event):
                try:
                    ...
                finally:
                    overlay.close()
            overlay.canvas.bind("<ButtonRelease-1>", on_up)
        except ImportError:
            overlay.close()
            messagebox.showerror(...)

    注意：screeninfo 缺失时 open() 抛出 ImportError，由调用方按各自文案提示；
    放大镜库缺失时自动降级为 None（不显示放大镜）。
    """

    def __init__(self, app, *, alpha=0.3, cursor="cross", bg=None,
                 use_canvas=True, magnifier_zoom=4, magnifier_size=150):
        self.app = app
        self._alpha = alpha
        self._cursor = cursor
        self._bg = bg
        self._use_canvas = use_canvas
        self._magnifier_zoom = magnifier_zoom
        self._magnifier_size = magnifier_size

        self.window = None
        self.canvas = None
        self.magnifier = None
        self.min_x = 0
        self.min_y = 0
        self.max_x = 0
        self.max_y = 0
        self._magnifier_shown = False
        self._closed = False

    def open(self):
        """创建全屏遮罩并抓取输入；screeninfo 缺失时抛出 ImportError"""
        import time

        self.app.iconify()
        time.sleep(0.2)

        import screeninfo

        monitors = screeninfo.get_monitors()
        self.min_x = min(m.x for m in monitors)
        self.min_y = min(m.y for m in monitors)
        self.max_x = max(m.x + m.width for m in monitors)
        self.max_y = max(m.y + m.height for m in monitors)

        self.window = tk.Toplevel(self.app)
        self.window.geometry(
            f"{self.max_x - self.min_x}x{self.max_y - self.min_y}+{self.min_x}+{self.min_y}"
        )
        self.window.overrideredirect(True)
        self.window.attributes("-alpha", self._alpha)
        self.window.attributes("-topmost", True)
        window_cfg = {"cursor": self._cursor}
        if self._bg:
            window_cfg["bg"] = self._bg
        self.window.configure(**window_cfg)

        if self._use_canvas:
            self.canvas = tk.Canvas(
                self.window, bg=self._bg or "#000000", highlightthickness=0
            )
            self.canvas.pack(fill=tk.BOTH, expand=True)

        try:
            from bt_utils.magnifier import MagnifierWindow
            self.magnifier = MagnifierWindow(
                zoom_factor=self._magnifier_zoom, size=self._magnifier_size
            )
        except ImportError:
            self.magnifier = None

        self.window.bind("<Escape>", lambda e: self.close())
        self.window.focus_set()
        self.window.grab_set()
        return self

    def track_magnifier(self, event):
        """放大镜跟随鼠标：首次显示，其后更新位置"""
        if self.magnifier is None:
            return
        if not self._magnifier_shown:
            self.magnifier.show(event.x_root, event.y_root)
            self._magnifier_shown = True
        else:
            self.magnifier.update(event.x_root, event.y_root)

    def hide_magnifier(self):
        """隐藏放大镜"""
        if self.magnifier is not None:
            self.magnifier.hide()
        self._magnifier_shown = False

    def close(self, deiconify=True):
        """隐藏放大镜、销毁遮罩（可选恢复主窗口）；幂等，可重复调用

        Args:
            deiconify: 是否同时恢复主窗口。截图流程需先销毁遮罩但保持主窗口
                最小化，以便随后的截屏不包含主窗口，此时传入 False。
        """
        if self._closed:
            return
        self._closed = True
        self.hide_magnifier()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
            self.canvas = None
        if deiconify:
            self.app.deiconify()

    @staticmethod
    def is_too_small(start, end, threshold=3):
        """判断选区是否过小（任一边小于阈值，或起点缺失）"""
        if start is None or end is None:
            return True
        return abs(end[0] - start[0]) < threshold or abs(end[1] - start[1]) < threshold

    @staticmethod
    def normalize_region(start, end):
        """将两个绝对坐标点归一化为 (x1, y1, x2, y2)"""
        return (
            min(start[0], end[0]), min(start[1], end[1]),
            max(start[0], end[0]), max(start[1], end[1]),
        )



class BoolField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, default: bool = False, **kwargs):
        if default is None or default == "" or (not isinstance(default, bool) and str(default).lower() not in ("true", "false", "1", "0")):
            self._default = False
        elif isinstance(default, bool):
            self._default = default
        else:
            self._default = str(default).lower() in ("true", "1")
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        self.var = tk.BooleanVar(value=self._default)
        self.switch = ctk.CTkSwitch(
            self,
            text="",
            variable=self.var,
            width=44,
            progress_color=self._dark_colors['primary'],
            button_color=self._dark_colors['text_primary'],
            button_hover_color=self._dark_colors['text_secondary'],
            command=lambda: self.on_change(self.key, self.var.get())
        )
        self.switch.pack(anchor="w")
    
    def set_value(self, value: Any):
        if value is None:
            self.var.set(self._default)
        else:
            self.var.set(bool(value))
    
    def get_value(self) -> Any:
        return self.var.get()


class RegionField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, app, **kwargs):
        self.app = app
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="未选择")
        
        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            width=120,
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            state="disabled"
        )
        self.entry.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        self.btn = ctk.CTkButton(
            input_frame,
            text="选择",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._start_selection())
    
    def _start_selection(self):
        overlay = _SelectionOverlay(
            self.app, alpha=0.3, cursor="cross", bg=self._dark_colors['primary']
        )
        try:
            overlay.open()

            start_abs = [None]
            rect = [None]

            def on_mouse_up(event):
                end_abs = (event.x_root, event.y_root)
                if overlay.is_too_small(start_abs[0], end_abs):
                    # 先关闭遮罩与放大镜、恢复主窗口，再弹警告，避免警告框被遮挡而无法关闭
                    overlay.close()
                    messagebox.showwarning("警告", "选择的区域太小，请重新选择")
                    return
                try:
                    region = overlay.normalize_region(start_abs[0], end_abs)
                    bound_window = self._get_bound_window()
                    if bound_window:
                        from bt_utils.coordinate import CoordinateConverter
                        region = CoordinateConverter.screen_region_to_window(region, bound_window)
                    self.var.set(f"{region[0]},{region[1]},{region[2]},{region[3]}")
                    self.on_change(self.key, list(region))
                finally:
                    overlay.close()

            def on_mouse_down(event):
                overlay.hide_magnifier()
                start_abs[0] = (event.x_root, event.y_root)
                rect[0] = None

            def on_mouse_drag(event):
                overlay.track_magnifier(event)
                if start_abs[0] is None:
                    return
                if rect[0]:
                    overlay.canvas.delete(rect[0])
                rect[0] = overlay.canvas.create_rectangle(
                    start_abs[0][0] - overlay.min_x, start_abs[0][1] - overlay.min_y,
                    event.x_root - overlay.min_x, event.y_root - overlay.min_y,
                    outline="#000000", width=2, fill=""
                )

            canvas = overlay.canvas
            canvas.bind("<Motion>", overlay.track_magnifier)
            canvas.bind("<Button-1>", on_mouse_down)
            canvas.bind("<B1-Motion>", on_mouse_drag)
            canvas.bind("<ButtonRelease-1>", on_mouse_up)
        except ImportError:
            overlay.close()
            messagebox.showerror("错误", "screeninfo库未安装，无法支持区域选择。\n请运行 'pip install screeninfo' 安装该库。")
        except Exception as e:
            overlay.close()
            messagebox.showerror("错误", f"区域选择失败: {str(e)}")

    def _get_bound_window(self):
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'get_start_node'):
                start_node = editor.get_start_node()
                if start_node and hasattr(start_node, 'config'):
                    bind_window = start_node.config.get_bool("bind_window", False)
                    if bind_window:
                        window_title = start_node.config.get("window_title", "")
                        window_pid = start_node.config.get_int("window_pid", 0)
                        if window_title or window_pid:
                            from bt_utils.window_manager import WindowManager
                            hwnd, _ = WindowManager.find_window_smart(
                                window_pid if window_pid > 0 else None,
                                window_title
                            )
                            return hwnd
        return None
    
    def set_value(self, value: Any):
        if isinstance(value, (list, tuple)) and len(value) == 4:
            self.var.set(f"{value[0]},{value[1]},{value[2]},{value[3]}")
        else:
            self.var.set(str(value or "未选择"))
    
    def get_value(self) -> Any:
        return self.var.get()


class FileField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, 
                 filetypes: List[tuple] = None, app=None, width: int = None, **kwargs):
        self.filetypes = filetypes or [("所有文件", "*.*")]
        self.full_path = ""
        self.app = app
        self._width = width
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="")
        
        entry_kwargs = {
            "textvariable": self.var,
            "font": Theme.get_font('sm'),
            "height": Theme.DIMENSIONS['input_height'],
            "fg_color": self._dark_colors['bg_tertiary'],
            "border_color": self._dark_colors['border'],
            "text_color": self._dark_colors['text_primary'],
            "corner_radius": Theme.DIMENSIONS['button_corner_radius'],
            "state": "disabled"
        }
        if self._width:
            entry_kwargs["width"] = self._width
        
        self.entry = ctk.CTkEntry(input_frame, **entry_kwargs)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        self.btn = ctk.CTkButton(
            input_frame,
            text="浏览",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._browse())
    
    def _get_project_root(self):
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'project_root') and editor.project_root:
                return editor.project_root
            
            if hasattr(editor, 'file_path') and editor.file_path:
                project_root = self._find_project_root(editor.file_path)
                if project_root:
                    return project_root
        
        return None
    
    def _find_project_root(self, file_path: str):
        """向上查找项目根目录"""
        current_dir = os.path.dirname(file_path)
        
        while current_dir:
            project_json_path = os.path.join(current_dir, "project.json")
            if os.path.exists(project_json_path):
                return current_dir
            
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break
            current_dir = parent_dir
        
        return None
    
    def _get_editor(self):
        if self.app and hasattr(self.app, 'behavior_tree'):
            return self.app.behavior_tree
        return None
    
    def _prompt_create_project(self):
        from tkinter import messagebox
        result = messagebox.askyesno(
            "提示",
            "请先创建或打开项目，才能导入资源文件。\n\n是否现在创建新项目？"
        )
        if result:
            editor = self._get_editor()
            if editor and hasattr(editor, '_on_new_project_dialog'):
                editor._on_new_project_dialog()
        return result
    
    def _browse(self):
        project_root = self._get_project_root()
        
        if not project_root:
            self._prompt_create_project()
            return
        
        initial_dir = None
        if self.full_path:
            abs_full_path = self.full_path
            if self.full_path.startswith("./"):
                abs_full_path = os.path.normpath(os.path.join(project_root, self.full_path[2:]))
            if os.path.exists(abs_full_path):
                initial_dir = os.path.dirname(abs_full_path)
        else:
            if os.path.exists(project_root):
                initial_dir = project_root
        
        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="选择文件",
            filetypes=self.filetypes
        )
        
        if not file_path:
            return
        
        from bt_utils.resource_service import ResourceService
        
        resource_type = ResourceService.RESOURCE_TYPE_MAP.get(self.key)
        
        # 不再传递 old_path：旧文件可能仍被其他复制节点引用
        # 资源清理统一在保存时由 cleanup_unreferenced_files 处理
        relative_path = ResourceService.import_single_file_to_project(
            file_path,
            project_root,
            resource_type=resource_type
        )
        
        if relative_path:
            self.full_path = relative_path
            filename = relative_path.split("/")[-1]
            self.var.set(filename)
            self.on_change(self.key, relative_path)
        else:
            from tkinter import messagebox
            messagebox.showwarning(
                "导入警告",
                "无法将文件复制到项目文件夹，将使用原始绝对路径。\n"
                "注意：使用绝对路径可能导致项目迁移后文件丢失。"
            )
            self.full_path = file_path
            filename = file_path.split("/")[-1].split("\\")[-1]
            self.var.set(filename)
            self.on_change(self.key, file_path)
    
    def set_value(self, value: Any):
        if value:
            self.full_path = str(value)
            filename = str(value).split("/")[-1].split("\\")[-1]
            self.var.set(filename)
        else:
            self.var.set("")
    
    def get_value(self) -> Any:
        return self.full_path


class FolderField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable,
                 app=None, width: int = None, **kwargs):
        self.full_path = ""
        self.app = app
        self._width = width
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()

    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")

        self.var = tk.StringVar(value="")

        entry_kwargs = {
            "textvariable": self.var,
            "font": Theme.get_font('sm'),
            "height": Theme.DIMENSIONS['input_height'],
            "fg_color": self._dark_colors['bg_tertiary'],
            "border_color": self._dark_colors['border'],
            "text_color": self._dark_colors['text_primary'],
            "corner_radius": Theme.DIMENSIONS['button_corner_radius'],
            "state": "disabled"
        }
        if self._width:
            entry_kwargs["width"] = self._width

        self.entry = ctk.CTkEntry(input_frame, **entry_kwargs)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, Theme.DIMENSIONS['spacing_xs']))

        self.btn = ctk.CTkButton(
            input_frame,
            text="浏览",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._browse())

    def _get_project_root(self):
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'project_root') and editor.project_root:
                return editor.project_root
        return None

    def _browse(self):
        project_root = self._get_project_root()

        initial_dir = None
        if self.full_path:
            abs_full_path = self.full_path
            if self.full_path.startswith("./"):
                abs_full_path = os.path.normpath(os.path.join(project_root or ".", self.full_path[2:]))
            if os.path.isdir(abs_full_path):
                initial_dir = os.path.dirname(abs_full_path)
        else:
            if project_root and os.path.exists(project_root):
                initial_dir = os.path.dirname(project_root)

        folder_path = filedialog.askdirectory(
            initialdir=initial_dir,
            title="选择子树项目文件夹"
        )

        if not folder_path:
            return

        project_json = os.path.join(folder_path, "project.json")
        tree_json = os.path.join(folder_path, "tree.json")
        if not os.path.exists(project_json) and not os.path.exists(tree_json):
            from tkinter import messagebox
            result = messagebox.askyesno(
                "提示",
                f"所选文件夹中未找到 project.json 或 tree.json。\n\n是否仍要使用此文件夹作为子树项目？"
            )
            if not result:
                return

        if project_root:
            import shutil
            folder_name = os.path.basename(folder_path)
            subtrees_dir = os.path.join(project_root, "subtrees")
            os.makedirs(subtrees_dir, exist_ok=True)

            abs_project_root = os.path.abspath(project_root)
            abs_subtrees_dir = os.path.abspath(subtrees_dir)
            abs_source = os.path.abspath(folder_path)

            # 自复制防护：源文件夹已在项目 subtrees 目录内，直接引用，避免复制到自己内部
            if abs_source.startswith(abs_subtrees_dir + os.sep):
                rel_path = os.path.relpath(abs_source, abs_project_root).replace(os.sep, "/")
                if not rel_path.startswith("./"):
                    rel_path = "./" + rel_path
                self.full_path = rel_path
                self.var.set(folder_name)
                self.on_change(self.key, rel_path)
                return

            dest_dir = os.path.join(subtrees_dir, folder_name)

            # 幂等：目标已存在且与源内容一致 → 直接复用，不重复复制
            if os.path.exists(dest_dir) and _subtree_dirs_identical(folder_path, dest_dir):
                rel_path = "./subtrees/" + folder_name
                self.full_path = rel_path
                self.var.set(folder_name)
                self.on_change(self.key, rel_path)
                return

            if os.path.exists(dest_dir):
                from tkinter import messagebox
                result = messagebox.askyesno(
                    "文件夹已存在",
                    f"子树文件夹 '{folder_name}' 已存在于当前项目中。\n\n是否覆盖？"
                )
                if not result:
                    rel_path = "./subtrees/" + folder_name
                    self.full_path = rel_path
                    self.var.set(folder_name)
                    self.on_change(self.key, rel_path)
                    return
                # 安全覆盖：先复制到临时目录，成功后再替换旧目录，避免源目录被误删导致子树丢失
                tmp_dir = os.path.join(subtrees_dir, f".{folder_name}.tmp_{os.getpid()}")
                try:
                    if os.path.exists(tmp_dir):
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    shutil.copytree(folder_path, tmp_dir)
                    from bt_utils.resource_service import ResourceService
                    ResourceService.move_dir_to_cache(dest_dir, project_root)
                    shutil.copytree(tmp_dir, dest_dir)
                except Exception as e:
                    from tkinter import messagebox
                    messagebox.showerror("复制失败", f"复制子树项目文件夹失败: {e}")
                    return
                finally:
                    if os.path.exists(tmp_dir):
                        try:
                            shutil.rmtree(tmp_dir, ignore_errors=True)
                        except Exception:
                            pass
            else:
                try:
                    shutil.copytree(folder_path, dest_dir)
                except Exception as e:
                    from tkinter import messagebox
                    messagebox.showerror("复制失败", f"复制子树项目文件夹失败: {e}")
                    return

            rel_path = "./subtrees/" + folder_name
            self.full_path = rel_path
            self.var.set(folder_name)
            self.on_change(self.key, rel_path)
            return

        self.full_path = folder_path
        folder_name = os.path.basename(folder_path)
        self.var.set(folder_name)
        self.on_change(self.key, folder_path)

    def set_value(self, value: Any):
        if value:
            self.full_path = str(value)
            display = str(value)
            if "/" in display or "\\" in display:
                display = display.replace("\\", "/").split("/")[-1]
            self.var.set(display)
        else:
            self.var.set("")

    def get_value(self) -> Any:
        return self.full_path


class ScreenshotField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, 
                 filetypes: List[tuple] = None, app=None, width: int = None, **kwargs):
        self.filetypes = filetypes or [("所有文件", "*.*")]
        self.full_path = ""
        self.app = app
        self._width = width
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="")
        
        entry_kwargs = {
            "textvariable": self.var,
            "font": Theme.get_font('sm'),
            "height": Theme.DIMENSIONS['input_height'],
            "fg_color": self._dark_colors['bg_tertiary'],
            "border_color": self._dark_colors['border'],
            "text_color": self._dark_colors['text_primary'],
            "corner_radius": Theme.DIMENSIONS['button_corner_radius'],
            "state": "disabled"
        }
        if self._width:
            entry_kwargs["width"] = self._width
        
        self.entry = ctk.CTkEntry(input_frame, **entry_kwargs)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        self.browse_btn = ctk.CTkButton(
            input_frame,
            text="浏览",
            font=Theme.get_font('sm'),
            width=50,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.browse_btn.pack(side="right")
        self.browse_btn.bind("<ButtonRelease-1>", lambda e: self._browse())
        
        screenshot_frame = ctk.CTkFrame(self, fg_color="transparent")
        screenshot_frame.pack(fill="x", pady=(Theme.DIMENSIONS['spacing_xs'], 0))
        
        self.screenshot_btn = ctk.CTkButton(
            screenshot_frame,
            text="截图",
            font=Theme.get_font('sm'),
            width=50,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['info'],
            hover_color=self._dark_colors['info_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.screenshot_btn.pack(side="left")
        self.screenshot_btn.bind("<ButtonRelease-1>", lambda e: self._take_screenshot())
    
    def _browse(self):
        project_root = self._get_project_root()
        
        if not project_root:
            from tkinter import messagebox
            result = messagebox.askyesno(
                "提示",
                "请先创建或打开项目，才能导入资源文件。\n\n是否现在创建新项目？"
            )
            if result:
                if self.app and hasattr(self.app, 'behavior_tree'):
                    editor = self.app.behavior_tree
                    if hasattr(editor, '_on_new_project_dialog'):
                        editor._on_new_project_dialog()
            return
        
        initial_dir = None
        if self.full_path:
            abs_full_path = self.full_path
            if self.full_path.startswith("./"):
                abs_full_path = os.path.normpath(os.path.join(project_root, self.full_path[2:]))
            if os.path.exists(abs_full_path):
                initial_dir = os.path.dirname(abs_full_path)
        else:
            if os.path.exists(project_root):
                initial_dir = project_root
        
        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="选择文件",
            filetypes=self.filetypes
        )
        
        if not file_path:
            return
        
        from bt_utils.resource_service import ResourceService
        
        resource_type = ResourceService.RESOURCE_TYPE_MAP.get(self.key)
        
        # 不再传递 old_path：旧文件可能仍被其他复制节点引用
        # 资源清理统一在保存时由 cleanup_unreferenced_files 处理
        relative_path = ResourceService.import_single_file_to_project(
            file_path,
            project_root,
            resource_type=resource_type
        )
        
        if relative_path:
            self.full_path = relative_path
            filename = relative_path.split("/")[-1]
            self.var.set(filename)
            self.on_change(self.key, relative_path)
        else:
            from tkinter import messagebox
            messagebox.showwarning(
                "导入警告",
                "无法将文件复制到项目文件夹，将使用原始绝对路径。\n"
                "注意：使用绝对路径可能导致项目迁移后文件丢失。"
            )
            self.full_path = file_path
            filename = file_path.split("/")[-1].split("\\")[-1]
            self.var.set(filename)
            self.on_change(self.key, file_path)
    
    def _take_screenshot(self):
        import os
        from tkinter import messagebox
        
        try:
            if not self.app:
                messagebox.showerror("错误", "应用实例未初始化")
                return
            
            app_dir = self._get_project_root()
            if not app_dir:
                self.app.deiconify()
                messagebox.showerror("错误", "请先保存项目，再进行截图操作")
                return
            
            image_dir = os.path.join(app_dir, "images", "templates")
            
            if not os.path.exists(image_dir):
                os.makedirs(image_dir)
            
            self.app._screenshot_callback = self._save_screenshot
            self._start_screenshot_selection()
            
        except Exception as e:
            if self.app:
                self.app.deiconify()
            messagebox.showerror("错误", f"截图失败: {str(e)}")
    
    def _start_screenshot_selection(self):
        overlay = _SelectionOverlay(
            self.app, alpha=0.3, cursor="cross", bg=self._dark_colors['primary']
        )
        try:
            overlay.open()

            start_abs = [None]
            rect = [None]

            def on_mouse_up(event):
                end_abs = (event.x_root, event.y_root)
                if overlay.is_too_small(start_abs[0], end_abs):
                    overlay.close()
                    messagebox.showwarning("警告", "选择的区域太小，请重新选择")
                    return
                try:
                    # 先销毁遮罩但保持主窗口最小化，避免主窗口出现在截图中；
                    # 截图回调在截屏完成后再自行恢复主窗口。
                    overlay.close(deiconify=False)
                    region = overlay.normalize_region(start_abs[0], end_abs)
                    callback = getattr(self.app, '_screenshot_callback', None)
                    if callable(callback):
                        callback(region)
                finally:
                    self.app.deiconify()

            def on_mouse_down(event):
                overlay.hide_magnifier()
                start_abs[0] = (event.x_root, event.y_root)
                rect[0] = None

            def on_mouse_drag(event):
                overlay.track_magnifier(event)
                if start_abs[0] is None:
                    return
                if rect[0]:
                    overlay.canvas.delete(rect[0])
                rect[0] = overlay.canvas.create_rectangle(
                    start_abs[0][0] - overlay.min_x, start_abs[0][1] - overlay.min_y,
                    event.x_root - overlay.min_x, event.y_root - overlay.min_y,
                    outline="#000000", width=2, fill=""
                )

            canvas = overlay.canvas
            canvas.bind("<Motion>", overlay.track_magnifier)
            canvas.bind("<Button-1>", on_mouse_down)
            canvas.bind("<B1-Motion>", on_mouse_drag)
            canvas.bind("<ButtonRelease-1>", on_mouse_up)
        except ImportError:
            overlay.close()
            messagebox.showerror("错误", "screeninfo库未安装，无法支持多显示器选择。\n请运行 'pip install screeninfo' 安装该库。")
        except Exception as e:
            overlay.close()
            messagebox.showerror("错误", f"区域选择失败: {str(e)}")
    
    def _save_screenshot(self, region):
        import os
        import time
        from tkinter import messagebox
        
        try:
            project_root = self._get_project_root()
            if not project_root:
                self.app.deiconify()
                messagebox.showerror("错误", "请先保存项目，再进行截图操作")
                return
            
            old_path = self.full_path if self.full_path else None
            
            image_dir = os.path.join(project_root, "images", "templates")
            
            if not os.path.exists(image_dir):
                os.makedirs(image_dir)
            
            time.sleep(0.2)
            
            from bt_utils.screenshot import ScreenshotManager
            screenshot = ScreenshotManager().get_region_screenshot(region)
            
            self.app.deiconify()
            
            if not screenshot:
                messagebox.showerror("错误", "无法获取截图区域")
                return
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"template_{timestamp}.png"
            save_path = os.path.join(image_dir, filename)
            
            screenshot.save(save_path)
            
            from bt_utils.path_resolver import PathResolver
            resolver = PathResolver(project_root)
            relative_path = resolver.to_relative(save_path)
            
            self.full_path = relative_path
            self.var.set(filename)
            self.on_change(self.key, relative_path)
            
            # 不再移动旧截图到缓存：旧截图可能仍被其他复制节点引用
            # 资源清理统一在保存时由 cleanup_unreferenced_files 处理
            
            messagebox.showinfo("成功", f"截图已保存到:\n{relative_path}")
            
        except Exception as e:
            self.app.deiconify()
            messagebox.showerror("错误", f"保存截图失败: {str(e)}")
    
    def _get_project_root(self):
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'project_root') and editor.project_root:
                return editor.project_root
            
            if hasattr(editor, 'file_path') and editor.file_path:
                project_root = self._find_project_root(editor.file_path)
                if project_root:
                    return project_root
        
        return None
    
    def _find_project_root(self, file_path: str):
        """向上查找项目根目录"""
        import os
        current_dir = os.path.dirname(file_path)
        
        while current_dir:
            project_json_path = os.path.join(current_dir, "project.json")
            if os.path.exists(project_json_path):
                return current_dir
            
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:
                break
            current_dir = parent_dir
        
        return None
    
    def set_value(self, value: Any):
        if value:
            self.full_path = str(value)
            filename = str(value).split("/")[-1].split("\\")[-1]
            self.var.set(filename)
        else:
            self.var.set("")
    
    def get_value(self) -> Any:
        return self.full_path


class KeyField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, **kwargs):
        self._listening = False
        self._pynput_listener = None
        self._timeout_id = None
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="")
        
        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            state="disabled"
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        self.btn = ctk.CTkButton(
            input_frame,
            text="修改",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._start_listening())
    
    def _start_listening(self):
        if self._listening:
            self._stop_listening()
            return
        
        self._listening = True
        self.btn.configure(text="取消", fg_color=self._dark_colors['warning'])
        
        try:
            toplevel = self.winfo_toplevel()
            if hasattr(toplevel, 'set_keyfield_active'):
                toplevel.set_keyfield_active(True)
        except Exception:
            pass
        
        from pynput import keyboard
        from bt_utils.key_name_resolver import resolve_key_name
        
        def on_press(key):
            key_name = resolve_key_name(key)
            if key_name:
                try:
                    self.after(0, lambda: self._on_key_captured(key_name))
                except Exception:
                    pass
                return False
        
        self._pynput_listener = keyboard.Listener(on_press=on_press)
        self._pynput_listener.start()
        
        self._timeout_id = self.after(10000, self._stop_listening)
    
    def _on_key_captured(self, key_name: str):
        if not self._listening:
            return
        
        self.var.set(key_name)
        self.on_change(self.key, key_name)
        self._stop_listening()
    
    def _stop_listening(self):
        self._listening = False
        
        if self._pynput_listener:
            try:
                self._pynput_listener.stop()
            except Exception:
                pass
            self._pynput_listener = None
        
        if self._timeout_id:
            self.after_cancel(self._timeout_id)
            self._timeout_id = None
        
        try:
            toplevel = self.winfo_toplevel()
            if hasattr(toplevel, 'set_keyfield_active'):
                toplevel.set_keyfield_active(False)
        except Exception:
            pass
        
        try:
            if self.winfo_exists():
                self.btn.configure(text="修改", fg_color=self._dark_colors['primary'])
        except Exception:
            pass
    
    def set_value(self, value: Any):
        self.var.set(str(value or ""))
    
    def get_value(self) -> Any:
        return self.var.get()


class PositionField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, app, **kwargs):
        self.app = app
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="未选择")
        
        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, Theme.DIMENSIONS['spacing_xs']))
        self.entry.bind("<FocusOut>", lambda e: self._parse_and_change())
        
        self.btn = ctk.CTkButton(
            input_frame,
            text="获取",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._pick_position())
    
    def _parse_and_change(self):
        try:
            parts = self.var.get().replace(" ", "").split(",")
            if len(parts) >= 2:
                value = [int(parts[0]), int(parts[1])]
                self.on_change(self.key, value)
        except (ValueError, AttributeError):
            pass
    
    def _pick_position(self):
        overlay = _SelectionOverlay(
            self.app, alpha=0.2, cursor="crosshair",
            bg=self._dark_colors['primary'], use_canvas=False
        )
        try:
            overlay.open()

            label = tk.Label(
                overlay.window,
                text="点击选择位置",
                font=("Microsoft YaHei", 24),
                bg=self._dark_colors['primary'],
                fg="#FFFFFF"
            )
            label.place(relx=0.5, rely=0.5, anchor="center")

            def on_click(event):
                try:
                    x, y = event.x_root, event.y_root
                    bound_window = self._get_bound_window()
                    if bound_window:
                        from bt_utils.coordinate import CoordinateConverter
                        converted = CoordinateConverter.absolute_to_client(x, y, bound_window)
                        if converted:
                            x, y = converted
                    self.var.set(f"{x}, {y}")
                    self.on_change(self.key, [x, y])
                finally:
                    overlay.close()

            overlay.window.bind("<Motion>", overlay.track_magnifier)
            overlay.window.bind("<Button-1>", on_click)
        except ImportError:
            overlay.close()
            messagebox.showerror("错误", "screeninfo库未安装，无法支持位置选择。\n请运行 'pip install screeninfo' 安装该库。")
        except Exception as e:
            overlay.close()
            messagebox.showerror("错误", f"位置选择失败: {str(e)}")
    
    def set_value(self, value: Any):
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            self.var.set(f"{value[0]}, {value[1]}")
        else:
            self.var.set(str(value or "未选择"))
    
    def get_value(self) -> Any:
        try:
            parts = self.var.get().replace(" ", "").split(",")
            if len(parts) >= 2:
                return [int(parts[0]), int(parts[1])]
            return None
        except (ValueError, AttributeError):
            return None
    
    def _get_bound_window(self):
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'get_start_node'):
                start_node = editor.get_start_node()
                if start_node and hasattr(start_node, 'config'):
                    bind_window = start_node.config.get_bool("bind_window", False)
                    if bind_window:
                        window_title = start_node.config.get("window_title", "")
                        window_pid = start_node.config.get_int("window_pid", 0)
                        if window_title or window_pid:
                            from bt_utils.window_manager import WindowManager
                            hwnd, _ = WindowManager.find_window_smart(
                                window_pid if window_pid > 0 else None,
                                window_title
                            )
                            return hwnd
        return None


class OffsetField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, app, **kwargs):
        self.app = app
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="0, 0")
        
        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, Theme.DIMENSIONS['spacing_xs']))
        self.entry.bind("<FocusOut>", lambda e: self._parse_and_change())
        
        self.btn = ctk.CTkButton(
            input_frame,
            text="测量",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._measure_offset())
    
    def _parse_and_change(self):
        try:
            parts = self.var.get().replace(" ", "").split(",")
            if len(parts) >= 2:
                value = [int(parts[0]), int(parts[1])]
                self.on_change(self.key, value)
        except (ValueError, AttributeError):
            pass
    
    def _measure_offset(self):
        overlay = _SelectionOverlay(
            self.app, alpha=0.2, cursor="crosshair",
            bg=self._dark_colors['primary'], use_canvas=False
        )
        try:
            overlay.open()

            label = tk.Label(
                overlay.window,
                text="第一步：点击参考点（检测目标位置）",
                font=("Microsoft YaHei", 24),
                bg=self._dark_colors['primary'],
                fg="#FFFFFF"
            )
            label.place(relx=0.5, rely=0.5, anchor="center")

            reference_point = [None]

            def on_click(event):
                if reference_point[0] is None:
                    reference_point[0] = (event.x_root, event.y_root)
                    label.config(text="第二步：点击目标点（实际操作位置）")
                else:
                    try:
                        target_point = (event.x_root, event.y_root)
                        offset_x = target_point[0] - reference_point[0][0]
                        offset_y = target_point[1] - reference_point[0][1]
                        self.var.set(f"{offset_x}, {offset_y}")
                        self.on_change(self.key, [offset_x, offset_y])
                    finally:
                        overlay.close()

            overlay.window.bind("<Motion>", overlay.track_magnifier)
            overlay.window.bind("<Button-1>", on_click)
        except ImportError:
            overlay.close()
            messagebox.showerror("错误", "screeninfo库未安装，无法支持偏移测量。\n请运行 'pip install screeninfo' 安装该库。")
        except Exception as e:
            overlay.close()
            messagebox.showerror("错误", f"偏移测量失败: {str(e)}")
    
    def set_value(self, value: Any):
        if value is not None:
            if isinstance(value, (list, tuple)) and len(value) >= 2:
                self.var.set(f"{value[0]}, {value[1]}")
            else:
                self.var.set("0, 0")
        else:
            self.var.set("0, 0")
    
    def get_value(self) -> Any:
        try:
            parts = self.var.get().replace(" ", "").split(",")
            if len(parts) >= 2:
                return [int(parts[0]), int(parts[1])]
            return [0, 0]
        except (ValueError, AttributeError):
            return [0, 0]


class RegionOffsetField(FieldWidget):
    def __init__(self, master, label, key, on_change, app, **kwargs):
        self.app = app
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()

    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")

        self.var = tk.StringVar(value="-50, -50, 50, 50")

        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.entry.pack(side="left", fill="x", expand=True,
                        padx=(0, Theme.DIMENSIONS['spacing_xs']))
        self.entry.bind("<FocusOut>", lambda e: self._parse_and_change())

        self.btn = ctk.CTkButton(
            input_frame,
            text="测量",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._measure_region_offset())

    def _parse_and_change(self):
        try:
            parts = self.var.get().replace(" ", "").split(",")
            if len(parts) >= 4:
                value = [int(p) for p in parts[:4]]
                self.on_change(self.key, value)
        except (ValueError, AttributeError):
            pass

    def _measure_region_offset(self):
        overlay = _SelectionOverlay(
            self.app, alpha=0.3, cursor="crosshair", bg=self._dark_colors['primary']
        )
        try:
            overlay.open()

            canvas = overlay.canvas
            label = tk.Label(
                canvas,
                text="第一步：点击锚点（参考位置）",
                font=("Microsoft YaHei", 24),
                bg=self._dark_colors['primary'],
                fg="#FFFFFF"
            )
            canvas.create_window(
                (overlay.max_x - overlay.min_x) // 2,
                (overlay.max_y - overlay.min_y) // 2,
                window=label
            )

            reference_point = [None]
            drag_start_abs = [None]
            drag_start_rel = [None]
            rect_id = [None]

            def on_click(event):
                if reference_point[0] is None:
                    reference_point[0] = (event.x_root, event.y_root)
                    label.config(text="第二步：按住并拖拽选择区域范围")
                    overlay.hide_magnifier()
                else:
                    drag_start_abs[0] = (event.x_root, event.y_root)
                    drag_start_rel[0] = (event.x_root - overlay.min_x, event.y_root - overlay.min_y)
                    rect_id[0] = None

            def on_drag(event):
                overlay.track_magnifier(event)
                if reference_point[0] and drag_start_rel[0]:
                    if rect_id[0]:
                        canvas.delete(rect_id[0])
                    rect_id[0] = canvas.create_rectangle(
                        drag_start_rel[0][0], drag_start_rel[0][1],
                        event.x_root - overlay.min_x, event.y_root - overlay.min_y,
                        outline="#000000", width=2, fill=""
                    )

            def on_release(event):
                if not (reference_point[0] and drag_start_abs[0]):
                    return
                end_abs = (event.x_root, event.y_root)
                # 与 RegionField 行为对齐：选区过小时结束选择并提示，而非静默重置
                if overlay.is_too_small(drag_start_abs[0], end_abs):
                    overlay.close()
                    messagebox.showwarning("警告", "选择的区域太小，请重新选择")
                    return
                try:
                    rx, ry = reference_point[0]
                    sx, sy = drag_start_abs[0]
                    ex, ey = end_abs
                    offset_x1 = min(sx, ex) - rx
                    offset_y1 = min(sy, ey) - ry
                    offset_x2 = max(sx, ex) - rx
                    offset_y2 = max(sy, ey) - ry
                    self.var.set(f"{offset_x1}, {offset_y1}, {offset_x2}, {offset_y2}")
                    self.on_change(self.key, [offset_x1, offset_y1, offset_x2, offset_y2])
                finally:
                    overlay.close()

            canvas.bind("<Motion>", overlay.track_magnifier)
            canvas.bind("<Button-1>", on_click)
            canvas.bind("<B1-Motion>", on_drag)
            canvas.bind("<ButtonRelease-1>", on_release)
        except ImportError:
            overlay.close()
            messagebox.showerror("错误", "screeninfo库未安装，无法支持区域偏移测量。")
        except Exception as e:
            overlay.close()
            messagebox.showerror("错误", f"区域偏移测量失败: {str(e)}")

    def set_value(self, value):
        if value is not None:
            if isinstance(value, (list, tuple)) and len(value) >= 4:
                self.var.set(f"{value[0]}, {value[1]}, {value[2]}, {value[3]}")
            else:
                self.var.set("-50, -50, 50, 50")
        else:
            self.var.set("-50, -50, 50, 50")

    def get_value(self):
        try:
            parts = self.var.get().replace(" ", "").split(",")
            if len(parts) >= 4:
                return [int(p) for p in parts[:4]]
            return [-50, -50, 50, 50]
        except (ValueError, AttributeError):
            return [-50, -50, 50, 50]


class WindowSelectField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, app, update_other_field: Callable = None, **kwargs):
        self.app = app
        self._window_titles = []
        self._window_hwnd_map = {}
        self._window_pids = {}
        self._update_other_field = update_other_field
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()

    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")

        self.var = tk.StringVar(value="")

        self._refresh_window_list()

        # 先放置清空按钮，确保其宽度不被挤压
        self.clear_btn = ctk.CTkButton(
            input_frame,
            text="清空",
            font=Theme.get_font('sm'),
            width=50,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['info'],
            hover_color=self._dark_colors['info_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.clear_btn.pack(side="right", padx=(Theme.DIMENSIONS['spacing_xs'], 0))
        self.clear_btn.bind("<ButtonRelease-1>", lambda e: self._clear_selection())

        # 再放置下拉框，使用剩余空间
        self.combobox = ctk.CTkOptionMenu(
            input_frame,
            variable=self.var,
            values=self._window_titles,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            button_color=self._dark_colors['border'],
            button_hover_color=self._dark_colors['node_selected'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            width=140,
            command=self._on_window_selected
        )
        self.combobox.pack(side="left", fill="x", expand=True)

    def _on_window_selected(self, choice: str):
        self.var.set(choice)
        self.on_change(self.key, choice)
        if choice in self._window_hwnd_map:
            hwnd = self._window_hwnd_map[choice]
            if hwnd:
                self.on_change("window_hwnd", hwnd)
                self.on_change("bind_window", True)
                if self._update_other_field:
                    self._update_other_field("bind_window", True)
        if choice in self._window_pids:
            pid = self._window_pids[choice]
            if pid:
                self.on_change("window_pid", pid)

    def _clear_selection(self):
        self.var.set("")
        self.on_change(self.key, "")
        self.on_change("window_pid", 0)
        self.on_change("window_hwnd", 0)

    def _refresh_window_list(self):
        from bt_utils.window_manager import WindowManager
        
        current_value = self.var.get() if hasattr(self, 'var') else ""
        
        windows = WindowManager.enum_all_windows()
        
        title_count = {}
        self._window_titles = []
        self._window_hwnd_map = {}
        self._window_pids = {}
        
        for hwnd, title in windows:
            pid = WindowManager.get_window_pid(hwnd)
            if title in title_count:
                title_count[title] += 1
                display_title = f"{title} (PID:{pid})"
            else:
                title_count[title] = 1
                display_title = title
            self._window_titles.append(display_title)
            self._window_hwnd_map[display_title] = hwnd
            if pid:
                self._window_pids[display_title] = pid
        
        
        if hasattr(self, 'combobox'):
            self.combobox.configure(values=self._window_titles)
            if current_value and current_value in self._window_titles:
                self.var.set(current_value)

    def set_value(self, value: Any):
        if value and hasattr(self, 'combobox'):
            self.var.set(str(value))

    def get_value(self) -> Any:
        value = self.var.get()
        return value


class ScriptConvertField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, app, **kwargs):
        self.app = app
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()

    def _create_widget(self):
        self.convert_btn = ctk.CTkButton(
            self,
            text="转换相对坐标",
            font=Theme.get_font('sm'),
            width=100,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['info'],
            hover_color=self._dark_colors['info_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.convert_btn.pack(anchor="w")
        self.convert_btn.bind("<ButtonRelease-1>", lambda e: self._on_convert_click())

    def _get_project_root(self) -> str:
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'project_root') and editor.project_root:
                return editor.project_root
        return None

    def _resolve_script_path(self, script_path: str) -> str:
        if not script_path:
            return script_path
        if script_path.startswith("./"):
            project_root = self._get_project_root()
            if project_root:
                return os.path.join(project_root, script_path[2:])
        if not os.path.isabs(script_path):
            return os.path.abspath(script_path)
        return script_path

    def _get_script_path(self) -> str:
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'property_panel'):
                panel = editor.property_panel
                if "script_path" in panel.widgets:
                    widget = panel.widgets["script_path"]
                    val = widget.get_value()
                    if val:
                        return str(val)
        return ""

    def _get_start_node_config(self) -> dict:
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'get_start_node'):
                start_node = editor.get_start_node()
                if start_node:
                    return {
                        "bind_window": getattr(start_node, 'bind_window', False),
                        "window_title": getattr(start_node, 'window_title', ""),
                        "window_pid": getattr(start_node, 'window_pid', 0),
                    }
        return {}

    def _check_window_marker(self, content: str) -> dict:
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("# Window:"):
                return {
                    "has_marker": True,
                    "window_title": line[len("# Window:"):].strip()
                }
        return {"has_marker": False, "window_title": ""}

    def _backup_script(self, script_path: str) -> str:
        import shutil
        backup_path = script_path + ".bak"
        shutil.copy2(script_path, backup_path)
        return backup_path

    def _convert_coordinates(self, content: str, hwnd: int, window_title: str):
        import re
        from bt_utils.coordinate import CoordinateConverter

        converted_count = 0

        def replace_coord(match):
            nonlocal converted_count
            x, y = int(match.group(1)), int(match.group(2))
            result = CoordinateConverter.absolute_to_client(x, y, hwnd)
            if result:
                converted_count += 1
                return f"MoveTo {result[0]}, {result[1]}"
            return match.group(0)

        new_content = re.sub(r'MoveTo\s+(\d+)\s*,\s*(\d+)', replace_coord, content)

        rect = CoordinateConverter.get_window_rect(hwnd)
        header = f"# Window: {window_title}\n"
        if rect:
            header += f"# WindowRect: {rect[0]}, {rect[1]}, {rect[2]}, {rect[3]}\n"

        return header + new_content, converted_count

    def _on_convert_click(self):
        import tkinter.messagebox as messagebox
        from bt_utils.window_manager import WindowManager

        try:
            script_path = self._get_script_path()
            if not script_path:
                messagebox.showwarning("提示", "请先选择脚本文件")
                return

            absolute_script_path = self._resolve_script_path(script_path)

            if not os.path.exists(absolute_script_path):
                messagebox.showerror("错误", f"脚本文件不存在: {absolute_script_path}")
                return

            with open(absolute_script_path, 'r', encoding='utf-8') as f:
                content = f.read()

            marker = self._check_window_marker(content)
            if marker["has_marker"]:
                messagebox.showwarning("提示",
                    f"该脚本已完成相对坐标转换（窗口：{marker['window_title']}），不要重复执行")
                return

            start_config = self._get_start_node_config()
            if not start_config.get("bind_window"):
                messagebox.showinfo("提示", "当前项目未进行窗口绑定，无需转换相对坐标")
                return

            hwnd, _ = WindowManager.find_window_smart(
                start_config.get("window_pid") if start_config.get("window_pid", 0) > 0 else None,
                start_config.get("window_title", "")
            )
            if not hwnd:
                messagebox.showerror("错误", "未找到绑定窗口，请确保窗口已打开")
                return

            backup_path = self._backup_script(absolute_script_path)

            new_content, count = self._convert_coordinates(
                content, hwnd, start_config.get("window_title", "")
            )

            with open(absolute_script_path, 'w', encoding='utf-8') as f:
                f.write(new_content)

            messagebox.showinfo("成功",
                f"转换完成，已将 {count} 个坐标转换为窗口相对坐标\n原脚本已备份至 {backup_path}")

        except Exception as e:
            messagebox.showerror("错误", f"转换失败: {str(e)}")

    def set_value(self, value: Any):
        pass

    def get_value(self) -> Any:
        return None


class ColorField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, app, **kwargs):
        self.app = app
        self._current_color = "#808080"
        self._last_validate_time = 0
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()
    
    def _create_widget(self):
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x")
        
        self.var = tk.StringVar(value="未选择")
        self._rgb_value = None
        
        self.preview = ctk.CTkFrame(
            input_frame,
            width=32,
            height=32,
            fg_color=self._current_color,
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.preview.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_xs']))
        
        self.entry = ctk.CTkEntry(
            input_frame,
            textvariable=self.var,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            width=100,
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.entry.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_xs']))
        self.entry.bind("<FocusOut>", lambda e: self._parse_and_change())
        
        self.btn = ctk.CTkButton(
            input_frame,
            text="选择",
            font=Theme.get_font('sm'),
            width=60,
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['primary'],
            hover_color=self._dark_colors['primary_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
        )
        self.btn.pack(side="right")
        self.btn.bind("<ButtonRelease-1>", lambda e: self._pick_color())
    
    def _parse_and_change(self):
        import time
        from tkinter import messagebox
        
        current_time = time.time()
        if current_time - self._last_validate_time < 0.5:
            return
        self._last_validate_time = current_time
        
        text = self.var.get().strip()
        if text == "未选择" or not text:
            return
        
        parts = text.replace(" ", "").split(",")
        
        if len(parts) != 3:
            messagebox.showwarning("格式错误", "请输入正确的颜色格式: R, G, B\n例如: 255, 0, 0")
            if self._rgb_value:
                self.var.set(f"{self._rgb_value[0]}, {self._rgb_value[1]}, {self._rgb_value[2]}")
            else:
                self.var.set("未选择")
            return
        
        try:
            r = int(parts[0])
            g = int(parts[1])
            b = int(parts[2])
        except ValueError:
            messagebox.showwarning("数值错误", "颜色值必须是整数\n例如: 255, 128, 0")
            if self._rgb_value:
                self.var.set(f"{self._rgb_value[0]}, {self._rgb_value[1]}, {self._rgb_value[2]}")
            else:
                self.var.set("未选择")
            return
        
        if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            messagebox.showwarning("数值范围", f"颜色值已自动修正到 0-255 范围\n修正后: {r}, {g}, {b}")
        
        self.var.set(f"{r}, {g}, {b}")
        self._current_color = f"#{r:02x}{g:02x}{b:02x}"
        self._rgb_value = [r, g, b]
        self.preview.configure(fg_color=self._current_color)
        self.on_change(self.key, self._rgb_value)
    
    def validate_and_save(self):
        """验证并保存当前值（重写父类方法）"""
        self._parse_and_change()
    
    def _pick_color(self):
        from bt_gui.widgets import create_color_picker
        
        def on_color_picked(rgb):
            r, g, b = rgb
            self.var.set(f"{r}, {g}, {b}")
            self._current_color = f"#{r:02x}{g:02x}{b:02x}"
            self._rgb_value = [r, g, b]
            self.preview.configure(fg_color=self._current_color)
            self.on_change(self.key, self._rgb_value)
        
        create_color_picker(self.app, on_color_picked)
    
    def set_value(self, value: Any):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            r, g, b = int(value[0]), int(value[1]), int(value[2])
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            self.var.set(f"{r}, {g}, {b}")
            self._current_color = f"#{r:02x}{g:02x}{b:02x}"
            self._rgb_value = [r, g, b]
            self.preview.configure(fg_color=self._current_color)
        else:
            self.var.set(str(value or "未选择"))
            self._rgb_value = None
    
    def get_value(self) -> Any:
        try:
            text = self.var.get().strip()
            if text == "未选择" or not text:
                return self._rgb_value
            
            parts = text.replace(" ", "").split(",")
            if len(parts) >= 3:
                r = max(0, min(255, int(parts[0])))
                g = max(0, min(255, int(parts[1])))
                b = max(0, min(255, int(parts[2])))
                return [r, g, b]
            return self._rgb_value
        except (ValueError, AttributeError):
            return self._rgb_value


class TextListField(FieldWidget):
    def __init__(self, master, label: str, key: str, on_change: Callable, **kwargs):
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()

    def _create_widget(self):
        self.textbox = ctk.CTkTextbox(
            self,
            height=80,
            font=Theme.get_font('sm'),
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius']
        )
        self.textbox.pack(fill="x")
        self.textbox.bind("<FocusOut>", lambda e: self._on_change())

    def _on_change(self):
        self.on_change(self.key, self.get_value())

    def validate_and_save(self):
        self._on_change()

    def set_value(self, value: Any):
        self.textbox.delete("1.0", tk.END)
        if isinstance(value, list) and value:
            self.textbox.insert("1.0", '\n'.join(str(v) for v in value))
        elif isinstance(value, str) and value:
            self.textbox.insert("1.0", value)

    def get_value(self) -> Any:
        text = self.textbox.get("1.0", tk.END).strip()
        if not text:
            return []
        return [line.strip() for line in text.split('\n') if line.strip()]


class VariableSelectField(FieldWidget):
    @classmethod
    def _get_builtin_vars(cls) -> Dict[str, str]:
        from bt_core.blackboard import Blackboard
        return Blackboard.get_builtin_vars_info()

    def __init__(self, master, label: str, key: str, on_change: Callable, **kwargs):
        builtin_vars = self._get_builtin_vars()
        self._REVERSE_NAMES = {v: k for k, v in builtin_vars.items()}
        self._display_options = list(builtin_vars.values())
        super().__init__(master, label, key, on_change, **kwargs)
        self._create_widget()

    def _create_widget(self):
        self.var = tk.StringVar(value="")
        self.combobox = ctk.CTkComboBox(
            self,
            variable=self.var,
            values=self._display_options,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['bg_tertiary'],
            border_color=self._dark_colors['border'],
            button_color=self._dark_colors['border'],
            button_hover_color=self._dark_colors['node_selected'],
            text_color=self._dark_colors['text_primary'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=self._on_dropdown_select
        )
        self.combobox.pack(fill="x")
        self.combobox.bind("<FocusOut>", lambda e: self._on_value_change())
        self.combobox.bind("<Return>", lambda e: self._on_value_change())

    def _on_dropdown_select(self, choice: str):
        internal_value = self._REVERSE_NAMES.get(choice, choice)
        self.on_change(self.key, internal_value)

    def _on_value_change(self):
        current = self.var.get()
        internal_value = self._REVERSE_NAMES.get(current, current)
        self.on_change(self.key, internal_value)

    def set_value(self, value: Any):
        if value is None:
            self.var.set("")
            return
        builtin_vars = self._get_builtin_vars()
        display = builtin_vars.get(str(value), str(value))
        self.var.set(display)

    def get_value(self) -> Any:
        current = self.var.get()
        return self._REVERSE_NAMES.get(current, current)


class PropertyPanel(ctk.CTkFrame):
    def __init__(self, master, app, on_change: Optional[Callable[[str, str, Any], None]] = None, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app
        self.on_change = on_change
        
        self.current_node_id: Optional[str] = None
        self.current_node_type: Optional[str] = None
        self.widgets: Dict[str, FieldWidget] = {}
        self.field_schemas: Dict[str, Dict[str, Any]] = {}
        self.field_containers: Dict[str, Any] = {}
        self._hidden_values: Dict[str, Any] = {}
        self._is_loading: bool = False
        # 异步加载队列
        self._async_load_queue: list = []
        self._async_load_config: dict = {}
        # Widget复用：同类型节点切换时仅更新值
        self._last_node_type: Optional[str] = None
        
        self._dark_colors = Theme.get_dark_colors()
        self.configure(
            fg_color=self._dark_colors['sidebar_bg'],
            corner_radius=0,
            width=Theme.DIMENSIONS['property_width']
        )
        
        self._create_ui()
        self._bind_click_event()
    
    def is_loading(self) -> bool:
        return self._is_loading
    
    def _bind_click_event(self):
        def on_click(event):
            focused = self.focus_get()
            if focused:
                widget_type = str(type(focused).__name__)
                if widget_type in ("CTkEntry", "Entry"):
                    self.focus_set()
        
        self.bind("<Button-1>", on_click)
        self.header_frame.bind("<Button-1>", on_click)
        self.title_label.bind("<Button-1>", on_click)
        self.node_type_label.bind("<Button-1>", on_click)
        self.separator.bind("<Button-1>", on_click)
        self.content_frame.bind("<Button-1>", on_click)
    
    def force_save_current_field(self):
        """强制保存当前焦点控件的值"""
        focused = self.focus_get()
        if not focused:
            return
        
        for key, widget in self.widgets.items():
            try:
                if hasattr(widget, 'entry'):
                    entry_widget = widget.entry
                    
                    if entry_widget == focused:
                        self._save_widget_value(widget)
                        return
                    
                    if hasattr(entry_widget, '_entry'):
                        if entry_widget._entry == focused:
                            self._save_widget_value(widget)
                            return
                    
                    if hasattr(entry_widget, 'winfo_children'):
                        for child in entry_widget.winfo_children():
                            if child == focused:
                                self._save_widget_value(widget)
                                return
                
                if hasattr(widget, 'textbox'):
                    if widget.textbox == focused:
                        self._save_widget_value(widget)
                        return
                    if hasattr(widget.textbox, '_textbox'):
                        if widget.textbox._textbox == focused:
                            self._save_widget_value(widget)
                            return
            except Exception:
                pass
    
    def _save_widget_value(self, widget):
        """保存控件的值"""
        try:
            widget.validate_and_save()
        except Exception:
            pass
    
    def _create_ui(self):
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_md'])
        
        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="属性面板",
            font=Theme.get_font('lg'),
            text_color=self._dark_colors['text_primary']
        )
        self.title_label.pack(side="left")
        
        self.node_type_label = ctk.CTkLabel(
            self.header_frame,
            text="",
            font=Theme.get_font('sm'),
            text_color=self._dark_colors['text_muted']
        )
        self.node_type_label.pack(side="right")
        
        self.separator = ctk.CTkFrame(
            self,
            height=1,
            fg_color=self._dark_colors['border']
        )
        self.separator.pack(fill="x", padx=Theme.DIMENSIONS['spacing_md'])
        
        self.content_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=self._dark_colors['bg_tertiary'],
            scrollbar_button_hover_color=self._dark_colors['border']
        )
        self.content_frame.pack(fill="both", expand=True, padx=Theme.DIMENSIONS['spacing_md'], pady=Theme.DIMENSIONS['spacing_sm'])
        
        self._show_empty()
    
    def _show_empty(self):
        self._clear_content()
        self.title_label.configure(text="属性面板")
        self.node_type_label.configure(text="")
        
        empty_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        empty_frame.pack(expand=True)
        
        empty_icon = ctk.CTkLabel(
            empty_frame,
            text="◇",
            font=("Arial", 32),
            text_color=self._dark_colors['border']
        )
        empty_icon.pack(pady=(Theme.DIMENSIONS['spacing_xl'], Theme.DIMENSIONS['spacing_md']))
        
        empty_text = ctk.CTkLabel(
            empty_frame,
            text="请选择一个节点\n查看和编辑属性",
            font=Theme.get_font('sm'),
            text_color=self._dark_colors['text_muted'],
            justify="center"
        )
        empty_text.pack()
    
    def _update_values_only(self, node_data: Dict[str, Any]):
        """同类型节点切换时仅更新字段值，不重建控件

        当连续选择同类型节点时（如两个OCR节点），字段结构完全相同，
        只需更新各字段的值即可，避免销毁+重建控件的开销。

        Args:
            node_data: 新节点的数据
        """
        config_data = node_data.get("config", {})

        # 更新基本信息字段
        name_widget = self.widgets.get("name")
        if name_widget:
            name_widget.set_value(node_data.get("name", ""))
        enabled_widget = self.widgets.get("enabled")
        if enabled_widget:
            enabled_widget.set_value(node_data.get("enabled", True))
        skip_widget = self.widgets.get("skip")
        if skip_widget:
            skip_widget.set_value(node_data.get("skip", False))

        # 更新配置字段值
        for key, widget in self.widgets.items():
            if key in ("name", "enabled", "skip"):
                continue  # 基本信息已单独处理

            # TreeSelectField 需要刷新选项列表
            if isinstance(widget, TreeSelectField):
                widget.refresh_options()

            value = config_data.get(key)
            if key in self._hidden_values:
                self._hidden_values[key] = value
            elif key in self.field_schemas:
                field = self.field_schemas[key]
                display_value = value if value is not None else field.get("default")
                widget.set_value(display_value)
                self._update_single_field_visibility(key, field)

        self._is_loading = False

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        self.widgets.clear()
        self.field_schemas.clear()
        self.field_containers.clear()
        self._hidden_values.clear()
        self._async_load_queue.clear()
        self._last_node_type = None
    
    def save_and_clear(self):
        self.current_node_id = None
        self.current_node_type = None
        self._show_empty()
    
    # 异步加载每批字段数
    _ASYNC_FIELDS_PER_BATCH = 3

    def load_node(self, node_id: str, node_type: str, node_data: Dict[str, Any]):
        self._is_loading = True

        try:
            self.current_node_id = node_id
            self.current_node_type = node_type

            # Widget复用优化：同类型节点切换时仅更新值，不重建控件
            if self._last_node_type == node_type and self.widgets:
                self._update_values_only(node_data)
                return

            self._last_node_type = node_type

            self._clear_content()

            display_name = node_type.replace("Node", "").replace("Condition", "").replace("Action", "")
            self.title_label.configure(text="节点属性")
            self.node_type_label.configure(text=display_name)

            # 基本信息（少量字段，同步创建）
            self._create_base_fields(node_data)

            # 收集后续需要异步创建的字段列表
            async_steps = []

            schema = NODE_CONFIG_SCHEMAS.get(node_type, [])
            if schema:
                config_data = node_data.get("config", {})
                if node_type == "SetVariableNode" and config_data.get("operation") == "clear":
                    config_data["operation"] = "delete"
                    config_data.pop("value", None)
                    config_data.pop("value_type", None)
                    config_data.pop("source_variable", None)

                self._create_section_title("配置参数")
                self.config_fields_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
                self.config_fields_frame.pack(fill="x")

                if isinstance(schema, dict):
                    field_list = [{"key": k, **v} for k, v in schema.items()]
                else:
                    field_list = schema

                for field in field_list:
                    value = config_data.get(field["key"]) if isinstance(field, dict) and "key" in field else config_data.get(field.get("key"))
                    async_steps.append(("config_field", field, value))

            config = node_data.get("config", {})
            if node_type == "SubtreeNode" and isinstance(config, dict) and "_aut_parameter_file" in config:
                async_steps.append(("aut_param", config, None))

            if node_type in CONDITION_NODES:
                async_steps.append(("preview_section", node_type, node_data.get("config", {})))

            decorator_fields = []
            if node_type in CONDITION_NODES:
                decorator_fields = CONDITION_DECORATOR_FIELDS
            elif node_type in ACTION_NODES:
                decorator_fields = ACTION_DECORATOR_FIELDS
            elif node_type in COMPOSITE_NODES or node_type == "StartNode":
                decorator_fields = COMPOSITE_DECORATOR_FIELDS

            if decorator_fields:
                async_steps.append(("decorator_section", decorator_fields, node_data.get("config", {})))

            # 分帧异步加载
            if async_steps:
                self._async_load_queue = list(async_steps)
                self._async_load_config = node_data.get("config", {})
                self._schedule_async_load()
            else:
                self._is_loading = False
        except Exception:
            self._is_loading = False

    def _schedule_async_load(self):
        """调度下一批异步字段加载"""
        if not self._async_load_queue:
            self._is_loading = False
            return
        self.after(1, self._do_async_load_batch)

    def _do_async_load_batch(self):
        """执行一批异步字段创建"""
        batch_count = 0
        while self._async_load_queue and batch_count < self._ASYNC_FIELDS_PER_BATCH:
            step_type, data, extra = self._async_load_queue.pop(0)

            try:
                if step_type == "config_field":
                    self._create_field(data, extra, self.config_fields_frame)
                elif step_type == "aut_param":
                    self._create_aut_param_section(data)
                elif step_type == "preview_section":
                    self._create_preview_section(data, extra)
                elif step_type == "decorator_section":
                    self._create_section_title("装饰参数")
                    self.decorator_fields_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
                    self.decorator_fields_frame.pack(fill="x")
                    for field in data:
                        self._create_field(field, extra.get(field["key"]), self.decorator_fields_frame)
            except Exception as e:
                LogManager.debug_print(f"[WARN] 异步加载字段失败: {e}")

            batch_count += 1

        self._schedule_async_load()
    
    def _create_preview_section(self, node_type: str, config: Dict[str, Any]):
        self._create_section_title("预览检测")
        
        preview_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        preview_frame.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])
        
        self.preview_btn = ctk.CTkButton(
            preview_frame,
            text="🔍 预览检测",
            width=100,
            command=lambda: self._on_preview_click(node_type)
        )
        self.preview_btn.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_sm']))
        
        self.view_image_btn = ctk.CTkButton(
            preview_frame,
            text="查看识别图片",
            width=100,
            font=Theme.get_font('sm'),
            height=Theme.DIMENSIONS['input_height'],
            fg_color=self._dark_colors['info'],
            hover_color=self._dark_colors['info_hover'],
            corner_radius=Theme.DIMENSIONS['button_corner_radius'],
            command=self._open_preview_image
        )
        self._preview_image_path = None
        self.view_image_btn.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_sm']))
        self.view_image_btn.pack_forget()
    
    def _on_preview_click(self, node_type: str):
        from bt_utils.log_manager import LogManager

        # 预览检测前，确保运行日志面板已展开
        self._ensure_log_panel_expanded()

        self.view_image_btn.pack_forget()
        self.update_idletasks()

        try:
            config = self._get_current_config()
            result = self._run_condition_node_preview(node_type, config)

            if result.get("image_path"):
                self._preview_image_path = result["image_path"]
                self.view_image_btn.pack(side="left", padx=(0, Theme.DIMENSIONS['spacing_sm']))

        except Exception as e:
            LogManager.instance().log_failure(
                node_type="预览检测",
                node_name=node_type.replace("Node", ""),
                reason=f"检测异常: {str(e)}"
            )

    def _ensure_log_panel_expanded(self):
        """确保运行日志面板已展开，未展开时自动展开"""
        try:
            if self.app and hasattr(self.app, 'behavior_tree'):
                editor = self.app.behavior_tree
                if hasattr(editor, 'log_panel') and editor.log_panel:
                    if not editor.log_panel.is_expanded():
                        editor.log_panel.expand()
        except Exception:
            pass
    
    def _open_preview_image(self):
        if self._preview_image_path and os.path.exists(self._preview_image_path):
            import subprocess
            import platform
            if platform.system() == 'Windows':
                os.startfile(self._preview_image_path)
            elif platform.system() == 'Darwin':
                subprocess.run(['open', self._preview_image_path])
            else:
                subprocess.run(['xdg-open', self._preview_image_path])
    
    def _get_preview_images_dir(self) -> str:
        if self.app and hasattr(self.app, 'behavior_tree'):
            editor = self.app.behavior_tree
            if hasattr(editor, 'project_root') and editor.project_root:
                images_dir = os.path.join(editor.project_root, "images")
                if not os.path.exists(images_dir):
                    os.makedirs(images_dir)
                return images_dir
        return None
    
    def _cleanup_old_preview_images(self):
        images_dir = self._get_preview_images_dir()
        if images_dir and os.path.exists(images_dir):
            for filename in os.listdir(images_dir):
                if filename.startswith("preview_") and filename.endswith(".png"):
                    try:
                        os.remove(os.path.join(images_dir, filename))
                    except Exception:
                        pass
    
    def cleanup_preview_images(self):
        self._cleanup_old_preview_images()
    
    def _get_current_config(self) -> Dict[str, Any]:
        config = {}
        for key, widget in self.widgets.items():
            if hasattr(widget, 'get_value'):
                config[key] = widget.get_value()
        for key, value in self._hidden_values.items():
            config[key] = value
        return config
    
    def _run_condition_node_preview(self, node_type: str, config: Dict[str, Any]):
        from bt_core.config import NodeConfig
        from bt_core.blackboard import Blackboard
        from PIL import ImageGrab, ImageDraw
        import importlib
        import time
        
        self._cleanup_old_preview_images()
        
        node_config = NodeConfig(name="预览检测")
        for key, value in config.items():
            node_config.set(key, value)
        
        class PreviewContext:
            def __init__(ctx, app):
                ctx._app = app
                ctx._screenshot = None
                ctx._is_running = True
                ctx.blackboard = Blackboard()
                ctx._bound_window = None
                
                if app and hasattr(app, 'behavior_tree'):
                    editor = app.behavior_tree
                    if hasattr(editor, 'project_root') and editor.project_root:
                        ctx._project_root = editor.project_root
                    else:
                        ctx._project_root = None
                    
                    if hasattr(editor, 'get_start_node'):
                        start_node = editor.get_start_node()
                        if start_node:
                            bind_window = getattr(start_node, 'bind_window', False)
                            if bind_window:
                                window_title = getattr(start_node, 'window_title', '')
                                window_pid = getattr(start_node, 'window_pid', 0)
                                from bt_utils.window_manager import WindowManager
                                hwnd, _ = WindowManager.find_window_smart(
                                    window_pid if window_pid > 0 else None,
                                    window_title
                                )
                                if hwnd:
                                    ctx._bound_window = hwnd
                else:
                    ctx._project_root = None
            
            def get_screenshot(ctx, region=None):
                if ctx._bound_window:
                    from bt_utils.window_capture import WindowCapture
                    if ctx._screenshot is None:
                        ctx._screenshot = WindowCapture.capture_window(ctx._bound_window)
                    if region and ctx._screenshot:
                        return ctx._screenshot.crop(region)
                    return ctx._screenshot
                else:
                    if ctx._screenshot is None:
                        ctx._screenshot = ImageGrab.grab(all_screens=True)
                    if region:
                        return ImageGrab.grab(bbox=region, all_screens=True)
                    return ctx._screenshot
            
            def get_full_screenshot(ctx):
                if ctx._screenshot is None:
                    if ctx._bound_window:
                        from bt_utils.window_capture import WindowCapture
                        ctx._screenshot = WindowCapture.capture_window(ctx._bound_window)
                    else:
                        ctx._screenshot = ImageGrab.grab(all_screens=True)
                return ctx._screenshot
            
            def get_bound_window(ctx):
                return ctx._bound_window
            
            def resolve_path(ctx, relative_path):
                if relative_path.startswith("./") and ctx._project_root:
                    import os
                    return os.path.normpath(os.path.join(ctx._project_root, relative_path[2:]))
                return relative_path
            
            @property
            def project_root(ctx):
                return ctx._project_root
            
            def check_running(ctx):
                return True
        
        context = PreviewContext(self.app)
        
        node_map = {
            "OCRConditionNode": "bt_nodes.conditions.ocr:OCRConditionNode",
            "ImageConditionNode": "bt_nodes.conditions.image:ImageConditionNode",
            "ColorConditionNode": "bt_nodes.conditions.color:ColorConditionNode",
            "NumberConditionNode": "bt_nodes.conditions.number:NumberConditionNode",
            "VariableConditionNode": "bt_nodes.conditions.variable:VariableConditionNode",
            "TextExtractNode": "bt_nodes.conditions.text_extract:TextExtractNode",
        }
        
        if node_type not in node_map:
            return {"success": False, "image_path": None}
        
        module_path, class_name = node_map[node_type].split(":")
        module = importlib.import_module(module_path)
        node_class = getattr(module, class_name)
        node = node_class(config=node_config)
        success = node._check_condition(context)
        
        image_path = None
        images_dir = self._get_preview_images_dir()
        if images_dir and context._screenshot:
            screenshot = context._screenshot.copy()
            
            if context._bound_window:
                offset_x, offset_y = 0, 0
            else:
                try:
                    import screeninfo
                    monitors = screeninfo.get_monitors()
                    offset_x = -min(monitor.x for monitor in monitors)
                    offset_y = -min(monitor.y for monitor in monitors)
                except Exception:
                    offset_x, offset_y = 0, 0
            
            draw = ImageDraw.Draw(screenshot)
            
            region = config.get("region")
            if region:
                if isinstance(region, str):
                    try:
                        parts = [int(x.strip()) for x in region.split(",")]
                        if len(parts) == 4:
                            region = tuple(parts)
                        else:
                            region = None
                    except (ValueError, AttributeError):
                        region = None
                elif isinstance(region, (list, tuple)) and len(region) == 4:
                    region = tuple(region)
                else:
                    region = None
            
            if region and len(region) == 4:
                draw.rectangle(
                    [region[0] + offset_x, region[1] + offset_y,
                     region[2] + offset_x, region[3] + offset_y],
                    outline="red", width=2
                )
            
            timestamp = int(time.time() * 1000)
            image_path = os.path.join(images_dir, f"preview_{timestamp}.png")
            screenshot.save(image_path)
        
        return {"success": success, "image_path": image_path}
    
    def _create_section_title(self, title: str):
        section_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        section_frame.pack(fill="x", pady=(Theme.DIMENSIONS['spacing_lg'], Theme.DIMENSIONS['spacing_sm']))
        
        section_label = ctk.CTkLabel(
            section_frame,
            text=title,
            font=Theme.get_font('sm'),
            text_color=self._dark_colors['text_primary']
        )
        section_label.pack(side="left")
        
        section_line = ctk.CTkFrame(
            section_frame,
            height=1,
            fg_color=self._dark_colors['border']
        )
        section_line.pack(side="left", fill="x", expand=True, padx=(Theme.DIMENSIONS['spacing_sm'], 0))
    
    def _create_base_fields(self, node_data: Dict[str, Any]):
        self._create_section_title("基本信息")
        
        name_field = TextField(
            self.content_frame,
            label="名称",
            key="name",
            on_change=self._on_field_change
        )
        name_field.set_value(node_data.get("name", ""))
        name_field.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])
        self.widgets["name"] = name_field
        
        enabled_field = BoolField(
            self.content_frame,
            label="启用",
            key="enabled",
            on_change=self._on_field_change
        )
        enabled_field.set_value(node_data.get("enabled", True))
        enabled_field.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])
        self.widgets["enabled"] = enabled_field

        skip_field = BoolField(
            self.content_frame,
            label="跳过",
            key="skip",
            on_change=self._on_field_change
        )
        skip_field.set_value(node_data.get("skip", False))
        skip_field.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])
        self.widgets["skip"] = skip_field
    
    def _create_field(self, field: Dict[str, Any], value: Any, parent_frame=None):
        field_type = field.get("type", "text")
        key = field["key"]
        label = field["label"]
        
        self.field_schemas[key] = field
        
        if field.get("hidden", False):
            self._hidden_values[key] = value
            return
        
        container = parent_frame if parent_frame else self.content_frame
        
        field_widget = None
        
        if field_type == "text":
            field_widget = TextField(container, label, key, self._on_field_change)
        elif field_type == "number":
            field_widget = NumberField(
                container, label, key, self._on_field_change,
                min_val=field.get("min"), max_val=field.get("max"), step=field.get("step", 1),
                default=field.get("default")
            )
        elif field_type == "select":
            field_widget = SelectField(
                container, label, key, self._on_field_change,
                options=field.get("options", []),
                display_names=field.get("display_names")
            )
        elif field_type == "bool":
            field_widget = BoolField(container, label, key, self._on_field_change, default=field.get("default", False))
        elif field_type == "region":
            field_widget = RegionField(container, label, key, self._on_field_change, self.app)
        elif field_type == "file":
            field_widget = FileField(
                container, label, key, self._on_field_change,
                filetypes=field.get("filetypes", [("所有文件", "*.*")]),
                app=self.app,
                width=field.get("width")
            )
        elif field_type == "folder":
            field_widget = FolderField(
                container, label, key, self._on_field_change,
                app=self.app,
                width=field.get("width")
            )
        elif field_type == "screenshot":
            field_widget = ScreenshotField(
                container, label, key, self._on_field_change,
                filetypes=field.get("filetypes", [("所有文件", "*.*")]),
                app=self.app,
                width=field.get("width")
            )
        elif field_type == "key":
            field_widget = KeyField(container, label, key, self._on_field_change)
        elif field_type == "position":
            field_widget = PositionField(container, label, key, self._on_field_change, self.app)
        elif field_type == "color":
            field_widget = ColorField(container, label, key, self._on_field_change, self.app)
        elif field_type == "offset":
            field_widget = OffsetField(container, label, key, self._on_field_change, self.app)
        elif field_type == "region_offset":
            field_widget = RegionOffsetField(container, label, key, self._on_field_change, self.app)
        elif field_type == "window_select":
            field_widget = WindowSelectField(container, label, key, self._on_field_change, self.app, self._update_widget_value)
        elif field_type == "script_convert":
            field_widget = ScriptConvertField(container, label, key, self._on_field_change, self.app)
        elif field_type == "text_list":
            field_widget = TextListField(container, label, key, self._on_field_change)
        elif field_type == "variable_select":
            field_widget = VariableSelectField(container, label, key, self._on_field_change)
        elif field_type == "tree_select":
            field_widget = TreeSelectField(container, label, key, self._on_field_change, default=field.get("default", ""))
            # 创建后刷新选项，确保获取最新的 Tab 列表
            if isinstance(field_widget, TreeSelectField):
                field_widget.refresh_options()
        
        if field_widget:
            display_value = value if value is not None else field.get("default")
            field_widget.set_value(display_value)
            field_widget.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])
            self.widgets[key] = field_widget
            self.field_containers[key] = container
            
            self._update_single_field_visibility(key, field)

    def _create_aut_param_section(self, config):
        param_file = config.get("_aut_parameter_file", "")
        if not param_file:
            return

        project_root = self._get_project_root()
        if project_root and not os.path.isabs(param_file):
            param_file = os.path.join(project_root, param_file)

        if not os.path.exists(param_file):
            return

        try:
            with open(param_file, "r", encoding="utf-8") as f:
                aut_params = json.load(f)
        except Exception:
            return

        if not isinstance(aut_params, dict) or not aut_params:
            return

        self._create_section_title("加密参数")
        aut_fields_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        aut_fields_frame.pack(fill="x")

        for node_id, node_data in aut_params.items():
            if not isinstance(node_data, dict):
                continue

            node_name = node_data.get("nodeName", node_id)
            params = node_data.get("params", {})

            if not params:
                continue

            group_label = node_name

            group_frame = ctk.CTkFrame(aut_fields_frame, fg_color="transparent")
            group_frame.pack(fill="x", pady=(Theme.DIMENSIONS['spacing_xs'], 0))

            group_title = ctk.CTkLabel(
                group_frame,
                text=group_label,
                font=Theme.get_font('sm'),
                text_color=Theme.COLORS['text_secondary'],
                anchor="w"
            )
            group_title.pack(fill="x", padx=Theme.DIMENSIONS['spacing_sm'])

            for param_key, param_def in params.items():
                if not isinstance(param_def, dict):
                    continue

                field_key = f"_aut_param_{node_id}__{param_key}"
                field_def = {
                    "key": field_key,
                    "label": param_def.get("label", param_key),
                    "type": param_def.get("type", "text"),
                    "default": param_def.get("default"),
                }
                if param_def.get("options"):
                    field_def["options"] = param_def["options"]
                if param_def.get("min") is not None:
                    field_def["min"] = param_def["min"]
                if param_def.get("max") is not None:
                    field_def["max"] = param_def["max"]
                if param_def.get("required"):
                    field_def["label"] = field_def["label"] + " *"

                param_default = param_def.get("default")
                if isinstance(param_default, str) and param_default.startswith('['):
                    try:
                        param_default = json.loads(param_default)
                    except (json.JSONDecodeError, ValueError):
                        pass

                set_marker = f"_aut_param_set_{node_id}__{param_key}"
                if set_marker in config:
                    value = config.get(field_key, param_default)
                else:
                    value = param_default

                if isinstance(value, str) and value.startswith('['):
                    try:
                        value = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        pass

                self._create_field(field_def, value, group_frame)

    def _on_field_change(self, key: str, value: Any):
        if self._is_loading:
            return

        if key in self._hidden_values:
            self._hidden_values[key] = value

        if self.on_change and self.current_node_id:
            self.on_change(self.current_node_id, key, value)

            if key.startswith("_aut_param_"):
                param_name = key[len("_aut_param_"):]
                set_marker = f"_aut_param_set_{param_name}"
                self.on_change(self.current_node_id, set_marker, True)

        self._update_dependent_fields_visibility(key)
    
    def _update_widget_value(self, key: str, value: Any):
        if key in self.widgets:
            widget = self.widgets[key]
            if hasattr(widget, 'set_value'):
                widget.set_value(value)
    
    def _check_hide_condition(self, condition: Dict[str, Any]) -> bool:
        depend_field = condition.get("field")
        hide_value = condition.get("value")
        if not depend_field or depend_field not in self.widgets:
            return False
        depend_widget = self.widgets.get(depend_field)
        if not depend_widget:
            return False
        current_value = depend_widget.get_value()
        if isinstance(hide_value, list):
            return current_value in hide_value
        else:
            return current_value == hide_value

    def _update_single_field_visibility(self, key: str, field: Dict[str, Any]):
        hide_if = field.get("hide_if")
        if not hide_if:
            return

        if isinstance(hide_if, list):
            should_hide = any(self._check_hide_condition(cond) for cond in hide_if)
        else:
            should_hide = self._check_hide_condition(hide_if)

        widget = self.widgets.get(key)
        container = self.field_containers.get(key)

        if widget and container:
            if should_hide:
                widget.pack_forget()
            else:
                next_widget = self._find_next_visible_widget(key, container)
                if next_widget:
                    widget.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'], before=next_widget)
                else:
                    widget.pack(fill="x", pady=Theme.DIMENSIONS['spacing_xs'])
    
    def _find_next_visible_widget(self, current_key: str, container):
        schema_keys = list(self.field_schemas.keys())
        try:
            current_index = schema_keys.index(current_key)
        except ValueError:
            return None
        
        for i in range(current_index + 1, len(schema_keys)):
            next_key = schema_keys[i]
            next_container = self.field_containers.get(next_key)
            if next_container != container:
                continue
            next_widget = self.widgets.get(next_key)
            if next_widget and next_widget.winfo_ismapped():
                return next_widget
        
        return None
    
    def _update_dependent_fields_visibility(self, changed_key: str):
        for key, field in self.field_schemas.items():
            hide_if = field.get("hide_if")
            if not hide_if:
                continue

            if isinstance(hide_if, list):
                depend_fields = [cond.get("field") for cond in hide_if]
            else:
                depend_fields = [hide_if.get("field")]
            if changed_key not in depend_fields:
                continue

            self._update_single_field_visibility(key, field)
        
        for key, field in self.field_schemas.items():
            hide_if = field.get("hide_if")
            if not hide_if:
                continue
            
            self._update_single_field_visibility(key, field)
