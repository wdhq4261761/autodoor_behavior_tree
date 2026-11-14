# tests/test_cli_commands.py
"""CLI 命令测试 — 使用 argparse Namespace 模拟命令调用"""
import os
import sys
import json
import argparse
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest


def _make_args(**kwargs):
    """构造 argparse.Namespace"""
    defaults = {
        "command": None,
        "tree_file": None,
        "headless": False,
        "project": None,
        "bus": False,
        "rest": False,
        "rest_host": "127.0.0.1",
        "rest_port": 8080,
        "ws": False,
        "ws_host": "127.0.0.1",
        "ws_port": 8765,
        "plugins": False,
        "no_preflight": False,
        "tree_id": None,
        "all": False,
        "force": False,
        "schedule_action": None,
        "cron": None,
        "interval": None,
        "once": None,
        "name": "",
        "start": False,
        "stop": False,
        "restart": False,
        "status": False,
        "foreground": False,
        "target": None,
        "action": None,
        "token": None,
        "json": False,
        "plugin_action": None,
        "path": None,
        "config_action": None,
        "key": None,
        "value": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ── run 命令 ──

def test_run_missing_file(capsys):
    """run 不存在的文件应退出码 3"""
    from bt_cli.commands.run import cmd_run
    args = _make_args(command="run", tree_file="nonexistent.json")
    with pytest.raises(SystemExit) as exc_info:
        cmd_run(args)
    assert exc_info.value.code == 3


def test_run_headless_with_bus(tmp_path):
    """headless 模式带 --bus --rest --ws --plugins 应设置配置并启动 runner"""
    tree_file = tmp_path / "tree.json"
    tree_file.write_text('{"name": "test"}', encoding="utf-8")

    # patch 源模块（命令在函数内导入）
    with patch("bt_core.headless.HeadlessRunner") as mock_runner_cls, \
         patch("config.settings_manager.get_settings_manager") as mock_settings_cls:
        mock_settings = MagicMock()
        mock_settings_cls.return_value = mock_settings
        mock_runner = MagicMock()
        mock_runner.run.return_value = 0
        mock_runner_cls.return_value = mock_runner

        from bt_cli.commands.run import cmd_run
        args = _make_args(
            command="run", tree_file=str(tree_file),
            headless=True, bus=True, rest=True, ws=True, plugins=True
        )
        cmd_run(args)

        # 验证配置被设置
        assert mock_settings.set.call_count >= 6
        # 验证 runner.run 被调用
        mock_runner.run.assert_called_once_with(str(tree_file), None, check_preflight=True)


# ── config 命令 ──

def test_config_get_existing_key(capsys):
    """config get 已存在的 key"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_settings.get.return_value = True
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="get", key="message_bus.enabled")
        cmd_config(args)
        mock_settings.get.assert_called_once_with("message_bus.enabled")


def test_config_get_missing_key(capsys):
    """config get 不存在的 key 应退出码 1"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_settings.get.return_value = None
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="get", key="nonexistent")
        with pytest.raises(SystemExit) as exc_info:
            cmd_config(args)
        assert exc_info.value.code == 1


def test_config_set_boolean():
    """config set 布尔值"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="set", key="flag", value="true")
        cmd_config(args)
        mock_settings.set.assert_called_once_with("flag", True)
        mock_settings.save_settings.assert_called_once()


def test_config_set_number():
    """config set 数字"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="set", key="n", value="42")
        cmd_config(args)
        mock_settings.set.assert_called_once_with("n", 42)


def test_config_set_string():
    """config set 字符串"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="set", key="s", value="hello")
        cmd_config(args)
        mock_settings.set.assert_called_once_with("s", "hello")


def test_config_list():
    """config list 列出所有配置"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_settings.get_all_settings.return_value = {"a": 1, "b": "two"}
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="list")
        cmd_config(args)
        mock_settings.get_all_settings.assert_called_once()


def test_config_path():
    """config path 显示配置文件路径"""
    with patch("config.settings_manager.get_settings_manager") as mock_cls:
        mock_settings = MagicMock()
        mock_settings.config_file = "/path/to/settings.json"
        mock_cls.return_value = mock_settings

        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action="path")
        cmd_config(args)


