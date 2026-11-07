"""AutoDoor Behavior Tree CLI"""
import sys
import argparse


# CLI 子命令名集合。
# main.py 用它判断"当前进程是 CLI 调用还是 GUI 启动"——
# 这是打包成 exe 后 CLI 仍可用的唯一开关。
# 新增子命令时必须同步加到这里，否则打包版会把它当成 GUI 参数而启动图形界面。
COMMAND_NAMES = (
    "run",
    "status",
    "stop",
    "schedule",
    "daemon",
    "remote",
    "plugin",
    "config",
    "ai",
    "assets",
)


def _ensure_utf8_stdio():
    """管道/重定向场景统一使用 UTF-8 输出

    交互式控制台（isatty 为真）保持系统代码页，避免 CMD 直接运行时乱码；
    被重定向到文件或作为子进程管道读取时（DSH、CI、AI agent）改用 UTF-8，
    否则读取方按 UTF-8 解码 GBK 字节会得到乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is None or stream.isatty():
                continue
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # reconfigure 不可用（如被替换成非 TextIOWrapper）时静默跳过
            pass


def main():
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="autodoor-bt",
        description="AutoDoor 行为树 CLI 工具"
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="运行行为树")
    run_parser.add_argument("tree_file", help="行为树 JSON 文件路径")
    run_parser.add_argument("--headless", action="store_true", help="无 GUI 模式")
    run_parser.add_argument("--project", default=None, help="项目根目录")
    run_parser.add_argument("--bus", action="store_true", help="启用消息总线")
    run_parser.add_argument("--rest", action="store_true", help="启用 REST API")
    run_parser.add_argument("--rest-host", default="127.0.0.1")
    run_parser.add_argument("--rest-port", type=int, default=8080)
    run_parser.add_argument("--ws", action="store_true", help="启用 WebSocket 服务")
    run_parser.add_argument("--ws-host", default="127.0.0.1")
    run_parser.add_argument("--ws-port", type=int, default=8765)
    run_parser.add_argument("--plugins", action="store_true", help="启用插件系统")

    # status 命令
    subparsers.add_parser("status", help="查询运行状态")

    # stop 命令
    stop_parser = subparsers.add_parser("stop", help="停止行为树")
    stop_parser.add_argument("tree_id", nargs="?", default=None)
    stop_parser.add_argument("--all", action="store_true")
    stop_parser.add_argument("--force", action="store_true")

    # schedule 命令
    sched_parser = subparsers.add_parser("schedule", help="定时调度管理")
    sched_sub = sched_parser.add_subparsers(dest="schedule_action")
    sched_add = sched_sub.add_parser("add", help="添加定时任务")
    sched_add.add_argument("tree_file")
    sched_add.add_argument("--cron", default=None)
    sched_add.add_argument("--interval", default=None)
    sched_add.add_argument("--once", default=None)
    sched_add.add_argument("--name", default="")
    sched_add.add_argument("--headless", action="store_true")
    sched_sub.add_parser("list", help="列出定时任务")
    sched_rm = sched_sub.add_parser("remove", help="删除定时任务")
    sched_rm.add_argument("task_id")
    sched_run = sched_sub.add_parser("run", help="立即执行一次定时任务")
    sched_run.add_argument("task_id")
    sched_enable = sched_sub.add_parser("enable", help="启用定时任务")
    sched_enable.add_argument("task_id")
    sched_disable = sched_sub.add_parser("disable", help="禁用定时任务")
    sched_disable.add_argument("task_id")

    # daemon 命令
    daemon_parser = subparsers.add_parser("daemon", help="守护进程模式")
    daemon_parser.add_argument("--start", action="store_true")
    daemon_parser.add_argument("--stop", action="store_true")
    daemon_parser.add_argument("--restart", action="store_true")
    daemon_parser.add_argument("--status", action="store_true")
    daemon_parser.add_argument("--foreground", action="store_true")

    # remote 命令
    remote_parser = subparsers.add_parser("remote", help="远程控制")
    remote_parser.add_argument("target", help="host:port")
    remote_parser.add_argument("action", choices=["status", "trees", "start", "stop", "blackboard", "nodes"])
    remote_parser.add_argument("--tree-id", default=None)
    remote_parser.add_argument("--token", default=None)
    remote_parser.add_argument("--json", action="store_true")

    # plugin 命令
    plugin_parser = subparsers.add_parser("plugin", help="插件管理")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_action")
    plugin_sub.add_parser("list", help="列出已安装插件")
    plugin_sub.add_parser("nodes", help="列出插件提供的节点类型与参数")
    plugin_load = plugin_sub.add_parser("load", help="加载插件")
    plugin_load.add_argument("path", help="插件目录路径")
    plugin_start = plugin_sub.add_parser("start", help="启动插件")
    plugin_start.add_argument("name")
    plugin_stop = plugin_sub.add_parser("stop", help="停止插件")
    plugin_stop.add_argument("name")
    plugin_info = plugin_sub.add_parser("info", help="查看插件详情")
    plugin_info.add_argument("name")
    plugin_unload = plugin_sub.add_parser("unload", help="卸载插件")
    plugin_unload.add_argument("name")

    # assets 命令（制作期视觉素材落盘与校验）
    assets_parser = subparsers.add_parser("assets", help="视觉素材清单管理")
    assets_sub = assets_parser.add_subparsers(dest="assets_action")

    assets_add = assets_sub.add_parser("add", help="从截图裁剪并登记一条素材")
    assets_add.add_argument("--name", required=True, help="素材名（模板文件名）")
    assets_add.add_argument("--source", help="源图路径（与 --capture 二选一）")
    assets_add.add_argument("--capture", help="直接截屏，格式 x1,y1,x2,y2")
    assets_add.add_argument("--origin", help="源图左上角对应的屏幕坐标 x,y")
    assets_add.add_argument("--bbox", required=True, help="裁剪框（源图内坐标）x1,y1,x2,y2")
    assets_add.add_argument("--semantic", help="语义描述，供人工核对与追溯")
    assets_add.add_argument("--color", help="指定主色 #RRGGBB，缺省自动提取")
    assets_add.add_argument("--anchor", default="center", choices=["center", "topleft"])
    assets_add.add_argument("--refine-color",
                            help="精定位颜色 #RRGGBB：把 VLM 粗框外扩后用颜色连通域refine")
    assets_add.add_argument("--refine-expand", type=float, default=3.0,
                            help="精定位外扩倍数，默认 3.0（太小会截断目标）")
    assets_add.add_argument("--refine-tolerance", type=int, default=50,
                            help="精定位颜色容差，默认 50")
    assets_add.add_argument("--hwnd", type=int, help="目标窗口句柄，用于换算客户区坐标")
    assets_add.add_argument("--offset", help="窗口客户区屏幕原点 x,y（无 hwnd 时的替代）")
    assets_add.add_argument("--project", help="项目根目录，默认当前目录")
    assets_add.add_argument("--manifest", help="manifest 路径，默认 assets/manifest.json")

    assets_verify = assets_sub.add_parser("verify", help="校验 manifest 与模板一致性")
    assets_verify.add_argument("--project", help="项目根目录，默认当前目录")
    assets_verify.add_argument("--manifest", help="manifest 路径")

    assets_list = assets_sub.add_parser("list", help="列出已登记素材")
    assets_list.add_argument("--project", help="项目根目录，默认当前目录")
    assets_list.add_argument("--manifest", help="manifest 路径")

    # config 命令
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_get = config_sub.add_parser("get", help="读取配置")
    config_get.add_argument("key")
    config_set = config_sub.add_parser("set", help="设置配置")
    config_set.add_argument("key")
    config_set.add_argument("value")
    config_sub.add_parser("list", help="列出所有配置")
    config_sub.add_parser("path", help="显示配置文件路径")

    # ai 命令
    ai_parser = subparsers.add_parser("ai", help="AI 编排自动化")
    ai_sub = ai_parser.add_subparsers(dest="ai_action")

    ai_plan = ai_sub.add_parser("plan", help="阶段①: 意图分析")
    ai_plan.add_argument("description", help="任务描述")

    ai_select = ai_sub.add_parser("select", help="阶段②: 节点选型")
    ai_select.add_argument("plan_file", help="plan.json 文件路径")

    ai_scan = ai_sub.add_parser("scan", help="阶段③: VLM屏幕感知")
    ai_scan.add_argument("structure_file", help="structure.json 文件路径")

    ai_generate = ai_sub.add_parser("generate", help="阶段④: 生成JSON")
    ai_generate.add_argument("structure_file", help="structure_filled.json 文件路径")

    ai_validate = ai_sub.add_parser("validate", help="校验JSON结构")
    ai_validate.add_argument("tree_file", help="tree.json 文件路径")

    ai_test = ai_sub.add_parser("test", help="阶段⑤: 试运行")
    ai_test.add_argument("tree_file", help="tree.json 文件路径")
    ai_test.add_argument("--timeout", type=int, default=None, help="超时毫秒")

    ai_refine = ai_sub.add_parser("refine", help="阶段⑤: 迭代修正")
    ai_refine.add_argument("tree_file", help="tree.json 文件路径")
    ai_refine.add_argument("--max-rounds", type=int, default=None, help="最大迭代次数")

    ai_nodes = ai_sub.add_parser("nodes", help="列出可用节点规格")

    ai_create = ai_sub.add_parser("create", help="完整创建流程")
    ai_create.add_argument("description", help="任务描述")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # 路由到对应命令处理函数
    _dispatch(args)


def _dispatch(args):
    """路由到对应命令"""
    cmd = args.command
    if cmd == "run":
        from bt_cli.commands.run import cmd_run
        cmd_run(args)
    elif cmd == "status":
        from bt_cli.commands.status import cmd_status
        cmd_status(args)
    elif cmd == "stop":
        from bt_cli.commands.stop import cmd_stop
        cmd_stop(args)
    elif cmd == "schedule":
        from bt_cli.commands.schedule import cmd_schedule
        cmd_schedule(args)
    elif cmd == "daemon":
        from bt_cli.commands.daemon import cmd_daemon
        cmd_daemon(args)
    elif cmd == "remote":
        from bt_cli.commands.remote import cmd_remote
        cmd_remote(args)
    elif cmd == "plugin":
        from bt_cli.commands.plugin import cmd_plugin
        cmd_plugin(args)
    elif cmd == "config":
        from bt_cli.commands.config import cmd_config
        cmd_config(args)
    elif cmd == "ai":
        from bt_cli.commands.ai import cmd_ai
        cmd_ai(args)
    elif cmd == "assets":
        from bt_cli.commands.assets import cmd_assets
        cmd_assets(args)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
