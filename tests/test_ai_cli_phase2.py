# tests/test_ai_cli_phase2.py
"""AI CLI 阶段②命令测试 (scan/generate/validate)

subprocess 集成测试。bt_utils/__init__.py eager-import OCRManager /
ScriptRecorder 等模块，它们依赖 rapidocr / pynput / pyautogui 等重型
三方库。subprocess 无法使用 conftest 中的 mock，因此通过 PYTHONPATH +
sitecustomize.py 向子进程注入 mock。

配置隔离：通过设置 APPDATA 环境变量指向临时目录，确保子进程读取的是
默认配置，不受本机已有配置影响。
"""
import os
import sys
import json
import subprocess
import textwrap

import pytest

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 子进程中需要 mock 的缺失可选依赖
_MOCK_DEPS = [
    "rapidocr",
    "pynput",
    "pynput.mouse",
    "pynput.keyboard",
    "pyautogui",
    "win32api",
    "win32con",
    "win32gui",
    "win32process",
    "win32clipboard",
    "win32event",
    "pyperclip",
]

# sitecustomize.py 代码 — 子进程启动时自动执行，注入 mock
_SITECUSTOMIZE_CODE = textwrap.dedent(f"""\
    import sys as _sys
    from unittest.mock import MagicMock as _MagicMock
    for _m in {_MOCK_DEPS}:
        if _m not in _sys.modules:
            _sys.modules[_m] = _MagicMock()
""")


@pytest.fixture
def cli_env(tmp_path):
    """提供带有 mock 依赖和隔离配置的子进程环境

    - 在 tmp_path 中创建 sitecustomize.py，通过 PYTHONPATH 让子进程
      启动时自动 mock 缺失的可选依赖。
    - 设置 APPDATA 指向临时目录，隔离配置。
    """
    (tmp_path / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_CODE, encoding="utf-8"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(tmp_path) + os.pathsep + env.get("PYTHONPATH", "")
    )
    env["APPDATA"] = str(tmp_path / "appdata")
    return env


def _run_cli(args, env, timeout=30):
    """运行 CLI 子进程"""
    return subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "cli.py")] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=PROJECT_ROOT, timeout=timeout, env=env,
    )


# ------------------------------------------------------------------
# 测试数据
# ------------------------------------------------------------------

# 有效的行为树 tree.json（根节点为 StartNode，能通过 Serializer 反序列化）
_VALID_TREE = {
    "version": "2.1",
    "format_type": "behavior_tree",
    "root_node": "node_start",
    "nodes": {
        "node_start": {
            "id": "node_start", "type": "StartNode",
            "name": "开始", "enabled": True, "config": {},
            "position": {"x": 400, "y": 50}, "children": ["node_delay"],
        },
        "node_delay": {
            "id": "node_delay", "type": "DelayNode",
            "name": "延时", "enabled": True,
            "config": {"duration_ms": 1000},
            "position": {"x": 400, "y": 150}, "children": [],
        },
    },
    "connections": [{"parent_id": "node_start", "child_id": "node_delay"}],
}

# 无效的行为树 tree.json（根节点不是 StartNode）
_INVALID_TREE = {
    "version": "2.1",
    "format_type": "behavior_tree",
    "root_node": "node_delay",
    "nodes": {
        "node_delay": {
            "id": "node_delay", "type": "DelayNode",
            "name": "延时", "enabled": True,
            "config": {"duration_ms": 1000},
            "position": {"x": 400, "y": 50}, "children": [],
        },
    },
    "connections": [],
}

# 有效的节点结构 structure.json（可被 TreeGenerator 处理）
_VALID_STRUCTURE = {
    "nodes": [
        {"id": "node_start", "type": "StartNode",
         "config": {"bind_window": False}, "children": ["node_delay"]},
        {"id": "node_delay", "type": "DelayNode",
         "config": {"duration_ms": 1000}, "children": []},
    ],
}


# ------------------------------------------------------------------
# 测试用例
# ------------------------------------------------------------------

def test_ai_validate_valid_tree(cli_env, tmp_path):
    """测试 validate 命令校验有效行为树"""
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(_VALID_TREE, ensure_ascii=False), encoding="utf-8"
    )

    result = _run_cli(["ai", "validate", str(tree_file)], cli_env)

    assert result.returncode == 0
    assert "校验通过" in result.stdout


def test_ai_validate_invalid_tree(cli_env, tmp_path):
    """测试 validate 命令检测无效行为树（根节点不是 StartNode）"""
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(
        json.dumps(_INVALID_TREE, ensure_ascii=False), encoding="utf-8"
    )

    result = _run_cli(["ai", "validate", str(tree_file)], cli_env)

    assert result.returncode != 0
    assert "StartNode" in result.stdout or "StartNode" in result.stderr


def test_ai_generate_from_structure(cli_env, tmp_path):
    """测试 generate 命令从结构生成 tree.json"""
    structure_file = tmp_path / "structure.json"
    structure_file.write_text(
        json.dumps(_VALID_STRUCTURE, ensure_ascii=False), encoding="utf-8"
    )

    result = _run_cli(["ai", "generate", str(structure_file)], cli_env)

    assert result.returncode == 0
    assert "tree.json" in result.stdout
    assert "校验通过" in result.stdout


# ------------------------------------------------------------------
# 异常路径测试
# ------------------------------------------------------------------

def test_ai_scan_no_vlm_api_key(cli_env):
    """测试 ai scan 命令在未配置 VLM API Key 时的错误提示"""
    result = _run_cli(["ai", "scan", "nonexistent.json"], cli_env)
    assert result.returncode == 2  # EXIT_CONFIG_ERROR
    assert "VLM API Key" in result.stderr or "VLM API Key" in result.stdout


def test_ai_validate_file_not_found(cli_env):
    """测试 validate 命令文件不存在时的错误提示"""
    result = _run_cli(["ai", "validate", "nonexistent.json"], cli_env)
    assert result.returncode == 2  # EXIT_CONFIG_ERROR
    assert "文件不存在" in result.stderr or "文件不存在" in result.stdout


def test_ai_generate_file_not_found(cli_env):
    """测试 generate 命令文件不存在时的错误提示"""
    result = _run_cli(["ai", "generate", "nonexistent.json"], cli_env)
    assert result.returncode == 2  # EXIT_CONFIG_ERROR
    assert "文件不存在" in result.stderr or "文件不存在" in result.stdout


def test_ai_validate_invalid_json(cli_env, tmp_path):
    """测试 validate 命令 JSON 格式错误时的错误提示"""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid json", encoding="utf-8")
    result = _run_cli(["ai", "validate", str(bad_json)], cli_env)
    assert result.returncode == 2  # EXIT_CONFIG_ERROR
    assert "解析失败" in result.stderr or "解析失败" in result.stdout
