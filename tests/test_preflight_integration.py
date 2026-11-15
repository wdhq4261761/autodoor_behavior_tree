"""预检接入 Headless / CLI / GUI 的集成测试

预检必须在反序列化之前拦截明显不可运行的树，且可以被显式跳过。
测试中不启动真实引擎，也不初始化 Tk 窗口，避免真实鼠标键盘输入与弹窗。
"""
import argparse
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bt_core.headless import HeadlessRunner  # noqa: E402
from bt_core.preflight import PreflightReport  # noqa: E402

MISSING_TEMPLATE_TREE = {
    "root_node": "start",
    "nodes": {
        "start": {"type": "StartNode", "config": {}},
        "img": {"type": "ImageConditionNode",
                "config": {"template_path": "./images/no.png"}},
    },
    "connections": [{"parent_id": "start", "child_id": "img"}],
}


def _write_tree_with_missing_template(tmp_path):
    """写一棵根节点有效、但图片模板资源不存在的树"""
    tree = tmp_path / "t.json"
    tree.write_text(
        '{"root_node":"start","nodes":{"start":{"type":"StartNode","config":{}},'
        '"img":{"type":"ImageConditionNode","config":{"template_path":"./images/no.png"}}},'
        '"connections":[{"parent_id":"start","child_id":"img"}]}',
        encoding="utf-8",
    )
    return tree


def _stub_engine():
    """构造一个不启动线程、状态立即为 stopped 的引擎桩"""
    engine = MagicMock()
    engine.get_status.return_value = {"running": False}
    engine._thread.is_alive.return_value = False
    return engine


def test_headless_preflight_reports_missing_resource(tmp_path, capsys):
    tree = _write_tree_with_missing_template(tmp_path)
    runner = HeadlessRunner(enable_plugins=False)
    with patch.object(runner, "_load_plugins"), \
         patch.object(runner, "_start_service_layer"), \
         patch.object(runner, "_stop_service_layer"):
        code = runner.run(str(tree), project_root=str(tmp_path), check_preflight=True)
    assert code == 2
    captured = capsys.readouterr()
    assert "预检未通过" in captured.out
    assert "模板图片不存在" in captured.out


def test_headless_preflight_runs_after_plugin_loading(tmp_path):
    """预检发生在插件加载之后（插件节点不应被误报未知类型）"""
    tree = _write_tree_with_missing_template(tmp_path)
    runner = HeadlessRunner(enable_plugins=False)
    order = []

    def fake_load_plugins(settings):
        order.append("plugins")

    def fake_validate(tree_data, project_root=None):
        order.append("preflight")
        report = PreflightReport()
        report.add("error", "TEST_STOP", "用于在反序列化前终止")
        return report

    with patch.object(runner, "_load_plugins", side_effect=fake_load_plugins), \
         patch.object(runner, "_start_service_layer"), \
         patch.object(runner, "_stop_service_layer"), \
         patch("bt_core.preflight.validate_tree_data", side_effect=fake_validate):
        code = runner.run(str(tree), project_root=str(tmp_path), check_preflight=True)
    assert order == ["plugins", "preflight"]
    assert code == 2


def test_headless_skips_preflight_when_disabled(tmp_path, capsys):
    tree = _write_tree_with_missing_template(tmp_path)
    runner = HeadlessRunner(enable_plugins=False)
    engine = _stub_engine()
    with patch.object(runner, "_load_plugins"), \
         patch.object(runner, "_start_service_layer"), \
         patch.object(runner, "_stop_service_layer"), \
         patch("bt_core.serializer.Serializer.deserialize", return_value=None) as mock_deserialize, \
         patch("bt_core.engine.BehaviorTreeEngine", return_value=engine):
        code = runner.run(str(tree), project_root=str(tmp_path), check_preflight=False)
    mock_deserialize.assert_called_once()
    captured = capsys.readouterr()
    assert "预检未通过" not in captured.out
    assert code == 0


