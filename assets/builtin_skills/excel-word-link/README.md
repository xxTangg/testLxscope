# Excel ↔ Word 联动填充工具

把 Excel 里的数据填进 Word 文档，实现 Excel↔Word 联动。Excel 数据改了，重跑一次就出新 Word。

底层是脚本驱动（`python-docx` + `openpyxl`），**不是** Office 原生"粘贴链接"——好处是能**算账**（合计/占比/同比/会计括号负数）、能保留 Word 格式、跨 Mac/Windows。

> 这同时是一个 [Claude Code](https://claude.com/claude-code) Skill：把仓库交给 Claude，发一个 Word + 一个 Excel，它会自动识别对应关系、列草案给你审核、按确认后的清单填充并对账。详见 [SKILL.md](./SKILL.md)。

## 两种用法

### 1. 给 Claude 用（推荐，最灵活）
发一个 `.docx` + 一个 `.xlsx`，文档**不用预先改成模板**。Claude 走五步：

```
探查 → 自动识别「Word 哪里 ← Excel 哪个值」→ 列草案给你审 → 你对话调整 → 填充 + 对账校验
```

- 探查：`python3 scripts/inspect_files.py word.docx data.xlsx`
- 填充：`python3 scripts/apply_mapping.py mapping.json word.docx 输出.docx --excel data.xlsx`
- 模板被微调后检测差异：`... --check`

对应关系存成 `mapping.json`（用 `source` 指向 Excel 来源），**模板固定时换数据可复用、秒出**。

### 2. 离线占位符模式（发给同事双击用，不依赖 Claude）
在 Word 模板里写 `{{占位符}}`，Excel 三列「占位符 | 值 | 格式」，双击 `一键更新-Windows.bat`（Mac 用 `.command`）即可。

## 快速开始

```bash
pip install openpyxl python-docx        # Windows
pip3 install openpyxl python-docx       # Mac
```

仓库自带「付款通知书」开箱示例（`数据.xlsx` / `模板.docx`），双击双击器即可看到效果。

## 三种定位 + 格式化

`mapping.json` 每条指明「往哪填、填什么、怎么格式化」：

- **定位**：`cell` 表格坐标 / `find` 正文查找 / `placeholder` 占位符
- **取值**：`source` 从 Excel 现取（换数据不用改 mapping）/ `value` 写死常量
- **格式**：`money`（千分位+会计括号）/ `pct`（小数转%）/ `int` / `text`（编号电话防科学计数）/ 留空自动

## 进阶：要算账的复杂报表

合计、毛利率、同比、多表汇总这类**算出来的**值，`source` 取不了，走计算脚本。
`references/进阶范例-财务附注/` 是完整范例：11 张表的财务报表附注，自动算合计/账龄/账面价值/毛利率，342 个占位符一次填完（数据均为脱敏示例）。

## 文档

- [SKILL.md](./SKILL.md) — 给 Claude 的完整操作手册
- [需求文档.md](./需求文档.md) — 设计背景、方案演进、完整工作流（无损恢复上下文）
- [references/映射清单格式.md](./references/映射清单格式.md) — `mapping.json` 字段详解
- [references/占位符语法与格式化.md](./references/占位符语法与格式化.md) — 占位符 + 格式化速查

## 已知限制

- **不自动刷新**：Excel 改完要主动跑一次，Word 不会自己变。
- **跨 run 的段内混合格式可能丢**：替换的文字若被 Word 切成多个 run 会合并到首 run（脚本会报告，需目检）；单 run 内格式（如整段加粗）能保留。
- **派生值**（合计/同比）`source` 取不了，需先在 Excel 算好或走计算脚本。

## 文件结构

```
excel-word-link/
├── SKILL.md / 需求文档.md / README.md
├── scripts/
│   ├── inspect_files.py      探查：dump Word 结构（带坐标）+ Excel
│   ├── apply_mapping.py      填充：按 mapping.json 替换 + source 取值 + --check
│   └── fill_word.py          占位符引擎（离线双击 / 格式化函数）
├── references/               映射格式 / 占位符速查 / 财务进阶范例
├── assets/                   示例备份
├── 数据.xlsx / 模板.docx      离线开箱示例
└── 一键更新-Windows.bat / -Mac.command
```
