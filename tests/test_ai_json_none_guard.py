"""AI 模块 json.loads NoneType 防御测试

验证所有 AI 模块在 LLM 返回 "null" / 空字符串 / 非 dict JSON 时，
抛出明确的错误异常而非 AttributeError: 'NoneType' object has no attribute 'get'。
"""
import json
import pytest
from unittest.mock import MagicMock, patch


def test_vlm_analyzer_null_response_raises_error():
    """VLM 返回 JSON null 时应抛 VLMAnalysisError 而非 AttributeError"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer, VLMAnalysisError

    analyzer = VLMAnalyzer()
    analyzer._vlm = MagicMock()
    analyzer._vlm.chat_with_image.return_value = {"content": "null"}

    with patch.object(analyzer, "_encode_image", return_value=("image/png", "base64fake")):
        with pytest.raises(VLMAnalysisError, match="应为对象"):
            analyzer.analyze("fake_path", {"nodes": [{"id": "n1", "empty_params": ["region"]}]}, "test")


def test_vlm_analyzer_array_response_raises_error():
    """VLM 返回 JSON 数组时应抛 VLMAnalysisError 而非 AttributeError"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer, VLMAnalysisError

    analyzer = VLMAnalyzer()
    analyzer._vlm = MagicMock()
    analyzer._vlm.chat_with_image.return_value = {"content": "[1, 2, 3]"}

    with patch.object(analyzer, "_encode_image", return_value=("image/png", "base64fake")):
        with pytest.raises(VLMAnalysisError, match="应为对象"):
            analyzer.analyze("fake_path", {"nodes": [{"id": "n1", "empty_params": ["region"]}]}, "test")


def test_intent_analyzer_null_response_raises_error():
    """意图分析返回 JSON null 时应抛 IntentAnalysisError 而非 AttributeError"""
    from bt_cli.ai.intent_analyzer import IntentAnalyzer, IntentAnalysisError

    analyzer = IntentAnalyzer()
    analyzer._llm = MagicMock()
    analyzer._llm.chat.return_value = {"content": "null"}

    with pytest.raises(IntentAnalysisError, match="应为对象"):
        analyzer.analyze("do something")


def test_node_selector_null_response_raises_error():
    """节点选型返回 JSON null 时应抛 NodeSelectionError 而非 AttributeError"""
    from bt_cli.ai.node_selector import NodeSelector, NodeSelectionError

    selector = NodeSelector()
    selector._llm = MagicMock()
    selector._llm.chat.return_value = {"content": "null"}

    plan = {"task_summary": "test", "loop": {"enabled": True}, "phases": [{"phase": "act", "action": "click"}], "window": {}}
    with pytest.raises(NodeSelectionError, match="应为对象"):
        selector.select(plan)


def test_iteration_engine_null_response_raises_error():
    """试运行分析返回 JSON null 时应抛 IterationError 而非 AttributeError"""
    from bt_cli.ai.iteration_engine import IterationEngine, IterationError

    engine = IterationEngine()
    engine._llm = MagicMock()
    engine._llm.chat.return_value = {"content": "null"}

    report = {"success": False, "logs": ["error"]}
    tree = {"nodes": {"n1": {"type": "StartNode", "config": {}, "children": []}}, "root_node": "n1"}

    with pytest.raises(IterationError, match="应为对象"):
        engine.analyze_failure(report, tree, "test")


def test_vlm_analyzer_valid_dict_works():
    """VLM 返回合法 dict 时正常返回建议列表"""
    from bt_cli.ai.vlm_analyzer import VLMAnalyzer

    analyzer = VLMAnalyzer()
    analyzer._vlm = MagicMock()
    analyzer._vlm.chat_with_image.return_value = {
        "content": json.dumps({"suggestions": [{"node_id": "n1", "param": "region", "suggested_value": [0, 0, 100, 100], "confidence": 0.9}]})
    }

    # patch _encode_image to avoid file read
    with patch.object(analyzer, "_encode_image", return_value=("image/png", "base64fake")):
        suggestions = analyzer.analyze("fake_path", {"nodes": [{"id": "n1", "empty_params": ["region"]}]}, "test")

    assert len(suggestions) == 1
    assert suggestions[0]["node_id"] == "n1"
