# AutoDoor 行为树系统

<div align="center">

一个独立的可视化行为树编辑与执行框架，面向 Windows 平台的自动化场景

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)](https://www.microsoft.com/windows)

</div>

***

## 📖 项目简介

AutoDoor 行为树系统是一个功能完整的可视化行为树编辑与执行框架，专为 Windows 平台的自动化场景设计（应用辅助、RPA 流程等）。系统提供图形化编辑器、丰富的节点类型、脚本录制、OCR 识别、多种输入引擎等能力。

### ✨ 核心特性

| 特性                   | 说明                                     |
| -------------------- | -------------------------------------- |
| 🎨 **可视化编辑器**        | 基于 CustomTkinter 的节点式编辑器，支持拖拽、连线、缩放、框选 |
| ⚙️ **行为树引擎**         | 独立线程执行，支持启动/暂停/停止/恢复                   |
| 📑 **多 Tab 并行**      | 多行为树同时编辑与并行运行，独立画布/引擎/黑板               |
| 🧩 **24 种内置节点**      | 1 种开始节点 + 5 种组合节点 + 6 种条件节点 + 12 种动作节点 |
| 📊 **黑板系统**          | 观察者模式的数据共享机制，节点间解耦通信                   |
| 💾 **序列化**           | JSON/YAML/TXT 多格式持久化，版本化数据结构           |
| ↩️ **撤销/重做**         | Command 模式，支持 100 步历史                  |
| 🎮 **DD 虚拟键盘**       | DD级硬件模拟输入，绕过大多数输入检测                    |
| 👁️ **OCR 集成**       | 内嵌 RapidOCR，基于 ONNX Runtime，支持中英文识别    |
| 📝 **脚本录制**          | TXT 脚本录制与回放                            |
| 📦 **PyInstaller打包** | PyInstaller 打包，内置 DD64.dll、IbInputSimulator.dll 等驱动 |

***

## 💰 赞赏

如果这款工具对你有所帮助，欢迎赞助以助力老王对它的长期维护。如果需要定制或者其他帮助，也可以联系作者。

<div align="center">

![赞赏二维码](assets/appreciation.png)

</div>

***

## **联系作者**

QQ群：298117299 进群密码：autodoor
B站主页：<https://space.bilibili.com/263150759>

***

## 🛠️ 技术栈

```
Python 3.12+
├── GUI 框架:    CustomTkinter + Tkinter Canvas
├── 图像处理:    Pillow, OpenCV, imagehash
├── OCR 引擎:    RapidOCR + ONNX Runtime 1.19.0
├── 输入模拟:    PyAutoGUI / DD虚拟键盘 / IbInputSimulator / 后台消息
├── 音频播放:    pygame.mixer
├── 打包工具:    PyInstaller
└── CI/CD:       GitHub Actions
```

***

## 🏗️ 系统架构

### 分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    表现层                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ 行为树    │  │ 脚本录制  │  │  设置    │              │
│  │ 编辑器    │  │  标签页   │  │  标签页  │              │
│  └──────────┘  └──────────┘  └──────────┘              │
├─────────────────────────────────────────────────────────┤
│                    应用层                   │
│  ┌──────────────────────────────────────────┐           │
│  │         BehaviorTreeEditor               │           │
│  │  (编辑器编排: 工具栏/画布/面板/撤销重做)  │           │
│  └──────────────────────────────────────────┘           │
├─────────────────────────────────────────────────────────┤
│                    领域层                        │
│  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐   │
│  │ 节点   │ │ 执行引擎  │ │  黑板    │ │  序列化器  │   │
│  │ 模型   │ │  Engine   │ │Blackboard│ │ Serializer│   │
│  └────────┘ └──────────┘ └──────────┘ └───────────┘   │
├─────────────────────────────────────────────────────────┤
│                  基础设施层              │
│  ┌──────────┐ ┌────────────┐ ┌───────────┐             │
│  │ 输入控制  │ │ 截图管理器  │ │ OCR 管理器 │             │
│  │InputCtrl │ │Screenshot  │ │OCRManager │             │
│  └──────────┘ └────────────┘ └───────────┘             │
└─────────────────────────────────────────────────────────┘
```

### 模块结构

```
autodoor_behavior_tree/
├── main.py                    # 应用入口
├── bt_core/                   # 核心领域层
│   ├── nodes.py               # 节点抽象与实现
│   ├── engine.py              # 行为树执行引擎
│   ├── blackboard.py          # 黑板系统
│   ├── context.py             # 执行上下文
│   ├── serializer.py          # 序列化/反序列化
│   ├── registry.py            # 节点类型注册中心
│   ├── config.py              # 节点配置数据类
│   └── status.py              # 节点状态枚举
├── bt_nodes/                  # 具体节点实现
│   ├── actions/               # 动作节点
│   │   ├── keyboard.py        #   按键节点
│   │   ├── mouse.py           #   鼠标节点
│   │   ├── scroll.py          #   滚轮节点
│   │   ├── delay.py           #   延时节点
│   │   ├── variable.py        #   变量节点
│   │   ├── script.py          #   脚本节点
│   │   ├── code.py            #   代码节点
│   │   ├── alarm.py           #   报警节点
│   │   ├── text_input.py      #   文本输入节点
│   │   ├── start_tree.py      #   启动树节点
│   │   └── stop_tree.py       #   停止树节点
│   └── conditions/            # 条件节点
│       ├── ocr.py             #   文字检测节点
│       ├── image.py           #   图像匹配节点
│       ├── color.py           #   颜色检测节点
│       ├── number.py          #   数字比较节点
│       ├── variable.py        #   变量判断节点
│       └── text_extract.py    #   文本提取节点
├── bt_gui/                    # GUI 表现层
│   ├── app.py                 #   主应用窗口
│   ├── theme.py               #   主题与样式
│   ├── widgets.py             #   通用组件
│   ├── script_tab.py          #   脚本录制标签页
│   ├── settings_tab.py        #   设置标签页
│   └── bt_editor/             #   行为树编辑器
│       ├── editor.py          #     编辑器主控
│       ├── canvas.py          #     画布（节点/连线/交互）
│       ├── node_item.py       #     节点视觉项
│       ├── palette.py         #     节点面板
│       ├── property.py        #     属性面板
│       ├── toolbar.py         #     工具栏
│       ├── tab_bar.py         #     Tab 栏组件
│       ├── gui_tab_manager.py #     多 Tab 管理器
│       ├── undo_redo.py       #     撤销/重做系统
│       └── constants.py       #     节点类型常量
├── bt_utils/                  # 基础设施层
│   ├── input_controller_factory.py  #   输入控制器工厂（支持4种引擎）
│   ├── dd_input.py            #   DD 虚拟键盘控制
│   ├── ib_input.py            #   IB 输入模拟器
│   ├── bg_input.py            #   后台消息输入
│   ├── input_manager.py       #   输入管理器
│   ├── screenshot.py          #   截图管理器
│   ├── screen_service.py      #   屏幕服务
│   ├── ocr_manager.py         #   OCR 管理器
│   ├── alarm.py               #   报警播放器
│   ├── image_processor.py     #   图像处理工具
│   ├── magnifier.py           #   屏幕放大镜
│   ├── offset_tool.py         #   偏移量工具
│   ├── recorder.py            #   脚本录制器
│   ├── script_executor.py     #   脚本执行器
│   ├── log_manager.py         #   日志管理器
│   ├── auto_save.py           #   自动保存
│   ├── crash_recovery.py      #   崩溃恢复
│   ├── global_hotkey.py       #   全局热键
│   ├── resource_service.py    #   资源管理服务
│   ├── resource_importer.py   #   资源文件自动导入
│   ├── resource_manager.py    #   资源管理器
│   ├── path_resolver.py       #   路径解析
│   ├── project_manager.py     #   项目生命周期管理
│   ├── package_exporter.py    #   项目打包导出
│   ├── package_importer.py    #   从 ZIP 导入项目
│   └── ...
├── config/                    # 配置管理
│   ├── settings.json          #   默认设置
│   └── settings_manager.py    #   设置管理器
├── drivers/                   # 驱动文件
│   ├── DD64.dll               #   DD虚拟键盘驱动
│   └── IbInputSimulator.dll   #   IB输入模拟器驱动
├── assets/                    # 资源文件
│   ├── icons/                 #   图标
│   └── sounds/                #   音效
└── ...
```

***

## 🚀 快速开始

### 环境要求

- Python 3.12 或更高版本
- Windows 操作系统
- Visual C++ Redistributable（OCR 功能依赖）

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行应用

```bash
python main.py
```

### 打包应用

```bash
build.bat
```

***

## 🧩 节点类型

### 组合节点

| 节点               | 说明                                   |
| ---------------- | ------------------------------------ |
| **StartNode**    | 开始节点 - 行为树根节点，顺序执行子节点，失败后继续执行        |
| **SequenceNode** | 顺序节点 - 按顺序执行子节点，所有子节点成功才返回成功         |
| **SelectorNode** | 选择节点 - 按顺序执行子节点，任一成功即返回成功            |
| **ParallelNode** | 并行节点 - 同时执行所有子节点，根据策略决定成功条件          |
| **RandomNode**   | 随机节点 - 随机执行子节点，根据策略决定成功条件            |
| **SubtreeNode**  | 子树引用节点 - 引用外部行为树文件作为子树执行，支持循环检测与黑板隔离 |

### 条件节点

| 节点                        | 说明                        |
| ------------------------- | ------------------------- |
| **OCRConditionNode**      | 文字检测节点 - 检测屏幕指定区域是否包含目标文字 |
| **ImageConditionNode**    | 图像匹配节点 - 检测屏幕是否匹配目标图像模板   |
| **ColorConditionNode**    | 颜色检测节点 - 检测屏幕指定区域是否包含目标颜色 |
| **NumberConditionNode**   | 数字比较节点 - 识别屏幕数字并与目标值比较    |
| **VariableConditionNode** | 变量判断节点 - 判断黑板变量值是否满足条件    |
| **TextExtractNode**       | 文本提取节点 - OCR识别并提取文本到黑板变量  |

### 动作节点

| 节点                  | 说明                            |
| ------------------- | ----------------------------- |
| **KeyPressNode**    | 按键节点 - 执行键盘按键操作               |
| **MouseClickNode**  | 鼠标点击节点 - 执行鼠标点击操作（支持无限点击）     |
| **MouseMoveNode**   | 鼠标移动节点 - 移动鼠标到指定位置（支持拖拽）      |
| **MouseScrollNode** | 鼠标滚动节点 - 执行鼠标滚轮操作             |
| **DelayNode**       | 延时节点 - 等待指定时间                 |
| **SetVariableNode** | 设置变量节点 - 设置/修改黑板变量            |
| **ScriptNode**      | 脚本节点 - 执行外部脚本文件               |
| **CodeNode**        | 代码节点 - 执行外部程序                 |
| **AlarmNode**       | 报警节点 - 播放报警音效                 |
| **TextInputNode**   | 文本输入节点 - 逐字符输入文本（支持提取值/预设/文件） |
| **StartTreeNode**   | 启动树节点 - 启动其他已加载的行为树           |
| **StopTreeNode**    | 停止树节点 - 停止当前或其他行为树             |

***

## 🎯 核心功能

### 1. 可视化编辑器

- **节点拖拽**：从节点面板拖拽节点到画布
- **连线操作**：从输出端口拖拽到输入端口创建连线
- **框选移动**：框选多个节点批量移动
- **缩放平移**：滚轮缩放，右键拖拽平移画布
- **属性编辑**：选中节点后在属性面板编辑配置

### 2. 行为树执行

- **独立线程**：行为树在独立线程中执行，不阻塞 UI
- **状态可视化**：实时显示节点执行状态（成功/失败/运行中）
- **暂停恢复**：支持暂停和恢复执行
- **黑板系统**：节点间通过黑板共享数据

### 2.1 多 Tab 并行

- **多项目编辑**：通过 Tab 栏同时打开多个行为树项目
- **并行执行**：多个行为树在独立线程中真正并行运行
- **独立隔离**：每个 Tab 拥有独立的画布、引擎、黑板、撤销/重做
- **一键运行**：顶部"开始"按钮运行所有 Tab，Tab 内按钮运行单个
- **持久化**：关闭应用后自动保存 Tab 列表，下次启动恢复
- **快捷键**：F10 运行所有 Tab，F12 停止所有 Tab

### 3. 撤销/重做系统

- 支持 100 步历史记录
- 所有编辑操作均可撤销/重做
- Command 模式实现

### 4. 自动保存与崩溃恢复

- 定时自动保存（默认 30 秒）
- 启动时自动恢复上次编辑状态
- 静默恢复，无需用户确认

### 4.1 资源管理安全机制

手动保存时执行未引用资源清理，遵循以下安全原则：

- **截图目录保护**：`images/screenshots/` 不纳入清理扫描范围，避免截图预览被误删
- **子树资源保护**：`subtree_path` 引用的子树目录下所有文件递归收集到引用集合，避免子树资源被误删
- **路径规范化**：所有路径比较经过 `os.path.normpath` 统一分隔符，避免 Windows 下正斜杠/反斜杠不一致导致误判
- **移动到缓存**：未引用资源文件移动到 `cache/` 目录而非直接删除，支持通过 `restore_from_cache()` 恢复
- **延迟替换**：更换截图/文件时，仅在新文件成功导入后才将旧文件移到缓存，操作失败时旧文件完好保留

### 5. OCR 识别功能

- 基于 RapidOCR 引擎，识别速度快
- 支持中英文混合识别
- 支持关键词定位，返回关键词中心坐标
- 支持图像预处理（默认/复杂色彩/自适应/自动调优）
- 支持数字提取与比较

***

## ⌨️ 快捷键

| 快捷键                       | 功能          |
| ------------------------- | ----------- |
| `Ctrl+Z`                  | 撤销          |
| `Ctrl+Y` / `Ctrl+Shift+Z` | 重做          |
| `Ctrl+S`                  | 保存          |
| `Ctrl+Shift+S`            | 另存为         |
| `Ctrl+O`                  | 打开          |
| `Ctrl+N`                  | 新建          |
| `Ctrl+C`                  | 复制选中节点      |
| `Ctrl+V`                  | 粘贴节点        |
| `Ctrl+X`                  | 剪切节点        |
| `Ctrl+D`                  | 复制并粘贴（快速复制） |
| `Delete` / `Backspace`    | 删除选中        |

***

## 🔧 配置管理

### 默认配置结构

```json
{
  "alarm_sound_path": "",
  "alarm_volume": 70,
  "shortcuts": {
    "start": "F10",
    "stop": "F12",
    "record": "F11"
  },
  "behavior_tree": {
    "tick_interval": 10,
    "auto_save_interval": 30,
    "default_format": "json"
  },
  "ui": {
    "theme": "dark",
    "language": "zh_CN",
    "font_size": 10
  }
}
```

***

## 📦 打包与部署

| 版本      | Spec 文件            | 输出名称                          | 特殊包含                                            |
| ------- | ------------------ | ----------------------------- | ----------------------------------------------- |
| release | `autodoor_bt.spec` | `autodoor-behaviortree-{ver}` | rapidocr, onnxruntime, DD64.dll, assets, config |

### 打包大小（约 306 MB）

| 组件           | 大小       |
| ------------ | -------- |
| OpenCV (cv2) | \~138 MB |
| NumPy + libs | \~41 MB  |
| ONNX Runtime | \~27 MB  |
| RapidOCR     | \~16 MB  |
| 其他依赖         | \~84 MB  |

### GitHub Actions CI/CD

项目包含 GitHub Actions 工作流配置，支持自动构建和发布：

1. 触发条件：push tag / manual dispatch
2. 版本号提取：从 build\_config.json 读取
3. 模块验证：检查关键依赖
4. RapidOCR 验证：确认 OCR 引擎正确安装
5. 统一构建：PyInstaller --clean
6. 发布：创建 GitHub Release + 上传产物

***

## 🤖 DSH 集成（AI Agent 驱动）

本项目配套一个独立的 DSH（DeepSeek Harness）集成仓库，把 AutoDoor 的能力封装为 **12 个模型工具**，
可以在 Agent 对话里用自然语言驱动桌面自动化：

> 🔗 **配套仓库**：<https://github.com/wdhq4261761/autodoor-dsh-integration>（公开）
>
> `dsh_integration\` 目录**不在**本仓库的版本控制内（独立仓库管理），clone 本仓库拿不到 DSH 工具集，请从上面的配套仓库获取。

```
用户(GUI 对话) → DSH Agent(LLM 工具编排) → 12 个 autodoor_* 工具
              → 源码版: venv python cli.py / 打包版: autodoor-cli.exe
              → AutoDoor 引擎(OCR / 视觉 / 键鼠) → 桌面自动化
```

### 12 个工具概览

| 分类 | 工具 |
| --- | --- |
| 能力发现 | `autodoor_list_plugins` / `autodoor_list_nodes` |
| 设计与落盘 | `autodoor_generate` / `autodoor_save_structure` / `autodoor_create_plugin` |
| 素材制作 | `autodoor_assets_add` / `autodoor_assets_verify` |
| 运行与观测 | `autodoor_validate` / `autodoor_run` / `autodoor_status` / `autodoor_read_log` / `autodoor_stop` |

### 快速使用

```bat
:: 1. clone 两个仓库
git clone https://github.com/wdhq4261761/autodoor_behavior_tree.git
git clone https://github.com/wdhq4261761/autodoor-dsh-integration.git

:: 2. 把预设复制到 DSH 用户目录（假设 DSH 已安装）
xcopy /E /Y autodoor-dsh-integration\autodoor_preset\* "%USERPROFILE%\.dsh\.agent-presets\autodoor\"

:: 3. 设置 AutoDoor 根目录（源码版指项目根；打包版指 exe 所在目录），新开进程生效
setx AUTODOOR_ROOT "D:\workspace\autodoor_behavior_tree"

:: 4. 在 DSH profile 中注册预设后，新建会话选择「AutoDoor 自动化」即可
```

> 预设插件按「`AUTODOOR_CLI` → `<AUTODOOR_ROOT>\autodoor-cli.exe` → 源码版 venv」的顺序自动适配，
> 源码版与免安装打包版都可用；打包版必须用 `autodoor-cli.exe`（图形版无 stdout）。
>
> **纯净 PC 从零部署**请看配套仓库里的 [`docs/部署手册-AI-Agent执行版.md`](https://github.com/wdhq4261761/autodoor-dsh-integration/blob/master/docs/部署手册-AI-Agent执行版.md)——
> 面向 AI Agent 的可机读步骤（S1–S8，带成功判据与失败分支），人类可当核对清单用。

***

## 🔌 扩展开发

### 添加自定义节点

1. 创建节点类，继承 `ActionNode` 或 `ConditionNode`
2. 实现 `tick()` / `_execute_action()` / `_check_condition()` 方法
3. 实现 `to_dict()` 和 `from_dict()` 方法
4. 在 `__init__.py` 中注册到 `NodeRegistry`
5. 在 `constants.py` 中添加显示名称和分类
6. 在 `property.py` 中添加配置 Schema

### 示例：自定义动作节点

```python
from bt_core.nodes import ActionNode, NodeStatus
from bt_core.registry import NodeRegistry

class CustomActionNode(ActionNode):
    NODE_TYPE = "CustomAction"
    
    def _execute_action(self, context):
        # 实现自定义逻辑
        return NodeStatus.SUCCESS
    
    def to_dict(self):
        data = super().to_dict()
        # 添加自定义序列化逻辑
        return data
    
    @classmethod
    def from_dict(cls, data):
        node = super().from_dict(data)
        # 添加自定义反序列化逻辑
        return node

# 注册节点
NodeRegistry.register("CustomAction", CustomActionNode)
```

***

## 📄 序列化格式

### JSON 数据结构（v2.0）

```json
{
  "version": "2.0",
  "format_type": "behavior_tree_standalone",
  "metadata": {
    "created_at": "2026-04-09T12:00:00",
    "modified_at": "2026-04-09T12:00:00",
    "app_version": "1.1.0"
  },
  "root_node": "node_1",
  "nodes": {
    "node_1": {
      "id": "node_1",
      "type": "SequenceNode",
      "config": { "name": "顺序", "enabled": true, "extra": {} },
      "children": ["node_2", "node_3"]
    }
  },
  "connections": [
    { "parent_id": "node_1", "child_id": "node_2" },
    { "parent_id": "node_1", "child_id": "node_3" }
  ]
}
```

***

## 🐛 故障排除

### OCR 无法使用

1. 确保已安装 Visual C++ Redistributable 运行时库
2. 程序启动时会自动检测，缺少时会弹出提示
3. 可从微软官网下载安装 VC++ Redistributable
4. OCR 功能不可用时不影响其他功能使用

### DD 虚拟键盘无法使用

1. 确保 `drivers/DD64.dll` 文件存在
2. 检查是否有足够的系统权限
3. 尝试使用管理员权限运行

### 快捷键不生效

1. 确保应用窗口处于活动状态
2. 检查是否有其他应用占用了相同快捷键
3. 删除快捷键在输入框获得焦点时不触发（这是预期行为）

### 打包后程序无法启动

1. 检查是否缺少 Visual C++ Redistributable
2. 查看日志文件确认错误信息
3. 确保杀毒软件未拦截程序

***

## 📚 文档

- [架构文档](doc/01_架构文档.md) - 系统架构和核心组件设计
- [详细实现方法](doc/02_详细实现方法.md) - 节点实现和关键机制
- [技术图表与伪代码](doc/03_技术图表与伪代码.md) - 类图、流程图和算法

***

## 📝 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

***

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

***

<div align="center">

**Made with ❤️ by Flown王砖家**

</div>
