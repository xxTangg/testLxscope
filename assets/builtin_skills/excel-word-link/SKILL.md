---
name: excel-word-link
description: "将本地Excel数据按确认的映射填入Word模板，支持表格坐标、原文定位与占位符，保存映射供下期复用。用于Word自动填充、数据套表、财务附注与报表套打。"
license: MIT
---

## 内网系统适配

本技能使用企业内网模型、用户上传材料与已授权的内部知识库。只读取当前任务资料，不调用公网服务、在线解析或动态安装依赖；缺少本地能力时明确指出缺项。

技能目录使用宿主提供的实际路径（下文以 `$DIR` 表示）；脚本和参考资料按该目录解析，执行脚本使用绝对路径。产物写入当前会话工作区的输出目录，使用绝对路径提供下载；不写入系统共享目录或其他账号的目录。默认用中文交付。

# Excel → Word 联动填充

把 Excel 数据填进 Word，生成成品文档。Excel 改了重跑一次就出新 Word——这就是"联动"。

> 这是**脚本驱动**的联动，不是 Office 原生"粘贴链接"。好处是能算账（合计/占比/同比/会计括号负数）、能保留 Word 格式；代价是数据改完要主动跑一次。

## 核心工作流（用户发来 Word + Excel 时走这条）

**最常见场景**：用户甩来一个 `.docx` 和一个 `.xlsx`，文档**不一定有占位符**（往往是现成的正式文档，带空格/旧值/标签）。按下面五步，**不要**要求用户先去 Word 里插占位符。

### ① 探查——先"看见"两个文件

```bash
python3 scripts/inspect_files.py <word.docx> <excel.xlsx>
```

输出里每个 Word 位置都带**稳定定位 ID**：
- `P{n}`——第 n 个正文段落（如 `P3: 应付金额：0.00`）
- `T{t}R{r}C{c}`——第 t 个表格第 r 行第 c 列（如 `T0R1C1: ·空·`）

Excel 部分列出每个 sheet 的单元格。先读懂两边有什么。

### ② 自动识别——推断对应关系，生成草案

结合探查结果，自己判断「Word 哪个位置该填 Excel 哪个值」。识别线索：
- Word 标签对 Excel 字段名（`公司名称：____` ← Excel 里"公司名称"那行的值）
- 表格行标题/列标题对 Excel 的行列
- 待填痕迹：下划线 `____`、`·空·` 单元格、`0.00`/`XXX` 这类占位文本
- 数字位置 + 量级，判断该用 money / pct / int / text 哪种格式

把识别结果整理成一张**对应关系草案表**（给用户看的，人类可读）：

| # | Word 位置 | 当前内容 | ← Excel 来源 | 拟填值 | 格式 | 把握 |
|---|---|---|---|---|---|---|
| 1 | P1 | `致：____` | 基本信息.客户名称 | 北京华信科技 | text | 高 |
| 2 | T0R1C1 | ·空· | 明细.货款 | 140,000.00 | money | 中 |

### ③ 人工检查——列给用户，标出没把握的

把草案表发给用户，**明确标出低把握项**（一字不差地问："第 2 条我猜表格金额列填货款，对吗？"）。不要默默替用户决定模糊的对应。

### ④ 人工修改——用户增删改

用户会说"第 2 条不对，应填税款""第 5 处不用动""这里改成 X"。据此更新草案。

### ⑤ 填充——按确认后的清单出成品 + 校验

把确认后的草案写成 `mapping.json`（格式见 `references/映射清单格式.md`）。**关键：取值用 `source` 指向 Excel 来源，不要写死具体值**——这样以后换数据时这份 mapping 能直接复用（见下节）。然后跑：

```bash
python3 scripts/apply_mapping.py <mapping.json> <word.docx> <输出.docx> --excel <数据.xlsx>
```

脚本会报告：命中几条、**未命中哪几条**（定位没找到或 Excel 取值失败）、**哪几条发生格式合并**（段内混合格式可能丢，需目检）。

**把 mapping.json 留给用户存档**——它是这份文档的"对应关系记忆"，下期直接复用。

## 复用与模板微调（普适性的关键）

大多数情况模板是**固定的，每期只换数据**。这时 `mapping.json` 是可复用资产，不要每期重新识别：

