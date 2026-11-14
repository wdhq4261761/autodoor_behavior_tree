# bt_cli/ai/node_spec_exporter.py
"""从 NodeRegistry 动态导出节点完整规格

替代旧方案中写死在 prompt 中的节点清单。
新增节点或插件节点注册后，AI 自动获得新规格，无需手动更新。

参数名称、默认值、类型均与 bt_nodes/ 下的实际节点实现保持一致。
"""
from typing import Dict, Type

from bt_core.registry import NodeRegistry
from bt_core.nodes import Node, CompositeNode, ConditionNode, ActionNode


# 节点参数文档 — 每种节点类型的关键参数说明
# 参数名和默认值必须与 bt_nodes/ 下实际节点 __init__ 中的 config.get() 调用一致
_NODE_PARAM_DOCS = {
    "StartNode": {
        "params": [
            {"name": "bind_window", "type": "bool", "default": False, "desc": "是否绑定窗口"},
            {"name": "window_title", "type": "string", "default": "", "desc": "窗口标题"},
            {"name": "window_pid", "type": "int", "default": 0, "desc": "窗口进程ID"},
        ],
        "desc": "行为树根节点，入口节点。顺序执行子节点，子节点失败后继续执行后续子节点",
    },
    "SequenceNode": {
        "params": [
            {"name": "continue_on_failure", "type": "bool", "default": False, "desc": "失败是否继续执行后续子节点"},
            {"name": "childinterval", "type": "int", "default": 0, "desc": "子节点执行间隔毫秒"},
            {"name": "childinterval_random", "type": "int", "default": 0, "desc": "子节点间隔随机范围毫秒"},
        ],
        "desc": "顺序执行：全部成功才成功，任一失败则失败",
    },
    "SelectorNode": {
        "params": [
            {"name": "childinterval", "type": "int", "default": 0, "desc": "子节点执行间隔毫秒"},
            {"name": "childinterval_random", "type": "int", "default": 0, "desc": "子节点间隔随机范围毫秒"},
        ],
        "desc": "选择执行：依次尝试子节点，任一成功即成功，全部失败才失败",
    },
    "ParallelNode": {
        "params": [
            {"name": "success_policy", "type": "string", "default": "require_all",
             "desc": "成功策略：require_all（全部成功）/ require_one（任一成功）"},
        ],
        "desc": "并行执行：同时执行所有子节点",
    },
    "RandomNode": {
        "params": [
            {"name": "success_policy", "type": "string", "default": "require_all", "desc": "成功策略"},
            {"name": "fully_random", "type": "bool", "default": False, "desc": "是否每次完全随机（已执行的也可再次选中）"},
        ],
        "desc": "随机执行：随机选择子节点执行，用于防检测",
    },
    "SubtreeNode": {
        "params": [
            {"name": "subtree_path", "type": "string", "default": "", "desc": "子树项目文件夹路径"},
            {"name": "blackboard_mode", "type": "string", "default": "inherit",
             "desc": "黑板模式：inherit（共享）/ isolated（独立）/ namespaced（命名空间隔离）"},
            {"name": "namespace", "type": "string", "default": "", "desc": "命名空间前缀"},
            {"name": "auto_reload", "type": "bool", "default": False, "desc": "每次执行前重新加载"},
        ],
        "desc": "子树引用：加载外部行为树项目执行，支持黑板隔离",
    },
    "KeyPressNode": {
        "params": [
            {"name": "key", "type": "string", "default": "space", "desc": "按键名称（如 enter, space, ctrl+c, f1）"},
            {"name": "action", "type": "string", "default": "press",
             "desc": "动作：press（按一下）/ down（按下不释放）/ up（释放）"},
            {"name": "duration", "type": "int", "default": 0, "desc": "按压时长毫秒（0=瞬间）"},
            {"name": "duration_random", "type": "int", "default": 0, "desc": "按压时长随机增量毫秒"},
        ],
        "desc": "键盘按键",
    },
    "MouseClickNode": {
        "params": [
            {"name": "button", "type": "string", "default": "left",
             "desc": "鼠标按键：left/right/middle"},
            {"name": "position", "type": "list", "default": None, "desc": "点击坐标 [x, y]"},
            {"name": "action", "type": "string", "default": "press",
             "desc": "动作：press（点击）/ down（按下）/ up（释放）/ double（双击）"},
            {"name": "duration", "type": "int", "default": 100, "desc": "按压时长毫秒"},
            {"name": "use_blackboard", "type": "bool", "default": False,
             "desc": "是否从黑板读取位置"},
            {"name": "position_key", "type": "string", "default": "last_detection_position",
             "desc": "位置黑板键名"},
            {"name": "click_count", "type": "int", "default": 1, "desc": "点击次数（-1=无限）"},
            {"name": "click_interval", "type": "int", "default": 100, "desc": "点击间隔毫秒"},
            {"name": "duration_random", "type": "int", "default": 0, "desc": "按压时长随机增量毫秒"},
            {"name": "click_interval_random", "type": "int", "default": 0, "desc": "点击间隔随机增量毫秒"},
            {"name": "x_float", "type": "int", "default": 0, "desc": "X坐标随机浮动范围"},
            {"name": "y_float", "type": "int", "default": 0, "desc": "Y坐标随机浮动范围"},
        ],
        "desc": "鼠标点击",
    },
    "MouseMoveNode": {
        "params": [
            {"name": "position", "type": "list", "default": [0, 0], "desc": "起点坐标 [x, y]"},
            {"name": "use_blackboard", "type": "bool", "default": False, "desc": "是否从黑板读取起点"},
            {"name": "position_key", "type": "string", "default": "last_detection_position",
             "desc": "起点位置黑板键名"},
            {"name": "move_type", "type": "string", "default": "移动",
             "desc": "移动类型：移动/拖拽"},
            {"name": "drag_button", "type": "string", "default": "left", "desc": "拖拽按键"},
            {"name": "end_position", "type": "list", "default": None, "desc": "终点坐标 [x, y]"},
            {"name": "relative", "type": "bool", "default": False, "desc": "是否相对移动"},
            {"name": "offset", "type": "list", "default": None, "desc": "相对偏移 [dx, dy]"},
            {"name": "use_blackboard_end", "type": "bool", "default": False, "desc": "是否从黑板读取终点"},
            {"name": "position_key_end", "type": "string", "default": "", "desc": "终点位置黑板键名"},
            {"name": "move_duration", "type": "int", "default": 0, "desc": "移动时长毫秒"},
            {"name": "move_duration_random", "type": "int", "default": 0, "desc": "移动时长随机增量"},
            {"name": "drag_duration", "type": "int", "default": 0, "desc": "拖拽时长毫秒"},
            {"name": "drag_duration_random", "type": "int", "default": 0, "desc": "拖拽时长随机增量"},
            {"name": "x_float", "type": "int", "default": 0, "desc": "X坐标随机浮动"},
            {"name": "y_float", "type": "int", "default": 0, "desc": "Y坐标随机浮动"},
        ],
        "desc": "鼠标移动或拖拽",
    },
    "MouseScrollNode": {
        "params": [
            {"name": "distance", "type": "int", "default": 5, "desc": "滚动距离"},
            {"name": "clicks", "type": "int", "default": 1, "desc": "滚动次数"},
            {"name": "direction", "type": "string", "default": "向上",
             "desc": "方向：向上/向下/向左/向右"},
        ],
        "desc": "鼠标滚轮",
    },
    "DelayNode": {
        "params": [
            {"name": "duration_ms", "type": "int", "default": 1000, "desc": "延时时长毫秒"},
            {"name": "duration_ms_random", "type": "int", "default": 0, "desc": "延时随机增量毫秒"},
        ],
        "desc": "延时等待",
    },
    "SetVariableNode": {
        "params": [
            {"name": "variable_name", "type": "string", "default": "", "desc": "变量名"},
            {"name": "value", "type": "string", "default": "", "desc": "变量值"},
            {"name": "operation", "type": "string", "default": "set",
             "desc": "操作类型：set（设置）/ increment（递增）/ delete（删除）"},
            {"name": "value_type", "type": "string", "default": "constant",
             "desc": "值类型：constant（常量）/ variable（变量，仅operation=set时）"},
            {"name": "source_variable", "type": "string", "default": "",
             "desc": "来源变量名（value_type=variable时）"},
        ],
        "desc": "设置/修改/删除黑板变量",
    },
    "AlarmNode": {
        "params": [
            {"name": "sound_path", "type": "string", "default": "", "desc": "音频文件路径（空则使用默认报警声）"},
            {"name": "volume", "type": "int", "default": 70, "desc": "音量（0-100）"},
            {"name": "wait_complete", "type": "bool", "default": True, "desc": "是否等待播放完成"},
        ],
        "desc": "播放报警声音",
    },
    "ScriptNode": {
        "params": [
            {"name": "script_path", "type": "string", "default": "",
             "desc": "脚本文件路径（如 ./scripts/script/xxx.py）"},
            {"name": "loop", "type": "bool", "default": False, "desc": "是否循环执行"},
        ],
        "desc": "执行外部脚本文件",
    },
    "CodeNode": {
        "params": [
            {"name": "code_path", "type": "string", "default": "", "desc": "代码文件路径"},
            {"name": "code_type", "type": "string", "default": "auto",
             "desc": "代码类型：python/batch/powershell/auto"},
            {"name": "args", "type": "list", "default": [], "desc": "命令行参数列表"},
            {"name": "wait_complete", "type": "bool", "default": True, "desc": "是否等待执行完成"},
        ],
        "desc": "执行Python/Batch/PowerShell代码文件",
    },
    "StartTreeNode": {
        "params": [
            {"name": "target_tree", "type": "string", "default": "", "desc": "目标行为树名称"},
            {"name": "sound_path", "type": "string", "default": "", "desc": "启动音效路径"},
            {"name": "volume", "type": "int", "default": 70, "desc": "音量（0-100）"},
        ],
        "desc": "启动其他已加载的行为树",
    },
    "StopTreeNode": {
        "params": [
            {"name": "target_tree", "type": "string", "default": "",
             "desc": "目标行为树名称（空则停止当前树）"},
            {"name": "sound_path", "type": "string", "default": "", "desc": "停止音效路径"},
            {"name": "volume", "type": "int", "default": 70, "desc": "音量（0-100）"},
        ],
        "desc": "停止当前或其他已加载的行为树",
    },
    "TextInputNode": {
        "params": [
            {"name": "input_mode", "type": "string", "default": "文本提取值",
             "desc": "输入模式：文本提取值/预设文本/文件"},
            {"name": "preset_texts", "type": "list", "default": [],
             "desc": "预设文本列表（input_mode=预设文本时）"},
            {"name": "execution_mode", "type": "string", "default": "顺序",
             "desc": "执行模式：顺序/随机"},
            {"name": "blackboard_key", "type": "string", "default": "last_extracted_text",
             "desc": "文本提取值黑板键名（input_mode=文本提取值时）"},
            {"name": "file_path", "type": "string", "default": "",
             "desc": "文件路径（input_mode=文件时）"},
            {"name": "input_delay", "type": "int", "default": 0,
             "desc": "输入间隔毫秒（每个字符之间）"},
            {"name": "clear_before_input", "type": "bool", "default": False,
             "desc": "输入前是否清空原有内容"},
            {"name": "save_input_text", "type": "bool", "default": False,
             "desc": "是否保存输入文本到黑板"},
            {"name": "output_key", "type": "string", "default": "last_input_text",
             "desc": "输入文本存储黑板键名"},
        ],
        "desc": "文本输入（预设文本/提取值/文件）",
    },
    "OCRConditionNode": {
        "params": [
            {"name": "keywords", "type": "string", "default": "",
             "desc": "OCR识别关键词（多个用逗号分隔）"},
            {"name": "language", "type": "string", "default": "简体中文",
             "desc": "识别语言：简体中文/English/繁体中文"},
            {"name": "preprocess_mode", "type": "string", "default": "默认",
             "desc": "预处理模式：默认/复杂色彩/自适应/自动调优"},
            {"name": "search_direction", "type": "string", "default": "左上", "desc": "搜索方向"},
        ],
        "desc": "OCR识别文字条件节点",
    },
    "ImageConditionNode": {
        "params": [
            {"name": "template_path", "type": "string", "default": "",
             "desc": "模板图片路径（如 ./images/templates/xxx.png）"},
            {"name": "threshold", "type": "float", "default": 80,
             "desc": "匹配阈值（0-100，越高越严格）"},
            {"name": "multi_scale", "type": "bool", "default": False,
             "desc": "是否启用多尺度模板匹配（应对 UI 缩放变化）"},
            {"name": "scale_range", "type": "string", "default": "0.85,1.15",
             "desc": "多尺度缩放范围，如 \"0.85,1.15\"（最小,最大）"},
            {"name": "scale_steps", "type": "int", "default": 5,
             "desc": "多尺度缩放步数（1-20，越大越慢越精细）"},
        ],
        "desc": "图像匹配条件节点",
    },
    "ColorConditionNode": {
        "params": [
            {"name": "target_color", "type": "list/string", "default": None,
             "desc": "目标颜色 [R,G,B] 或 \"#RRGGBB\""},
            {"name": "tolerance", "type": "int", "default": 30, "desc": "颜色容差（0-255）"},
            {"name": "match_mode", "type": "string", "default": "any", "desc": "匹配模式"},
            {"name": "min_pixels", "type": "int", "default": 1, "desc": "最少匹配像素数"},
            {"name": "color_match_threshold", "type": "float", "default": 0.9, "desc": "颜色匹配比例阈值"},
        ],
        "desc": "颜色检测条件节点",
    },
    "NumberConditionNode": {
        "params": [
            {"name": "language", "type": "string", "default": "简体中文", "desc": "OCR语言"},
            {"name": "preprocess_mode", "type": "string", "default": "默认", "desc": "预处理模式"},
            {"name": "extract_mode", "type": "string", "default": "无规则", "desc": "数字提取模式"},
            {"name": "extract_pattern", "type": "string", "default": "", "desc": "提取正则模式"},
            {"name": "min_confidence", "type": "float", "default": 50, "desc": "最小识别置信度（0-100）"},
            {"name": "value_key", "type": "string", "default": "last_number_value",
             "desc": "数值存储黑板键名"},
            {"name": "compare_mode", "type": "string", "default": ">=",
             "desc": "比较运算符：>、<、>=、<=、==、!="},
            {"name": "threshold", "type": "float", "default": 0, "desc": "比较目标值"},
            {"name": "search_direction", "type": "string", "default": "左上", "desc": "搜索方向"},
        ],
        "desc": "数字比较条件节点",
    },
    "VariableConditionNode": {
        "params": [
            {"name": "variable_name", "type": "string", "default": "", "desc": "要判断的变量名"},
            {"name": "operator", "type": "string", "default": "==",
             "desc": "比较运算符：>、<、>=、<=、==、!=、contains、exists、not_exists"},
            {"name": "compare_type", "type": "string", "default": "constant",
             "desc": "比较类型：constant（常量）/ variable（变量）"},
            {"name": "compare_value", "type": "string", "default": "",
             "desc": "比较值（compare_type=constant时）"},
            {"name": "compare_variable", "type": "string", "default": "",
             "desc": "比较变量名（compare_type=variable时）"},
        ],
        "desc": "变量判断条件节点（不涉及屏幕）",
    },
    "TextExtractNode": {
        "params": [
            {"name": "language", "type": "string", "default": "简体中文", "desc": "OCR语言"},
            {"name": "preprocess_mode", "type": "string", "default": "默认", "desc": "预处理模式"},
            {"name": "extract_mode", "type": "string", "default": "全部",
             "desc": "提取模式：全部/关键词"},
            {"name": "keywords", "type": "string", "default": "",
             "desc": "提取关键词（extract_mode=关键词时）"},
            {"name": "output_key", "type": "string", "default": "last_extracted_text",
             "desc": "提取文本存储黑板键名"},
            {"name": "save_all_text", "type": "bool", "default": False, "desc": "是否保存全部OCR文本"},
            {"name": "all_text_key", "type": "string", "default": "all_ocr_text",
             "desc": "全部文本存储黑板键名"},
        ],
        "desc": "文本提取节点",
    },
    "HTTPRequestNode": {
        "params": [
            {"name": "url", "type": "string", "default": "", "desc": "请求URL"},
            {"name": "method", "type": "string", "default": "GET",
             "desc": "HTTP方法：GET/POST/PUT/DELETE"},
            {"name": "body", "type": "string", "default": "", "desc": "请求体"},
            {"name": "headers", "type": "dict", "default": {}, "desc": "请求头字典"},
            {"name": "timeout_ms", "type": "int", "default": 5000, "desc": "超时毫秒"},
            {"name": "expected_status", "type": "int", "default": 0,
             "desc": "期望HTTP状态码（0=不检查）"},
            {"name": "response_key", "type": "string", "default": "http_response",
             "desc": "响应存储黑板键名"},
        ],
        "desc": "HTTP请求节点",
    },
    "APIConditionNode": {
        "params": [
            {"name": "url", "type": "string", "default": "", "desc": "请求URL"},
            {"name": "method", "type": "string", "default": "GET", "desc": "HTTP方法"},
            {"name": "body", "type": "string", "default": "", "desc": "请求体"},
            {"name": "expected_status", "type": "int", "default": 0,
             "desc": "期望HTTP状态码（0不检查）"},
            {"name": "json_path", "type": "string", "default": "",
             "desc": "响应JSON字段路径（点分，如data.code）"},
            {"name": "expected_value", "type": "any", "default": None, "desc": "期望字段值"},
            {"name": "timeout_ms", "type": "int", "default": 5000, "desc": "超时毫秒"},
            {"name": "headers", "type": "dict", "default": {}, "desc": "请求头"},
        ],
        "desc": "根据HTTP响应内容判断条件是否成立",
    },
    "WebSocketNode": {
        "params": [
            {"name": "url", "type": "string", "default": "",
             "desc": "WebSocket地址（ws://或wss://）"},
            {"name": "action", "type": "string", "default": "send",
             "desc": "操作类型：send/recv"},
            {"name": "message", "type": "string", "default": "",
             "desc": "send模式下发送的消息内容"},
            {"name": "payload_key", "type": "string", "default": "ws_message",
             "desc": "recv模式下接收数据写入黑板的键名"},
            {"name": "timeout_ms", "type": "int", "default": 1000,
             "desc": "recv模式下接收超时毫秒"},
        ],
        "desc": "WebSocket客户端节点：发送或接收消息",
    },
    "MessagePublishNode": {
        "params": [
            {"name": "topic", "type": "string", "default": "",
             "desc": "消息主题（可相对，配合prefix_tree_id自动加bt.{tree_id}.前缀）"},
            {"name": "payload", "type": "dict", "default": {},
             "desc": "静态负载字典"},
            {"name": "payload_key", "type": "string", "default": "",
             "desc": "黑板键名（若指定则用黑板值覆盖payload）"},
            {"name": "prefix_tree_id", "type": "bool", "default": True,
             "desc": "是否自动加上bt.{tree_id}.前缀"},
        ],
        "desc": "向消息总线发布消息",
    },
    "MessageSubscribeNode": {
        "params": [
            {"name": "topic", "type": "string", "default": "",
             "desc": "订阅主题（支持通配符，如bt.test.**）"},
            {"name": "payload_key", "type": "string", "default": "last_message",
             "desc": "接收消息data写入黑板的键名"},
            {"name": "timeout_ms", "type": "int", "default": 0,
             "desc": "等待超时毫秒（仅blocking模式生效）"},
            {"name": "wait_mode", "type": "string", "default": "nonblocking",
             "desc": "等待模式：nonblocking（非阻塞，未收到即FAILURE）/ blocking（阻塞等待）"},
        ],
        "desc": "等待并接收消息总线上的消息",
    },
}