def _make_run_args(tmp_path, **kwargs):
    tree = tmp_path / "tree.json"
    tree.write_text('{"name": "test"}', encoding="utf-8")
    defaults = dict(
        command="run",
        tree_file=str(tree),
        headless=True,
        project=None,
        bus=False,
        rest=False,
        rest_host="127.0.0.1",
        rest_port=8080,
        ws=False,
        ws_host="127.0.0.1",
        ws_port=8765,
        plugins=False,
        no_preflight=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_cmd_run_passes_preflight_flag(tmp_path):
    """cmd_run 把 --no-preflight 取反后传给 runner.run"""
    with patch("bt_core.headless.HeadlessRunner") as mock_runner_cls, \
         patch("config.settings_manager.get_settings_manager"):
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        mock_runner_cls.return_value = mock_runner

        from bt_cli.commands.run import cmd_run
        cmd_run(_make_run_args(tmp_path, no_preflight=True))
        mock_runner.run.assert_called_once_with(
            str(tmp_path / "tree.json"), None, check_preflight=False
        )

        mock_runner.run.reset_mock()
        cmd_run(_make_run_args(tmp_path, no_preflight=False))
        mock_runner.run.assert_called_once_with(
            str(tmp_path / "tree.json"), None, check_preflight=True
        )


def test_cmd_run_propagates_nonzero_exit_code(tmp_path):
    """runner 返回非 0 时 cmd_run 以该退出码结束进程"""
    with patch("bt_core.headless.HeadlessRunner") as mock_runner_cls, \
         patch("config.settings_manager.get_settings_manager"):
        mock_runner = MagicMock()
        mock_runner.run.return_value = 2
        mock_runner_cls.return_value = mock_runner

        from bt_cli.commands.run import cmd_run
        with pytest.raises(SystemExit) as exc_info:
            cmd_run(_make_run_args(tmp_path))
        assert exc_info.value.code == 2


def _fake_editor_self(tree_data, project_root):
    """构造 _handle_tab_run 需要的假 self（不创建 Tk 窗口）"""
    fake_self = MagicMock()
    tab = MagicMock()
    tab.is_running = False
    tab.project_root = str(project_root)
    tab.canvas.get_tree_data.return_value = tree_data
    fake_self.tab_manager.get_tab.return_value = tab
    return fake_self


def test_gui_preflight_error_prompts_and_aborts(tmp_path, monkeypatch):
    """GUI 预检发现错误时弹确认框，用户选否即中止运行"""
    from bt_gui.bt_editor import editor as editor_module
    from bt_gui.bt_editor.editor import BehaviorTreeEditor

    askyesno = MagicMock(return_value=False)
    monkeypatch.setattr(editor_module.messagebox, "askyesno", askyesno)

    fake_self = _fake_editor_self(MISSING_TEMPLATE_TREE, tmp_path)
    result = BehaviorTreeEditor._handle_tab_run(fake_self, "tab1")

    assert result is False
    askyesno.assert_called_once()


def test_gui_preflight_warning_only_does_not_prompt(tmp_path, monkeypatch):
    """仅有警告时不弹窗，只记录日志并继续运行流程"""
    from bt_gui.bt_editor import editor as editor_module
    from bt_gui.bt_editor.editor import BehaviorTreeEditor

    tree_data = {
        "root_node": "start",
        "nodes": {
            "start": {"type": "StartNode", "config": {}},
            "orphan": {"type": "StartNode", "config": {}},
        },
        "connections": [],
    }

    askyesno = MagicMock(return_value=False)
    showwarning = MagicMock()
    debug_print = MagicMock()
    monkeypatch.setattr(editor_module.messagebox, "askyesno", askyesno)
    monkeypatch.setattr(editor_module.messagebox, "showwarning", showwarning)
    monkeypatch.setattr(editor_module.LogManager, "debug_print", debug_print)

    fake_self = _fake_editor_self(tree_data, tmp_path)
    with patch("bt_core.serializer.Serializer.deserialize", return_value=(None, None)):
        result = BehaviorTreeEditor._handle_tab_run(fake_self, "tab1")

    askyesno.assert_not_called()
    debug_print.assert_called_once()
    showwarning.assert_called_once()
    assert result is False
