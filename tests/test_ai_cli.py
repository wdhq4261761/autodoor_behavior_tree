# tests/test_ai_cli.py
"""AI CLI 命令测试

subprocess 集成测试。bt_utils/__init__.py eager-import OCRManager /
ScriptRecorder 等模块，它们依赖 rapidocr / pynput / pyautogui 等重型
三方库。subprocess 无法使用 conftest 中的 mock，因此通过 PYTHONPATH +
sitecustomize.py 向子进程注入 mock。

配置隔离：通过设置 APPDATA 环境变量指向临时目录，确保子进程读取的是
默认配置（ai.llm.api_key 为空），不受本机已有配置影响。
"""
import os
import sys
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
    - 设置 APPDATA 指向临时目录，隔离配置（确保 ai.llm.api_key 为空）。
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


def test_ai_nodes_command(cli_env):
    """测试 ai nodes 命令输出节点规格"""
    result = _run_cli(["ai", "nodes"], cli_env)
    assert result.returncode == 0
    assert "StartNode" in result.stdout
    assert "SequenceNode" in result.stdout
    assert "MouseClickNode" in result.stdout
    assert "OCRConditionNode" in result.stdout


def test_ai_command_help(cli_env):
    """测试 ai 命令帮助"""
    result = _run_cli(["ai", "--help"], cli_env, timeout=10)
    assert result.returncode == 0
    assert "plan" in result.stdout
    assert "select" in result.stdout
    assert "nodes" in result.stdout


def test_ai_plan_command_no_api_key(cli_env):
    """测试 ai plan 命令在未配置 API Key 时的错误提示"""
    result = _run_cli(["ai", "plan", "测试描述"], cli_env)
    # 未配置 API Key 应返回 EXIT_CONFIG_ERROR (2)
    assert result.returncode == 2
    assert "API Key" in result.stderr or "API Key" in result.stdout


def test_ai_select_file_not_found(cli_env):
    """测试 ai select 命令在未配置 API Key 时的错误提示（API Key 检查先于文件检查）"""
    result = _run_cli(["ai", "select", "nonexistent.json"], cli_env)
    # 未配置 API Key 时应返回 EXIT_CONFIG_ERROR (2)，先于文件检查
    assert result.returncode == 2
    assert "API Key" in result.stderr or "API Key" in result.stdout


def test_ai_unknown_action(cli_env):
    """测试 ai 未知操作时的错误提示"""
    result = _run_cli(["ai", "unknown_action"], cli_env, timeout=10)
    assert result.returncode != 0
