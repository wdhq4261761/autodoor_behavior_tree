# bt_cli/ai/iteration_engine.py
"""阶段⑤ 试运行 + 迭代修正

通过 HeadlessRunner 试运行行为树，收集日志，
AI 分析失败原因，提供修正建议，应用修正后重新试运行。
"""
import json
import os
import copy
import shutil
import subprocess
import sys
from typing import Dict, Any, List, Optional

from bt_cli.ai.llm_client import LLMClient
from bt_cli.ai.resource_path import get_resource_path, get_cli_path
from bt_utils.json_io import load_json


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CLI_PATH = get_cli_path()


class IterationError(Exception):
    """迭代修正错误"""
    pass


class IterationEngine:
    """试运行 + 迭代修正引擎

    工作流程：
    1. 试运行行为树（限时）
    2. 收集执行日志、节点状态、黑板变量
    3. AI 分析失败原因
    4. 应用修正建议
    5. 重新试运行（可多轮）
    """

    PROMPT_FILE = get_resource_path(__file__, "prompts", "failure_analysis.md")

    def __init__(self, llm_client: LLMClient = None):
        self._llm = llm_client

    def run_test(self, tree_path: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        """试运行行为树

        Args:
            tree_path: tree.json 文件路径
            timeout_ms: 超时毫秒

        Returns:
            试运行报告 {"success", "node_statuses", "logs", "blackboard"}
        """
        # PyInstaller 打包环境下，sys.executable 是主程序 exe 而非 Python 解释器，
        # 且 cli.py 路径也与开发环境不同。此时改用进程内 HeadlessRunner 执行。
        if hasattr(sys, "_MEIPASS"):
            return self._run_test_in_process(tree_path, timeout_ms)

        # 开发环境：通过 subprocess 调用 CLI run --headless
        cmd = [
            sys.executable, _CLI_PATH,
            "run", tree_path, "--headless",
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace',
                timeout=timeout_ms / 1000,
            )
            success = result.returncode == 0
            logs = result.stdout.split("\n") if result.stdout else []
            if result.stderr:
                logs.extend(result.stderr.split("\n"))
        except subprocess.TimeoutExpired:
            success = False
            logs = [f"试运行超时 ({timeout_ms}ms)"]
        except Exception as e:
            success = False
            logs = [f"试运行异常: {e}"]

        return {
            "success": success,
            "node_statuses": {},  # 后续可通过日志解析
            "logs": logs,
            "blackboard": {},
        }

    def _run_test_in_process(self, tree_path: str, timeout_ms: int = 30000) -> Dict[str, Any]:
        """进程内执行行为树（PyInstaller 环境兜底方案）

        直接调用 HeadlessRunner 运行行为树，避免 subprocess + cli.py 的路径问题。
        使用线程 + 超时控制，模拟 subprocess 的超时行为。
        """
        import io
        import threading
        import contextlib

        logs: list = []
        success = False
        exception: Optional[Exception] = None

        def _runner():
            nonlocal success, exception
            try:
                from bt_core.headless import HeadlessRunner

                # 捕获 stdout 作为日志
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    runner = HeadlessRunner()
                    code = runner.run(tree_path, project=None)
                output = buf.getvalue()
                if output:
                    logs.extend(output.split("\n"))
                if code == 2:
                    logs.append("预检未通过，试运行未执行")
                success = (code == 0)
            except Exception as e:
                exception = e
                logs.append(f"运行错误: {e}")

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=timeout_ms / 1000)

        if thread.is_alive():
            # 超时：HeadlessRunner 没有直接的 stop 从外部调用机制，
            # 这里标记超时并返回（线程会随进程退出而终止）
            success = False
            logs.insert(0, f"试运行超时 ({timeout_ms}ms)")
        elif exception:
            success = False

        return {
            "success": success,
            "node_statuses": {},
            "logs": logs,
            "blackboard": {},
        }

    def analyze_failure(self, test_report: Dict[str, Any],
                        tree_data: Dict[str, Any],
                        task_context: str) -> Dict[str, Any]:
        """AI 分析失败原因

        Args:
            test_report: 试运行报告
            tree_data: 当前行为树结构
            task_context: 任务上下文

        Returns:
            {"analysis", "fixes", "confidence"}

        Raises:
            IterationError: 分析失败
        """
        if self._llm is None:
            self._llm = LLMClient.from_config("llm")

        system_prompt = self._load_prompt()

        # 精简行为树结构（只保留关键信息）
        tree_summary = self._summarize_tree(tree_data)

        user_content = (
            f"## 任务上下文\n{task_context}\n\n"
            f"## 试运行报告\n```json\n{json.dumps(test_report, ensure_ascii=False, indent=2)}\n```\n\n"
            f"## 行为树结构\n```json\n{json.dumps(tree_summary, ensure_ascii=False, indent=2)}\n```\n\n"
            f"请分析失败原因并提供修正建议。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            result = self._llm.chat(
                messages,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            raise IterationError(f"LLM 请求失败: {e}") from e

        try:
            analysis = json.loads(result["content"])
        except json.JSONDecodeError as e:
            raise IterationError(
                f"LLM 返回的 JSON 无效: {e}\n原始内容: {result['content'][:500]}"
            ) from e

        if not isinstance(analysis, dict):
            raise IterationError(
                f"LLM 返回的 JSON 应为对象，实际为 {type(analysis).__name__}: "
                f"{result['content'][:500]}"
            )

        return analysis

    def apply_fixes(self, tree_data: Dict[str, Any],
                    fixes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """应用修正建议到行为树

        Args:
            tree_data: 行为树数据
            fixes: 修正建议列表

        Returns:
            修正后的行为树（深拷贝）
        """
        fixed = copy.deepcopy(tree_data)
        nodes = fixed.get("nodes", {})

        for fix in fixes:
            if not isinstance(fix, dict):
                continue
            node_id = fix.get("node_id")
            param = fix.get("param")
            new_value = fix.get("new_value")
            if node_id is None or param is None or new_value is None:
                continue

            if node_id in nodes:
                if "config" not in nodes[node_id]:
                    nodes[node_id]["config"] = {}
                nodes[node_id]["config"][param] = new_value

        return fixed

    def iterate(self, tree_path: str, max_rounds: int = 3,
                task_context: str = "") -> Dict[str, Any]:
        """完整迭代流程

        在迭代开始前会备份原始 tree_path 文件为 ``tree_path + ".bak"``，
        以便在迭代过程中出现异常或修正结果不理想时可手动恢复。
        备份文件在方法返回后保留，不会自动删除。

        Args:
            tree_path: tree.json 文件路径
            max_rounds: 最大迭代次数
            task_context: 任务上下文

        Returns:
            {"success", "rounds", "final_tree", "reports"}
        """
        tree_data = load_json(tree_path)

        # 备份原始文件，便于异常时手动恢复
        backup_path = tree_path + ".bak"
        shutil.copy2(tree_path, backup_path)

        reports = []

        for round_num in range(1, max_rounds + 1):
            print(f"\n--- 第 {round_num} 轮试运行 ---")

            # 试运行
            report = self.run_test(tree_path)
            reports.append(report)

            if report["success"]:
                print("试运行成功！")
                return {
                    "success": True,
                    "rounds": round_num,
                    "final_tree": tree_data,
                    "reports": reports,
                }

            # AI 分析
            print("AI 正在分析失败原因...")
            try:
                analysis = self.analyze_failure(report, tree_data, task_context)
            except IterationError as e:
                print(f"分析失败: {e}")
                break

            print(f"分析: {analysis.get('analysis', '')}")
            fixes = analysis.get("fixes", [])

            if not fixes:
                print("无修正建议，停止迭代")
                break

            # 应用修正
            tree_data = self.apply_fixes(tree_data, fixes)
            print(f"应用了 {len(fixes)} 个修正")

            # 保存修正后的树
            with open(tree_path, "w", encoding="utf-8") as f:
                json.dump(tree_data, f, ensure_ascii=False, indent=2)

        return {
            "success": False,
            "rounds": len(reports),
            "final_tree": tree_data,
            "reports": reports,
        }

    def _summarize_tree(self, tree_data: Dict) -> List[Dict]:
        """精简行为树结构用于 AI 分析"""
        summary = []
        for node_id, node in tree_data.get("nodes", {}).items():
            summary.append({
                "id": node_id,
                "type": node.get("type"),
                "config": node.get("config", {}),
                "children": node.get("children", []),
            })
        return summary

    def _load_prompt(self) -> str:
        """加载系统提示词"""
        with open(self.PROMPT_FILE, "r", encoding="utf-8") as f:
            return f.read()
