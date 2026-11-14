"""run 命令 — 运行行为树"""
import os
import sys


def cmd_run(args):
    """运行行为树"""
    if not os.path.isfile(args.tree_file):
        print(f"错误: 文件不存在: {args.tree_file}")
        sys.exit(3)

    if args.headless:
        code = _run_headless(args)
        if code:
            sys.exit(code)
    else:
        _run_gui(args)


def _run_headless(args):
    """无 GUI 模式运行，返回退出码（0 成功，2 预检未通过）"""
    from bt_core.headless import HeadlessRunner
    from config.settings_manager import get_settings_manager

    settings = get_settings_manager()

    # 应用 CLI 参数到配置
    if args.bus:
        settings.set("message_bus.enabled", True)
    if args.rest:
        settings.set("rest_server.enabled", True)
        settings.set("rest_server.host", args.rest_host)
        settings.set("rest_server.port", args.rest_port)
    if args.ws:
        settings.set("websocket_server.enabled", True)
        settings.set("websocket_server.host", args.ws_host)
        settings.set("websocket_server.port", args.ws_port)

    # 落盘保存配置（--plugins 不落盘，避免一次运行永久改变后续行为）
    settings.save_settings()

    # 打印运行信息
    print(f"运行行为树: {args.tree_file}")
    print(f"  模式: Headless")
    if args.bus:
        print(f"  消息总线: 已启用")
    if args.rest:
        print(f"  REST API: {args.rest_host}:{args.rest_port}")
    if args.ws:
        print(f"  WebSocket: {args.ws_host}:{args.ws_port}")
    if args.plugins:
        print(f"  插件系统: 已启用")

    runner = HeadlessRunner(enable_plugins=args.plugins)

    try:
        code = runner.run(
            args.tree_file, args.project,
            check_preflight=not args.no_preflight,
        )
    except KeyboardInterrupt:
        print("\n停止运行...")
        runner.stop()
        return 0
    except Exception as e:
        print(f"运行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    return code


def _run_gui(args):
    """GUI 模式运行"""
    # 将 tree_file 传递给 GUI
    os.environ["AUTODOOR_BT_OPEN_FILE"] = os.path.abspath(args.tree_file)

    # 重置 sys.argv，避免 main.py 的 parse_args 解析 CLI 子命令参数失败
    sys.argv = [sys.argv[0]]

    # 启动 GUI 主应用
    from main import main as gui_main
    gui_main()