def test_config_no_action(capsys):
    """config 无操作应退出码 1"""
    with patch("config.settings_manager.get_settings_manager"):
        from bt_cli.commands.config import cmd_config
        args = _make_args(command="config", config_action=None)
        with pytest.raises(SystemExit) as exc_info:
            cmd_config(args)
        assert exc_info.value.code == 1


# ── status 命令 ──

def test_status_no_daemon(capsys, tmp_path, monkeypatch):
    """无守护进程状态文件时提示"""
    # mock expanduser 让状态文件指向临时目录
    def fake_expanduser(p):
        if ".autodoor_bt" in p:
            return str(tmp_path / "fake_home")
        return p
    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)

    from bt_cli.commands.status import cmd_status
    args = _make_args(command="status")
    cmd_status(args)
    captured = capsys.readouterr()
    assert "未检测到" in captured.out


def test_status_with_daemon(capsys, tmp_path, monkeypatch):
    """有守护进程状态文件时显示状态"""
    # 创建假的 home 目录和状态文件
    fake_home = tmp_path / "fake_home"
    fake_autodoor = fake_home / ".autodoor_bt"
    fake_autodoor.mkdir(parents=True)
    status_file = fake_autodoor / "daemon_status.json"
    status_data = {
        "pid": 12345,
        "start_time": "2026-07-28T10:00:00",
        "trees": {"tree1": {"status": "running"}},
    }
    status_file.write_text(json.dumps(status_data), encoding="utf-8")

    def fake_expanduser(p):
        if "~" in p or ".autodoor_bt" in p:
            return str(fake_home / p.replace("~", "").lstrip("/\\"))
        return p
    monkeypatch.setattr(os.path, "expanduser", fake_expanduser)

    from bt_cli.commands.status import cmd_status
    args = _make_args(command="status")
    cmd_status(args)
    captured = capsys.readouterr()
    assert "12345" in captured.out or "tree1" in captured.out


# ── plugin 命令 ──

def test_plugin_list(capsys):
    """plugin list 列出插件"""
    from bt_cli.commands.plugin import cmd_plugin
    args = _make_args(command="plugin", plugin_action="list")
    cmd_plugin(args)
    captured = capsys.readouterr()
    # 内置 example 插件应被列出
    assert "示例插件" in captured.out or "example" in captured.out


def test_plugin_no_action(capsys):
    """plugin 无操作应退出码 1"""
    from bt_cli.commands.plugin import cmd_plugin
    args = _make_args(command="plugin", plugin_action=None)
    with pytest.raises(SystemExit) as exc_info:
        cmd_plugin(args)
    assert exc_info.value.code == 1


def test_plugin_info_not_found(capsys):
    """plugin info 不存在的插件应退出码 1"""
    from bt_cli.commands.plugin import cmd_plugin
    args = _make_args(command="plugin", plugin_action="info", name="nonexistent_plugin")
    with pytest.raises(SystemExit) as exc_info:
        cmd_plugin(args)
    assert exc_info.value.code == 1


def test_plugin_info_existing(capsys):
    """plugin info 已存在的插件"""
    from bt_cli.commands.plugin import cmd_plugin
    args = _make_args(command="plugin", plugin_action="info", name="example")
    cmd_plugin(args)
    captured = capsys.readouterr()
    assert "示例插件" in captured.out
    assert "example" in captured.out


# ── schedule 命令 ──

def test_schedule_no_action(capsys):
    """schedule 无操作应退出码 1"""
    from bt_cli.commands.schedule import cmd_schedule
    args = _make_args(command="schedule", schedule_action=None)
    with pytest.raises(SystemExit) as exc_info:
        cmd_schedule(args)
    assert exc_info.value.code == 1


def test_schedule_add_missing_trigger(capsys):
    """schedule add 未指定触发方式应退出码 1"""
    from bt_cli.commands.schedule import cmd_schedule
    args = _make_args(
        command="schedule", schedule_action="add",
        tree_file="tree.json", name="t1"
    )
    with pytest.raises(SystemExit) as exc_info:
        cmd_schedule(args)
    assert exc_info.value.code == 1