# 装饰参数（条件节点通用）
_CONDITION_DECORATOR_PARAMS = [
    {"name": "invert", "type": "bool", "default": False, "desc": "条件结果取反"},
    {"name": "retry_count", "type": "int", "default": 0, "desc": "失败重试次数（-1=无限）"},
    {"name": "timeout_ms", "type": "int", "default": 0, "desc": "超时毫秒（0=不超时）"},
    {"name": "check_interval_ms", "type": "int", "default": 300, "desc": "检测间隔毫秒"},
    {"name": "region", "type": "list/string", "default": None,
     "desc": "检测区域 [x1,y1,x2,y2]"},
    {"name": "region_mode", "type": "string", "default": "fixed",
     "desc": "区域模式：fixed（固定区域）/ dynamic（动态区域）"},
    {"name": "region_offset", "type": "list", "default": [-50, -50, 50, 50],
     "desc": "动态区域偏移 [x1,y1,x2,y2]"},
    {"name": "region_use_last_pos", "type": "bool", "default": True,
     "desc": "动态区域是否使用上次检测位置"},
    {"name": "region_anchor", "type": "string", "default": "",
     "desc": "动态区域锚点黑板键名"},
    {"name": "offset", "type": "list", "default": None, "desc": "坐标偏移 [dx,dy]"},
    {"name": "offset_x", "type": "int", "default": 0, "desc": "X坐标偏移"},
    {"name": "offset_y", "type": "int", "default": 0, "desc": "Y坐标偏移"},
    {"name": "save_position", "type": "bool", "default": True,
     "desc": "是否保存检测位置到黑板"},
    {"name": "position_key", "type": "string", "default": "",
     "desc": "位置存储黑板键名（空则用默认键last_detection_position）"},
]

