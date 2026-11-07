# AutoDoor 行为树系统 — 视觉素材制作与 CLI 参考

> 适用版本：**V2.0.0 及以上**
> 面向对象：需要在无 GUI 环境下制作 / 校验视觉素材、或把这些步骤交给脚本与 AI Agent 执行的用户。

***

## 1 两个入口

同一套命令有两个入口，参数完全一致：

| 场景 | 入口 | 说明 |
| --- | --- | --- |
| 源码环境 | `venv\Scripts\python.exe cli.py <命令>` | 功能最全，可随时改代码 |
| 免安装包 | `autodoor-cli.exe <命令>` | 与图形版同一目录，共享 `_internal` 运行时 |

```bat
:: 源码环境
cd /d D:\workspace\autodoor_behavior_tree
venv\Scripts\python.exe cli.py plugin list

:: 免安装包
cd /d D:\tools\autodoor
autodoor-cli.exe plugin list
```

> 图形版 `autodoor-behaviortree.exe` 不带控制台，**不能**用来执行 CLI 命令——它没有 stdout，自动化脚本读不到任何输出。

***

## 2 命令总表

| 命令 | 作用 | 常用子命令 |
| --- | --- | --- |
| `run` | 运行行为树 | `--headless` `--plugins` `--project` `--rest` `--ws` |
| `status` | 查询运行状态 | — |
| `stop` | 停止运行 | — |
| `schedule` | 定时调度 | 增删查 |
| `daemon` | 守护进程模式 | — |
| `remote` | 远程控制 | — |
| `plugin` | 插件管理 | `list` `nodes` `load` `start` `stop` `unload` |
| `assets` | 视觉素材清单 | `add` `verify` `list` |
| `config` | 配置读写 | `get` `set` `list` |
| `ai` | AI 编排流水线 | 意图分析、节点选型、生成、校验 |

`plugin` 与 `assets` 是 V2.0.0 的重点，下面展开。

***

## 3 制作期标准流程

一条视觉自动化的完整制作链路，共六步：

```text
截图 / 定位目标
      ↓
assets add 登记素材（裁剪 + 主色 + 坐标）
      ↓
在树里配置图像匹配 / 颜色检测节点
      ↓
assets verify 校验清单与模板一致性
      ↓
run --headless --plugins 无界面试跑
      ↓
看日志微调阈值 / 缩放范围
```

### 3.1 第一步：取得截图

两种方式，任选其一：

```bash
# 方式 A：直接截屏（推荐，自动记录屏幕坐标原点）
autodoor-cli assets add --name save_btn --capture 100,200,700,600 \
  --bbox 120,140,180,180 --semantic "保存按钮"

# 方式 B：用已有图片
autodoor-cli assets add --name save_btn --source shots\main.png \
  --origin 0,0 --bbox 120,140,180,180 --semantic "保存按钮"
```

`--capture` 接受 `<x1,y1,x2,y2>`，截取的是**虚拟桌面**范围（多显示器也覆盖）。`--origin` 只在方式 B 需要：告诉工具这张图左上角在屏幕的哪个位置。

### 3.2 第二步：把粗框精修成模板

如果坐标来自视觉大模型（误差通常 20–50 px），用 `--refine-color` 按颜色连通域收紧：

```bash
autodoor-cli assets add --name target --source shots\aim.png --origin 0,0 \
  --bbox 900,480,1020,600 \
  --refine-color "#d93b3b" --refine-expand 3.0 --refine-tolerance 50 \
  --semantic "红色圆环靶心"
```

- `--refine-expand`：在粗框基础上向外扩几倍再找颜色，太小会截断目标（默认 3.0）
- `--refine-tolerance`：颜色容差（默认 50）
- 精修未命中时**不会失败**，只打一条 `[WARN] 精定位未命中，沿用原始粗框`，此时应人工核对截图

### 3.3 第三步：在树里使用

节点参数指向模板，或直接用清单里的主色：

| 想做的事 | 节点 | 关键参数 |
| --- | --- | --- |
| 找这个按钮 | 图像匹配 | `template_path` = `assets/templates/save_btn.png`，`threshold` = 80 |
| 主色足够独特 | 颜色检测 | `target_color` = 清单里的 `dominant_color` |
| 尺寸可能不同 | 图像匹配 + 多尺度 | `multi_scale` = true，`scale_range` = `0.85,1.15` |

### 3.4 第四步：校验

```bash
autodoor-cli assets verify --project D:\my_project
```