```
每期（模板没变，只换 Excel 数据）：
  python3 scripts/apply_mapping.py mapping.json word.docx 输出.docx --excel 新数据.xlsx
  → 因为 mapping 用 source 指向 Excel，换数据自动出新值，零识别、零人工检查

模板被人微调了（改了文字、挪了表格、加了段落）：
  python3 scripts/apply_mapping.py mapping.json 微调后.docx --check --excel 数据.xlsx
  → --check 只检测不写，逐条报告哪几条「对不上了」
  → 你只针对报错的那几条，用对话告诉我怎么调（"P2 原文改成了（待定）"）
  → 我更新 mapping.json 里那几条，重新填充
```

这样兼顾两头：模板固定时**复用秒出**，模板微调时**只补差异、不从头审**，调整全程用对话完成。

填完**必做校验**（CLAUDE.md 第 2 节硬要求）：
- 残留检查：还有没有该填没填的空/占位文本
- 对账：派生值（合计/占比/同比）独立手算一遍，和输出逐项核对
- 把结果连同"未实测项"如实报告，再交付

## mapping.json 速记（详见 references/映射清单格式.md）

```json
[
  {"locate": {"type": "cell", "table": 0, "row": 1, "col": 1}, "source": {"sheet": "明细", "key": "货款"}, "format": "money", "note": "表0货款"},
  {"locate": {"type": "find", "old": "0.00", "para": 3}, "source": {"sheet": "基本信息", "key": "应付金额"}, "format": "money", "note": "P3 金额"},
  {"locate": {"type": "find", "old": "________"}, "value": "固定说明文字", "format": "text", "note": "极少变的常量用 value"}
]
```

**locate（往哪填）**：
- `cell`：表格坐标，最可靠。给 `old` 替换格内文本，不给则整格填空。
- `find`：正文查找替换；给 `para` 限定段落，不给则全文首个。
- `placeholder`：替换 `{{name}}`，兼容旧占位符模板。

**取值（填什么，二选一）**：
- `source`：从 Excel 现取，**推荐**——换数据不用改 mapping。`{"sheet":"基本信息","key":"客户名称"}`（第一列找 key 取第二列）或 `{"sheet":"明细","row":2,"col":3}`（坐标，1 起）。
- `value`：写死常量，适合极少变的固定文字。

**format**：`money`/`pct`/`int`/`text`/留空自动。

## 进阶：要算账的复杂报表

当 Word 里的数字是**算出来的**（合计、毛利率、同比、多表汇总），别让用户在 Excel 里先算好。读 `references/进阶范例-财务附注/update_word.py`——它把 11 张表的派生计算（货币资金合计、应收账款账龄、固定资产账面价值、毛利率）都在代码里算好。照它的结构，针对用户实际数据写一段映射生成逻辑，再走 `apply_mapping.py` 或 `fill_word.py` 填充。格式化函数 `fmt_money/fmt_pct/fmt_int` 在 `scripts/fill_word.py`，可直接复用。

## 可选：离线占位符模式（不经过 Claude）

如果要把工具发给同事在自己电脑上**双击运行**（不走对话），用占位符模式：模板里写 `{{占位符}}`，Excel 三列「占位符 | 值 | 格式」，双击 `一键更新-Windows.bat`（Mac 用 `.command`）。详见 `references/占位符语法与格式化.md`。底层是 `scripts/fill_word.py`。

## 环境依赖

```bash
pip install openpyxl python-docx     # Windows
pip3 install openpyxl python-docx    # Mac
```

## 已知限制（如实告知用户）

- **不自动刷新**：Excel 改完要主动跑一次，Word 不会自己变。
- **跨 run 的段内混合格式可能丢**：python-docx 把文本切成多个 run，要替换的文字若跨 run，会合并到首 run（脚本会报告哪几条发生了合并，请目检）。单 run 内的格式（如整个数字加粗）能完整保留。
- **重复值定位**：`find` 用全文首个匹配，原文若多处重复，加 `para`/`cell` 精确定位。

## 文件结构

```
excel-word-link/
├── SKILL.md                      本手册
├── scripts/
│   ├── inspect_files.py          ① 探查：dump Word 结构（带坐标）+ Excel
│   ├── apply_mapping.py          ⑤ 填充：按 mapping.json 精确替换 + 校验
│   └── fill_word.py              占位符模式引擎（离线双击 / 复用格式化函数）
├── references/
│   ├── 映射清单格式.md            mapping.json 字段详解
│   ├── 占位符语法与格式化.md       占位符 + 格式化速查
│   └── 进阶范例-财务附注/          要算账的复杂报表完整范例（11 表 + 派生计算）
├── assets/                       占位符模式示例备份
├── 数据.xlsx / 模板.docx          离线占位符模式开箱示例
└── 一键更新-Windows.bat / -Mac.command   离线双击入口
```
