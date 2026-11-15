import os
import sys
import json
import time
import tempfile
import threading
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestHeadlessRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False, encoding='utf-8'
        )
        # 注意：序列化器期望扁平格式（nodes 字典 + connections 列表 + root_node ID），
        # 而非嵌套的 root.children 结构。
        tree_data = {
            "version": "2.1",
            "format_type": "behavior_tree",
            "root_node": "root",
            "nodes": {
                "root": {
                    "id": "root",
                    "type": "SequenceNode",
                    "name": "Root",
                    "config": {}
                },
                "delay1": {
                    "id": "delay1",
                    "type": "DelayNode",
                    "name": "Delay100ms",
                    "config": {"duration_ms": 100}
                }
            },
            "connections": [
                {"parent_id": "root", "child_id": "delay1"}
            ]
        }
        json.dump(tree_data, self.tmp)
        self.tmp.close()

    def tearDown(self):
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_headless_runner_can_be_imported(self):
        from bt_core.headless import HeadlessRunner
        self.assertTrue(hasattr(HeadlessRunner, 'run'))
        self.assertTrue(hasattr(HeadlessRunner, 'stop'))

    def test_headless_run_simple_tree(self):
        from bt_core.headless import HeadlessRunner
        runner = HeadlessRunner()
        # run() 返回退出码（0 表示正常结束），成功完成不抛出异常即为通过
        runner.run(self.tmp.name)

    def test_headless_stop(self):
        """Test that stop() works correctly"""
        from bt_core.headless import HeadlessRunner
        runner = HeadlessRunner()
        result = [None]
        def run_thread():
            result[0] = runner.run(self.tmp.name)
        t = threading.Thread(target=run_thread)
        t.start()
        time.sleep(0.05)  # Let it start
        runner.stop()
        t.join(timeout=2)
        self.assertTrue(t.is_alive() is False)  # Thread should have exited

    def test_context_set_headless_flag(self):
        from bt_core.context import ExecutionContext
        ctx = ExecutionContext()
        self.assertFalse(ctx.is_headless())
        ctx.set_headless(True)
        self.assertTrue(ctx.is_headless())
        ctx.set_headless(False)
        self.assertFalse(ctx.is_headless())

    def test_headless_notify_node_status_noop(self):
        from bt_core.context import ExecutionContext
        ctx = ExecutionContext()
        ctx.set_headless(True)
        called = []
        ctx._on_node_status = lambda nid, st: called.append((nid, st))
        ctx.notify_node_status("n1", "SUCCESS")
        self.assertEqual(called, [])


class TestMainHeadlessArg(unittest.TestCase):
    def test_main_argparse_headless_flag(self):
        with open(os.path.join(PROJECT_ROOT, "main.py"), 'r', encoding='utf-8') as f:
            source = f.read()
        self.assertIn("--headless", source)
        self.assertIn("argparse", source)


if __name__ == '__main__':
    unittest.main()