输出会逐条标 `OK` / `ERR`，有 ERR 时退出码为 1，可直接挡在发布前。

### 3.5 第五步：无界面试跑

```bash
autodoor-cli run tree.json --headless --plugins --project D:\my_project
```

`--plugins` 不能漏——不加它，树里的 `vlm_vision.*`、`uia_bridge.*` 等插件节点不会被注册。

### 3.6 第六步：看日志调阈值

日志在应用主目录的 `logs/`（源码版是项目根，免安装版是 exe 同级）。重点看两类行：

- `未找到匹配模板 (阈值: 0.8, 最高置信度: 0.62)` → 阈值偏高或模板已失效
- `多尺度命中 scale=1.10` → 当前显示缩放与制作时不同

***

## 4 assets 命令详解

### 4.1 add 参数

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `--name` | 是 | 素材名，同时是模板文件名（`assets/templates/<name>.png`） |
| `--bbox` | 是 | 裁剪框，**源图内坐标** `x1,y1,x2,y2` |
| `--source` | 二选一 | 源图路径（相对路径先按 cwd、再按项目根解析） |
| `--capture` | 二选一 | 直接截屏，`x1,y1,x2,y2`（屏幕坐标） |
| `--origin` | 否 | 源图左上角对应的屏幕坐标 `x,y`；`--capture` 时自动推定 |
| `--semantic` | 否 | 语义描述，写进清单，供人工核对与追溯 |
| `--color` | 否 | 指定主色 `#RRGGBB`；缺省自动提取 |
| `--anchor` | 否 | `center`（默认）/ `topleft` |
| `--refine-color` | 否 | 精定位颜色，触发连通域收紧 |
| `--refine-expand` | 否 | 精定位外扩倍数，默认 3.0 |
| `--refine-tolerance` | 否 | 精定位颜色容差，默认 50 |
| `--hwnd` | 否 | 目标窗口句柄，用于换算客户区相对坐标 |
| `--offset` | 否 | 窗口客户区屏幕原点 `x,y`（无 hwnd 时替代） |
| `--project` | 否 | 项目根目录，默认当前目录 |
| `--manifest` | 否 | 清单路径，默认 `<project>/assets/manifest.json` |

### 4.2 三个典型调用

**纯色控件（主色独特）**

```bash
autodoor-cli assets add --name confirm_btn --capture 0,0,1920,1080 \
  --bbox 820,600,900,640 --color "#2f6fd0" --semantic "确认按钮"
```

**模板图（有纹理、需要匹配）**

```bash
autodoor-cli assets add --name logo --source shots\login.png --origin 0,0 \
  --bbox 640,200,960,260 --semantic "登录页 Logo"
```

**绑定窗口（后台运行，要客户区坐标）**

```bash
autodoor-cli assets add --name export_btn --capture 0,0,1920,1080 \
  --bbox 1200,300,1280,340 --hwnd 658716 --semantic "导出按钮"
```

`--hwnd` 是十进制整数——用 `type=int` 解析，**不接受** `0x` 十六进制写法。可用 AutoDoor 图形界面「窗口绑定」功能取句柄，或在 Python 里 `print(int(hwnd))` 转换后填入。

### 4.3 verify 与 list

```bash
autodoor-cli assets verify       # 逐条校验，有 ERR 返回 1
autodoor-cli assets list         # 打印清单摘要
```

`verify` 的检查项：

| 级别 | 触发条件 |
| --- | --- |
| ERR | 名称重复；模板文件不存在或打不开；模板实际尺寸与清单声明不符；`bbox_screen` 缺失 / 非法；主色不是合法十六进制 |
| WARN | `bbox_screen` 宽高与模板尺寸不一致；缺主色（无法用颜色节点）；缺语义描述 |

### 4.4 manifest 字段

```json
{
  "version": 1,
  "created_at": "2026-11-07T10:12:33",
  "updated_at": "2026-11-07T10:12:33",
  "targets": [
    {
      "name": "save_btn",
      "semantic": "保存按钮",
      "template": "assets/templates/save_btn.png",
      "kind": "template",
      "template_size": [60, 40],
      "bbox_image": [120, 140, 180, 180],
      "bbox_screen": [120, 140, 180, 180],
      "center_screen": [150, 160],
      "coord_client": [410, 260],
      "anchor": "center",
      "dominant_color": "#d93b3b",
      "color_ratio": 0.81,
      "source_image": "assets/raw/screen_20261107_101233.png",
      "source_origin": [0, 0],
      "hwnd": null,
      "updated_at": "2026-11-07T10:12:33"
    }
  ]
}
```

