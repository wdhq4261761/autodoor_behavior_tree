"""资源路径工具测试

验证 get_resource_path 在开发环境下能正确解析 prompt 文件路径，
以及 get_cli_path 能正确找到 cli.py。
"""
import os
import pytest


def test_get_resource_path_finds_prompt_files():
    """开发环境下 get_resource_path 应能找到所有 prompt .md 文件"""
    from bt_cli.ai.resource_path import get_resource_path

    ref_file = os.path.join(os.path.dirname(__file__), '..', 'bt_cli', 'ai', 'intent_analyzer.py')
    ref_file = os.path.abspath(ref_file)

    # 每个 AI 模块的 prompt 文件
    prompt_files = [
        ("intent_analyzer.py", "intent_analysis.md"),
        ("node_selector.py", "node_selection.md"),
        ("vlm_analyzer.py", "vlm_analysis.md"),
        ("iteration_engine.py", "failure_analysis.md"),
    ]

    for module_name, prompt_name in prompt_files:
        module_path = os.path.join(os.path.dirname(ref_file), module_name)
        path = get_resource_path(module_path, "prompts", prompt_name)
        assert os.path.exists(path), f"Prompt file not found via get_resource_path: {path}"


def test_get_resource_path_nonexistent_returns_path():
    """文件不存在时仍返回拼接的路径（让调用方抛 FileNotFoundError）"""
    from bt_cli.ai.resource_path import get_resource_path

    ref_file = os.path.abspath(__file__)
    path = get_resource_path(ref_file, "prompts", "nonexistent.md")
    # 至少返回了一个字符串路径
    assert isinstance(path, str)
    assert path.endswith("nonexistent.md")


def test_get_cli_path_finds_cli_py():
    """开发环境下 get_cli_path 应能找到项目根的 cli.py"""
    from bt_cli.ai.resource_path import get_cli_path

    path = get_cli_path()
    assert os.path.exists(path), f"cli.py not found via get_cli_path: {path}"
    assert path.endswith("cli.py")


def test_is_pyinstaller_dev_environment_false():
    """开发环境下 _is_pyinstaller 应为 False"""
    from bt_cli.ai.resource_path import _is_pyinstaller
    assert _is_pyinstaller() is False


def test_ai_modules_load_prompt_files():
    """所有 AI 模块的 PROMPT_FILE 应指向实际存在的文件"""
    from bt_cli.ai.intent_analyzer import IntentAnalyzer
    from bt_cli.ai.node_selector import NodeSelector
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer
    from bt_cli.ai.iteration_engine import IterationEngine

    classes = [
        IntentAnalyzer,
        NodeSelector,
        VLMAnalyzer,
        IterationEngine,
    ]

    for cls in classes:
        path = cls.PROMPT_FILE
        assert os.path.exists(path), f"{cls.__name__}.PROMPT_FILE does not exist: {path}"
        assert path.endswith('.md')
