"""uia_bridge — UIA 控件采样插件

设计原则（方案 v3 第 2 章）：**制作期接入，运行期物化为坐标**。

为什么不在运行期每 tick 调 UIA：

* 首次冷启动 330~840 ms（本机实测：资源管理器 137 控件 / 0.84 s）；
* COM 跨进程封送，控件多时线性放大；
* 窗口重建后缓存的 element 引用会失效。

因此本插件只在制作期或低频「再校准」时采样，产出**客户区相对坐标**，
运行期交给内置 ``MouseClickNode`` 直接点击。

⚠️ 坐标陷阱：``bind_window`` 之后，``execute_mouse_click`` 会把所有
``position`` 当作**客户区相对坐标**再转屏幕。若采样时写的是屏幕绝对坐标，
运行期会被二次转换而点偏。所以本插件默认输出 ``client`` 模式。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from bt_core.nodes import ActionNode, ConditionNode, NodeStatus
from bt_utils.coordinate import CoordinateConverter
from bt_utils.log_manager import LogManager

# UIA 控件树枚举可能很慢，限制单次遍历规模
_MAX_NODES_DEFAULT = 3000


# ---------------------------------------------------------------------------
# UIA 访问
# ---------------------------------------------------------------------------
def _require_pywinauto():
    try:
        import pywinauto  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "未安装 pywinauto，请执行: pip install pywinauto"
        ) from e


def _resolve_hwnd(cfg) -> int:
    """按 hwnd / window_title / window_class 定位窗口句柄。"""
    hwnd = cfg.get_int("hwnd", 0)
    if hwnd:
        return hwnd

    title = str(cfg.get("window_title", "") or "").strip() or None
    class_name = str(cfg.get("window_class", "") or "").strip() or None
    if not title and not class_name:
        raise RuntimeError("需配置 hwnd，或 window_title / window_class 之一")

    found = CoordinateConverter.find_window(title=title, class_name=class_name)
    if not found:
        raise RuntimeError(
            f"未找到窗口 title={title!r} class={class_name!r}"
        )
    return int(found)


def _connect(hwnd: int):
    _require_pywinauto()
    from pywinauto import Application

    app = Application(backend="uia").connect(handle=hwnd, timeout=5)
    return app.window(handle=hwnd)


def _match(elem, name: str, control_type: str, name_mode: str) -> bool:
    info = elem.element_info
    actual_type = (info.control_type or "").strip()
    if control_type and actual_type.lower() != control_type.strip().lower():
        return False
    if not name:
        return True

    actual_name = (info.name or "").strip()
    if name_mode == "regex":
        import re
        return re.search(name, actual_name) is not None
    if name_mode == "contains":
        return name in actual_name
    return actual_name == name


def _find_controls(win, name: str, control_type: str, name_mode: str,
                   max_nodes: int) -> List[Any]:
    """遍历控件树并按条件筛选。"""
    matched = []
    scanned = 0
    for elem in win.descendants():
        scanned += 1
        if scanned > max_nodes:
            break
        try:
            if _match(elem, name, control_type, name_mode):
                matched.append(elem)
        except Exception:
            continue
    return matched


def _rect_of(elem) -> Optional[Tuple[int, int, int, int]]:
    try:
        r = elem.rectangle()
        return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:
        return None


def _safe(element, method: str, default=None):
    try:
        return getattr(element, method)()
    except Exception:
        return default


# ---------------------------------------------------------------------------
# UIASampleNode
# ---------------------------------------------------------------------------
class UIASampleNode(ActionNode):
    """采样一个控件，输出屏幕坐标与客户区相对坐标。

    适合在制作期运行一次，把结果固化到 structure.json / manifest.json；
    运行期不要再高频调用。
    """

    NODE_TYPE = "UIASampleNode"

    def _execute_action(self, context) -> NodeStatus:
        started = time.time()
        try:
            hwnd = _resolve_hwnd(self.config)
            win = _connect(hwnd)

            name = str(self.config.get("control_name", "") or "").strip()
            ctype = str(self.config.get("control_type", "") or "").strip()
            name_mode = str(self.config.get("name_mode", "exact") or "exact")
            nth = self.config.get_int("nth", 0)
            max_nodes = self.config.get_int("max_nodes", _MAX_NODES_DEFAULT)

            matches = _find_controls(win, name, ctype, name_mode, max_nodes)
            elapsed = int((time.time() - started) * 1000)

            if not matches:
                return self._fail(
                    f"未找到控件 name={name!r} type={ctype!r}"
                    f"（扫描 {elapsed}ms）"
                )
            if nth >= len(matches):
                return self._fail(
                    f"匹配到 {len(matches)} 个控件，但要求第 {nth} 个"
                )

            elem = matches[nth]
            rect = _rect_of(elem)
            if not rect:
                return self._fail("控件矩形不可用（可能已销毁）")

            left, top, right, bottom = rect
            screen_center = ((left + right) // 2, (top + bottom) // 2)

            client_center = CoordinateConverter.absolute_to_client(
                screen_center[0], screen_center[1], hwnd
            )
            if client_center is None:
                client_center = screen_center

            output_mode = str(self.config.get("output_mode", "client") or "client")
            position = client_center if output_mode == "client" else screen_center

            self._write_blackboard(context, elem, rect, screen_center,
                                   client_center, position)

            if self.config.get_bool("write_manifest", False):
                self._write_manifest(context, elem, rect, screen_center,
                                     client_center, hwnd, output_mode)

            LogManager.instance().log_success(
                node_type="UIA采样节点", node_name=self.name
            )
            LogManager.debug_print(
                f"[UIA] {name or ctype} -> screen={screen_center} "
                f"client={client_center} 匹配{len(matches)}个 耗时{elapsed}ms"
            )
            return NodeStatus.SUCCESS

        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"UIASampleNode '{self.name}'")
            return self._fail(f"执行异常: {e}")

    def _write_blackboard(self, context, elem, rect, screen_center,
                          client_center, position) -> None:
        bb = context.blackboard
        bb.set("uia_rect", list(rect))
        bb.set("uia_screen_x", screen_center[0])
        bb.set("uia_screen_y", screen_center[1])
        bb.set("uia_client_x", client_center[0])
        bb.set("uia_client_y", client_center[1])
        bb.set("uia_name", _safe(elem, "window_text", "") or "")
        bb.set("uia_control_type",
               getattr(elem.element_info, "control_type", "") or "")
        bb.set("uia_enabled", bool(_safe(elem, "is_enabled", False)))
        bb.set("uia_visible", bool(_safe(elem, "is_visible", False)))

        key = str(self.config.get("position_key", "") or "").strip()
        if key:
            bb.set(key, position)
        if self.config.get_bool("write_scalar", False):
            bb.set("last_detection_x", position[0])
            bb.set("last_detection_y", position[1])

    def _write_manifest(self, context, elem, rect, screen_center,
                        client_center, hwnd, output_mode) -> None:
        from bt_cli.commands.assets import _load_manifest

        project = str(self.config.get("project", "") or ".") or "."
        rel = str(self.config.get("manifest_path", "assets/manifest.json")
                  or "assets/manifest.json")
        import os
        path = rel if os.path.isabs(rel) else os.path.join(project, rel)

        data = _load_manifest(path)
        name = str(self.config.get("asset_name", "") or "").strip() \
            or (_safe(elem, "window_text", "") or "uia_anchor")
        entry = {
            "name": name,
            "kind": "anchor",
            "semantic": str(self.config.get("semantic", "") or ""),
            "template": None,
            "bbox_screen": list(rect),
            "center_screen": list(screen_center),
            "coord_client": list(client_center),
            "coord_mode": output_mode,
            "hwnd": hwnd,
            "control_type": getattr(elem.element_info, "control_type", "") or "",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        targets = [t for t in data.get("targets", []) if t.get("name") != name]
        targets.append(entry)
        data["targets"] = targets
        data.setdefault("version", 1)
        data["updated_at"] = entry["updated_at"]

        import json, os as _os
        _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        LogManager.debug_print(f"[UIA] 已写入 manifest: {path} -> {name}")

    def _fail(self, reason: str) -> NodeStatus:
        LogManager.instance().log_failure(
            node_type="UIA采样节点", node_name=self.name, reason=reason
        )
        LogManager.debug_print(f"[UIA][ERROR] {reason}")
        return NodeStatus.FAILURE


# ---------------------------------------------------------------------------
# UIAStateNode
# ---------------------------------------------------------------------------
class UIAStateNode(ConditionNode):
    """检查控件状态：存在 / 可用 / 可见。

    典型用途：确认按钮已启用再点击，或等待对话框消失。
    """

    NODE_TYPE = "UIAStateNode"

    def _check_condition(self, context) -> bool:
        try:
            hwnd = _resolve_hwnd(self.config)
            win = _connect(hwnd)

            name = str(self.config.get("control_name", "") or "").strip()
            ctype = str(self.config.get("control_type", "") or "").strip()
            name_mode = str(self.config.get("name_mode", "exact") or "exact")
            expect = str(self.config.get("expect", "exists") or "exists").lower()

            matches = _find_controls(
                win, name, ctype, name_mode,
                self.config.get_int("max_nodes", _MAX_NODES_DEFAULT),
            )
            if not matches:
                self._log_condition_result(False, f"未找到控件 {name or ctype}")
                return False

            elem = matches[self.config.get_int("nth", 0)]
            enabled = bool(_safe(elem, "is_enabled", False))
            visible = bool(_safe(elem, "is_visible", False))

            if expect == "exists":
                ok = True
            elif expect == "enabled":
                ok = enabled
            elif expect == "disabled":
                ok = not enabled
            elif expect == "visible":
                ok = visible
            else:
                self._log_condition_result(False, f"未知的 expect={expect}")
                return False

            self._log_condition_result(
                ok, f"expect={expect} enabled={enabled} visible={visible}"
            )
            return ok

        except Exception as e:
            from bt_utils.exception_handler import log_exception
            log_exception(e, f"UIAStateNode '{self.name}'")
            self._log_condition_result(False, f"执行异常: {e}")
            return False