| 字段 | 用途 |
| --- | --- |
| `bbox_image` | 模板在源图中的位置，重建素材时用 |
| `bbox_screen` / `center_screen` | 屏幕绝对坐标，未绑窗口时鼠标节点用 |
| `coord_client` | 客户区相对坐标，绑窗口时用 |
| `dominant_color` / `color_ratio` | 可直接喂给颜色检测节点 |
| `source_image` / `source_origin` | 追溯源图，也是坐标换算依据 |
| `kind` | `template`（有模板图）/ `anchor`（UIA 采样产物，仅坐标） |

> 同名素材再次 `add` 会**覆盖**该条目，`created_at` 保留。

***

## 5 plugin 命令

### 5.1 让 AI 或人先看清有什么节点

```bash
autodoor-cli plugin list      # 插件清单
autodoor-cli plugin nodes     # 节点类型 + 完整参数 schema
```

`plugin nodes` 的输出是写树文件时的权威依据：插件节点在 JSON 里必须写成 `{插件名}.{节点类型}`，例如：

```json
{
  "id": "n7",
  "type": "math_expressions.ExpressionNode",
  "config": {
    "expression_x": "move_x = gx - 960",
    "expression_y": "move_y = gy - 540"
  }
}
```

写错成 `ExpressionNode` 会在加载时提示节点类型未知。

### 5.2 启停与装载

```bash
autodoor-cli plugin load D:\my_plugins\my_plugin
autodoor-cli plugin start my_plugin
autodoor-cli plugin stop my_plugin
autodoor-cli plugin unload my_plugin
```

- 插件在 `start` 之后才注册节点
- 插件目录默认是应用主目录下的 `plugins/`，可用环境变量 `AUTODOOR_PLUGINS_DIR` 覆盖（多实例 / CI 隔离时有用）

***

## 6 常见问题

**Q1：命令敲完没反应，直接弹出了图形界面**

命令名不在 CLI 白名单里。V2.0.0 已把白名单统一到 `cli.COMMAND_NAMES`（共 10 项）。若自己新增了子命令，必须同步加进该表，否则打包版会把它当 GUI 参数。

**Q2：`assets add` 报 `bbox 超出源图尺寸`**

`--bbox` 是**源图内**坐标，不是屏幕坐标。用 `--capture` 截的图，其内部坐标 = 屏幕坐标 − `origin`；若 `--capture 0,0,1920,1080`，两者才恰好相同。

**Q3：登记成功了，运行却点错位置**

三种可能，按顺序排查：

1. 制作时与运行时的**显示缩放**不同 → 开 `multi_scale`
2. 运行环境有**副屏在左 / 在上**（虚拟桌面原点为负）→ 确认版本 ≥ 2.0.0，该缺陷已修
3. 树节点绑定了窗口，但素材登记时没用 `--hwnd` / `--offset` → 客户区坐标缺失，鼠标按屏幕坐标点了

**Q4：清单里主色是空的**

`--color` 未指定且自动提取失败（模板几乎纯透明或全黑）。这类模板也不适合颜色兜底，建议改用 `--refine-color` 重做或直接依赖模板匹配。

**Q5：管道读取 CLI 输出是乱码**

V2.0.0 起，非交互场景（管道 / 重定向）自动切 UTF-8；交互式控制台保持系统代码页。若仍乱码，请确认调用的是 V2.0.0 及以上版本，并在读取端按 UTF-8 解码。

**Q6：`verify` 通过，但跑起来还是找不到目标**

`verify` 只校验清单与文件的一致性，不校验"这个模板在当前屏幕上能否匹配到"。后者要用 `run --headless` 实跑并看置信度。

***

## 7 一页速查

```bash
# 制作
autodoor-cli assets add --name X --capture 0,0,1920,1080 --bbox x1,y1,x2,y2 --semantic "说明"
autodoor-cli assets verify
autodoor-cli assets list

# 查能力
autodoor-cli plugin list
autodoor-cli plugin nodes

# 试跑
autodoor-cli run tree.json --headless --plugins --project <项目根>

# 排错
dir logs\*.txt                       # 源码版
dir <exe目录>\logs\*.txt             # 免安装版
```

***

*文档版本：1.0（随 V2.0.0 新增）*
*最后更新：2026-11-07*