def test_schedule_add_with_cron(tmp_path, monkeypatch):
    """schedule add 成功添加 cron 任务"""
    from bt_cli.scheduler import Scheduler
    monkeypatch.setattr(Scheduler, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(Scheduler, "DATA_DIR", str(tmp_path))
    # 创建临时行为树文件（add_task 现在会验证文件存在）
    tree_file = tmp_path / "tree.json"
    tree_file.write_text("{}")

    from bt_cli.commands.schedule import cmd_schedule
    args = _make_args(
        command="schedule", schedule_action="add",
        tree_file=str(tree_file), name="定时任务",
        cron="0 * * * *", headless=True
    )
    cmd_schedule(args)
    # 验证任务已添加
    s = Scheduler()
    tasks = s.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].name == "定时任务"
    assert tasks[0].cron == "0 * * * *"


def test_schedule_list_empty(capsys, tmp_path, monkeypatch):
    """schedule list 空列表"""
    from bt_cli.scheduler import Scheduler
    monkeypatch.setattr(Scheduler, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(Scheduler, "DATA_DIR", str(tmp_path))

    from bt_cli.commands.schedule import cmd_schedule
    args = _make_args(command="schedule", schedule_action="list")
    cmd_schedule(args)
    captured = capsys.readouterr()
    assert "无定时任务" in captured.out


def test_schedule_remove_not_found(capsys, tmp_path, monkeypatch):
    """schedule remove 不存在的任务应退出码 1"""
    from bt_cli.scheduler import Scheduler
    monkeypatch.setattr(Scheduler, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(Scheduler, "DATA_DIR", str(tmp_path))

    from bt_cli.commands.schedule import cmd_schedule
    args = _make_args(command="schedule", schedule_action="remove", task_id="nonexistent")
    with pytest.raises(SystemExit) as exc_info:
        cmd_schedule(args)
    assert exc_info.value.code == 1


# ── stop 命令 ──

def test_stop_no_target(capsys):
    """stop 无目标且无 --all 应退出码 1"""
    from bt_cli.commands.stop import cmd_stop
    args = _make_args(command="stop", tree_id=None, all=False)
    with pytest.raises(SystemExit) as exc_info:
        cmd_stop(args)
    assert exc_info.value.code == 1


def test_stop_all(capsys):
    """stop --all 尝试停止所有行为树"""
    # patch requests 模块（stop 在函数内 import requests）
    with patch("requests.get") as mock_get, patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value.json.return_value = []
        mock_post.return_value = mock_resp

        from bt_cli.commands.stop import cmd_stop
        args = _make_args(command="stop", all=True)
        cmd_stop(args)
        captured = capsys.readouterr()
        assert "停止" in captured.out


# ── remote 命令 ──

def test_remote_status(capsys):
    """remote status 查询远程状态"""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok", "version": "1.0.0"}
        mock_get.return_value = mock_resp

        from bt_cli.commands.remote import cmd_remote
        args = _make_args(
            command="remote", target="localhost:8080",
            action="status", token="abc"
        )
        cmd_remote(args)
        captured = capsys.readouterr()
        assert "ok" in captured.out or "1.0.0" in captured.out


def test_remote_connection_error(capsys):
    """remote 连接失败应退出码 1"""
    import requests as requests_mod
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests_mod.ConnectionError("Connection refused")

        from bt_cli.commands.remote import cmd_remote
        args = _make_args(command="remote", target="localhost:9999", action="status")
        with pytest.raises(SystemExit) as exc_info:
            cmd_remote(args)
        assert exc_info.value.code == 1


def test_remote_trees(capsys):
    """remote trees 列出远程行为树"""
    with patch("requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"tree_id": "t1", "status": "running"},
            {"tree_id": "t2", "status": "stopped"},
        ]
        mock_get.return_value = mock_resp

        from bt_cli.commands.remote import cmd_remote
        args = _make_args(command="remote", target="localhost:8080", action="trees")
        cmd_remote(args)
        captured = capsys.readouterr()
        assert "t1" in captured.out
        assert "t2" in captured.out


def test_remote_start_no_tree_id(capsys):
    """remote start 未指定 --tree-id 应退出码 1"""
    from bt_cli.commands.remote import cmd_remote
    args = _make_args(
        command="remote", target="localhost:8080",
        action="start", tree_id=None
    )
    with pytest.raises(SystemExit) as exc_info:
        cmd_remote(args)
    assert exc_info.value.code == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