# 动作节点通用装饰参数
_ACTION_DECORATOR_PARAMS = [
    {"name": "retry_count", "type": "int", "default": 0, "desc": "失败重试次数（-1=无限）"},
    {"name": "repeat_count", "type": "int", "default": 0, "desc": "成功重复次数（-1=无限）"},
    {"name": "repeat_interval_ms", "type": "int", "default": 100, "desc": "重复间隔毫秒"},
    {"name": "repeat_interval_ms_random", "type": "int", "default": 0,
     "desc": "重复间隔随机增量毫秒"},
    {"name": "timeout_ms", "type": "int", "default": 0, "desc": "超时毫秒（0=不超时）"},
]

# 已知异步节点集合
# _is_async 是在 __init__ 中设置的实例属性，无法通过类属性探测，
# 因此维护此显式集合来标识异步节点；新增异步节点时只需追加到此集合。
_KNOWN_ASYNC_NODES = {"HTTPRequestNode"}


class NodeSpecExporter:
    """从 NodeRegistry 动态导出节点完整规格"""

    def export_all(self) -> Dict[str, dict]:
        """遍历所有注册节点，导出真实参数规格

        Returns:
            {node_type: {node_type, category, base_class, parameters, description, is_async}}
        """
        specs = {}
        for node_type, node_class in NodeRegistry.list_types().items():
            specs[node_type] = self.export_one(node_type, node_class)
        return specs

    def export_one(self, node_type: str, node_class: Type[Node]) -> dict:
        """导出单个节点规格"""
        category = self._get_category(node_class)
        base_class = self._get_base_class(node_class)

        # 从文档表获取参数
        param_docs = _NODE_PARAM_DOCS.get(node_type, {})
        parameters = list(param_docs.get("params", []))

        # 条件节点追加装饰参数
        if category == "condition":
            parameters = parameters + _CONDITION_DECORATOR_PARAMS

        # 动作节点追加装饰参数
        if category == "action":
            parameters = parameters + _ACTION_DECORATOR_PARAMS

        return {
            "node_type": node_type,
            "category": category,
            "base_class": base_class,
            "parameters": parameters,
            "description": param_docs.get("desc", node_class.__doc__ or ""),
            "is_async": node_type in _KNOWN_ASYNC_NODES,
        }

    def _get_category(self, node_class: Type[Node]) -> str:
        """获取节点分类"""
        if issubclass(node_class, CompositeNode):
            return "composite"
        if issubclass(node_class, ConditionNode):
            return "condition"
        if issubclass(node_class, ActionNode):
            return "action"
        return "other"

    def _get_base_class(self, node_class: Type[Node]) -> str:
        """获取基类名"""
        for base in (CompositeNode, ConditionNode, ActionNode):
            if issubclass(node_class, base):
                return base.__name__
        return "Node"

    def export_for_prompt(self) -> str:
        """导出为 LLM 可读的文本格式"""
        specs = self.export_all()
        lines = []
        for category in ("composite", "condition", "action", "other"):
            cat_nodes = {k: v for k, v in specs.items() if v["category"] == category}
            if not cat_nodes:
                continue
            lines.append(f"\n### {category.upper()} 节点\n")
            for node_type, spec in cat_nodes.items():
                lines.append(f"**{node_type}**: {spec['description']}")
                if spec["parameters"]:
                    param_strs = []
                    for p in spec["parameters"]:
                        default = f'="{p["default"]}"' if isinstance(p["default"], str) else f"={p['default']}"
                        param_strs.append(f'{p["name"]}{default}({p["desc"]})')
                    lines.append(f"  参数: {', '.join(param_strs)}")
                lines.append("")
        return "\n".join(lines)
