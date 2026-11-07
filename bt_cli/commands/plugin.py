"""plugin 命令 — 插件管理"""
import sys
import os


def cmd_plugin(args):
    """插件管理"""
    action = getattr(args, "plugin_action", None)

    if action is None:
        print("用法: autodoor-bt plugin <list|load|start|stop|info>")
        sys.exit(1)

    from bt_plugins.base import PluginContext
    from bt_plugins.loader import PluginLoader
    from config.settings_manager import get_settings_manager

    settings = get_settings_manager()
    context = PluginContext(settings=settings)
    loader = PluginLoader(context)

    # 先扫描和加载已知的插件
    from bt_utils.resource_manager import get_builtin_plugins_dir, get_user_plugin_dir
    builtin_dir = get_builtin_plugins_dir()
    if os.path.isdir(builtin_dir):
        infos = loader.scan(builtin_dir)
        for info in infos:
            plugin_dir = os.path.join(builtin_dir, info.name)
            loader.load_plugin(plugin_dir)

    # 也扫描用户插件目录（打包版落在 exe 同级，不依赖 cwd）
    user_dir = get_user_plugin_dir()
    if os.path.isdir(user_dir):
        infos = loader.scan(user_dir)
        for info in infos:
            plugin_dir = os.path.join(user_dir, info.name)
            loader.load_plugin(plugin_dir)

    if action == "list":
        _list_plugins(loader)
    elif action == "nodes":
        _list_plugin_nodes(loader)
    elif action == "load":
        _load_plugin(loader, args)
    elif action == "start":
        _start_plugin(loader, args)
    elif action == "stop":
        _stop_plugin(loader, args)
    elif action == "unload":
        _unload_plugin(loader, args)
    elif action == "info":
        _show_info(loader, args)


def _list_plugins(loader):
    """列出插件"""
    infos = loader.list_plugins()
    if not infos:
        print("无已加载的插件")
        return

    print(f"插件列表 ({len(infos)} 个):")
    print("-" * 60)
    for info in infos:
        status = "已启动" if loader.is_started(info.name) else "已停止"
        print(f"  {info.display_name} ({info.name}) v{info.version}")
        print(f"    作者: {info.author}")
        print(f"    描述: {info.description}")
        print(f"    分类: {info.category}")
        print(f"    状态: {status}")
        print("-" * 60)


def _list_plugin_nodes(loader):
    """列出所有插件提供的节点类型与参数 schema（节点名带插件名前缀）

    用于 AI/DSH agent 发现插件能力：内置节点只覆盖 29 种，插件节点以
    ``{插件名}.{节点类型}`` 形式注册（如 math_expressions.ExpressionNode），
    在 structure.json / tree.json 中必须使用这种带前缀的名字。
    """
    # 启动全部插件以填充 display_info 与 schema（幂等，已启动直接返回）
    for info in loader.list_plugins():
        loader.start_plugin(info.name)

    display = loader.get_registered_display_info()
    schemas = loader.get_registered_schemas()

    infos = loader.list_plugins()
    if not infos:
        print("无已加载的插件")
        return

    total = 0
    for info in infos:
        prefix = info.name + "."
        node_types = sorted([t for t in display if t.startswith(prefix)])
        for t in schemas:
            if t.startswith(prefix) and t not in node_types:
                node_types.append(t)
        node_types.sort()

        if not node_types:
            continue

        print(f"\n{'='*60}")
        print(f"  插件: {info.display_name} ({info.name}) v{info.version}")
        print(f"  作者: {info.author}")
        print(f"  描述: {info.description}")
        print(f"{'='*60}")

        for node_type in node_types:
            total += 1
            meta = display.get(node_type, {})
            schema = schemas.get(node_type, [])
            print(f"\n  [{node_type}]")
            print(f"    显示名: {meta.get('display_name', '')}")
            print(f"    描述: {meta.get('description', '')}")
            print(f"    分类: {meta.get('category', 'plugin')}")
            if schema:
                print(f"    参数:")
                for s in schema:
                    default = s.get("default")
                    if isinstance(default, str):
                        default_str = f'"{default}"'
                    elif isinstance(default, bool):
                        default_str = "true" if default else "false"
                    else:
                        default_str = str(default)
                    print(f"      {s.get('key')} ({s.get('type', 'text')}) = {default_str}  — {s.get('label', '')}")

    print(f"\n共 {total} 个插件节点")


def _load_plugin(loader, args):
    """加载插件"""
    if loader.load_plugin(args.path):
        print(f"插件加载成功: {args.path}")
    else:
        print(f"插件加载失败: {args.path}")
        sys.exit(1)


def _start_plugin(loader, args):
    """启动插件"""
    if loader.start_plugin(args.name):
        print(f"插件已启动: {args.name}")
    else:
        print(f"插件启动失败: {args.name}")
        sys.exit(1)


def _stop_plugin(loader, args):
    """停止插件"""
    loader.stop_plugin(args.name)
    print(f"插件已停止: {args.name}")


def _unload_plugin(loader, args):
    """卸载插件"""
    if args.name not in [p.name for p in loader.list_plugins()]:
        print(f"未找到插件: {args.name}")
        sys.exit(1)
    loader.unload_plugin(args.name)
    print(f"插件已卸载: {args.name}")


def _show_info(loader, args):
    """显示插件详情"""
    info = loader.get_plugin_info(args.name)
    if not info:
        print(f"未找到插件: {args.name}")
        sys.exit(1)

    print(f"插件详情:")
    print(f"  名称: {info.name}")
    print(f"  显示名: {info.display_name}")
    print(f"  版本: {info.version}")
    print(f"  作者: {info.author}")
    print(f"  描述: {info.description}")
    print(f"  分类: {info.category}")
    print(f"  最低版本: {info.min_app_version or '无限制'}")
    print(f"  依赖: {', '.join(info.dependencies) if info.dependencies else '无'}")
