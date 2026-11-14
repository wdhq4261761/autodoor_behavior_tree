"""预检接入 Headless / CLI 的集成测试

预检必须在反序列化之前拦截明显不可运行的树，且可以被显式跳过。
测试中不启动真实引擎，避免真实鼠标键盘输入。
"""
import argparse
import os
import sys
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bt_core.headless import HeadlessRunner  # noqa: E402


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
    assert code != 0
    captured = capsys.readouterr()
    assert "预检未通过" in captured.out
    assert "模板图片不存在" in captured.out


def test_headless_preflight_runs_after_plugin_loading(tmp_path):
    """预检发生在插件加载之后（插件节点不应被误报未知类型）"""
    tree = _write_tree_with_missing_template(tmp_path)
    runner = HeadlessRunner(enable_plugins=False)
    calls = []

    def fake_load_plugins(settings):
        calls.append("plugins")

    with patch.object(runner, "_load_plugins", side_effect=fake_load_plugins), \
         patch.object(runner, "_start_service_layer"), \
         patch.object(runner, "_stop_service_layer"):
        runner.run(str(tree), project_root=str(tmp_path), check_preflight=True)
    assert calls == ["plugins"]


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
    import pytest

    with patch("bt_core.headless.HeadlessRunner") as mock_runner_cls, \
         patch("config.settings_manager.get_settings_manager"):
        mock_runner = MagicMock()
        mock_runner.run.return_value = 2
        mock_runner_cls.return_value = mock_runner

        from bt_cli.commands.run import cmd_run
        with pytest.raises(SystemExit) as exc_info:
            cmd_run(_make_run_args(tmp_path))
        assert exc_info.value.code == 2
