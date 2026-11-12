# fcs-reconcile 变更记录

记录本 Skill 的版本、规则版本、契约版本与回滚点（PRD §10.2）。

> 版本层级与 bump 时机见 [docs/governance/versioning.md](../../docs/governance/versioning.md)。
> 单 Skill 阶段 `skill_version` 与工具集版本对齐。

## [0.3.0] — 2026-08-11

**转 `Preview`，并补齐此前缺失的守卫。`scripts/` 的对账逻辑一行未改**——
`rule_version=1.0`、`contract_version=1.0` 均不变，相同输入 + 相同配置的对账结果与
0.2.x 完全一致（NFR-05）。

### 新增

- **`tests/golden/expected/` 逐单元格快照**：结果工作簿 7 张表 + 运行清单的完整期望值，
  由 `regen_snapshots.py` 生成（剔除 `run_id`、`run_at`、绝对路径等易变字段）。
  此前 golden 测试只断言 8 个 summary 计数与 2 个勾稽布尔值，**reporter 改错列序、改掉
  「判断依据」文案、少写一张表都不会红**——这是当时测试覆盖里最大的一处空洞。
  ⚠ `regen_snapshots.py` 只在 `rule_version` / `contract_version` 有意变更时执行；
  因回归失败而重生成快照 = 掩盖回归。
- **`requirements.txt` 带 `--hash=sha256:`**，支持 `pip install --require-hashes` 离线校验安装。
  注意 `numpy` 按 `python_full_version` 分叉，两个分支的哈希都在清单里。

### 变更

- **`status`：`Experimental` → `Preview`**。
- **`platforms.verified`：`[]` → `[claude-code, codex]`**，等级为「使用验证」。
  9 项验证项中 6 项由实际使用覆盖，权限确认 / 网络限制 / 错误处理 3 项未在宿主内确认，
  逐项状态见 [tests/cross_platform/records/](../../tests/cross_platform/records/)。
- **`tests.forward`：`pending` → `self-tested`**（不是 `passing`，见根 CHANGELOG 说明）。
- `skill_version` → `0.3.0`（`SKILL_META.yaml`、`scripts/version.py`、`SKILL.md` 同步）。

### 发布信息

- **规则/契约版本**：`rule_version=1.0`、`contract_version=1.0`，均未变。
- **测试状态**：unit / property / golden / security 通过（工具集合计 107 项）；
  `forward` 为 `self-tested`——开发者自测，非 PRD §10.1 定义的独立前向测试。
- **支持平台**：`claude-code`、`codex`（使用验证）；`workbuddy`（格式兼容）。
- **回滚版本**：`0.2.2`。回滚会把 `status`、`platforms.verified`、`tests.forward` 一并退回。

### 已知限制

结果工作簿有 2 处与[输出契约](../../docs/contracts/fcs-reconcile/output-contract.md)的
既有偏差未修（不是本版引入）：「隐私运行摘要」只复现 4 项而 PRD §5.3 要求 8 项；
「运行参数」表缺输入路径、字段映射、文件哈希。修复会改变工作簿内容并须 bump
`contract_version` 至 1.1，留待后续版本。其余限制见根 [CHANGELOG](../../CHANGELOG.md)。

## [0.2.2] — 2026-08-04

**只随工具集的许可证决策更新元数据，不动 `scripts/` 的任何对账逻辑。**
`rule_version=1.0`、`contract_version=1.0` 均不变（NFR-05）。

### 新增

- `LICENSE`：MIT License 副本。本目录是分发单元——用户把它复制到宿主的 skills 目录，
  根仓库的 LICENSE 不随之复制，而 MIT 要求所有副本都包含版权与许可声明。

### 变更

- `SKILL_META.yaml` 补 `license: MIT`；`skill_version` → `0.2.2`。
- `scripts/version.py`：`SKILL_VERSION` → `0.2.2`。

### 发布信息

- **规则/契约版本**：均未变。
- **测试状态**：unit / property / golden / security 通过（92 项）；`forward` 仍 `pending`。
- **回滚版本**：`0.2.1`。

## [0.2.1] — 2026-08-04

**本版只动测试与物料脚本的类型标注，不动 `scripts/` 的任何对账逻辑。**
`rule_version=1.0`、`contract_version=1.0` 均不变，相同输入 + 相同配置的对账结果与
0.2.0 / 0.1.0 完全一致（NFR-05）。

### 修复

- `tests/` 20 个文件补齐类型标注，mypy strict 下清零：`test_*` 函数补 `-> None`、
  fixture 参数标注 `tmp_path: Path` / `monkeypatch: pytest.MonkeyPatch`、辅助函数
  （`_r`、`row`、`statuses`、`_rows`、`_spec`、`_write`、`_make_config`、`_item`、
  `_fields`、`_match`、`_fail`）补齐完整签名。
- `tests/unit/test_summary.py`、`tests/golden/test_e2e_golden.py`：`s["counts"]["…"]`
  嵌套取值改用 `cast(dict[str, int], s["counts"])` 收窄——`build_summary` 的返回类型是
  `dict[str, object]`，与 `scripts/reconcile.py` 既有的 `cast` 惯例一致。
- `examples/gen_reconcile_demo.py`、`examples/gen_reconcile_result.py`：7 个样式辅助函数
  补 `Worksheet` / `Sequence[float]` 等标注；5 组循环变量改名以消除同名变量承载不同类型
  （`row` → `note_row` / `dq_row` / `audit_row` / `param_row`，`c` → `conf`）；
  中段 `from collections import defaultdict` 移回文件顶部。两个脚本已重新运行验证，
  产物工作表结构（3 张 / 7 张）与勾稽校验均通过。
- `scripts/version.py`：`SKILL_VERSION` → `0.2.1`。

### 发布信息

- **规则/契约版本**：`rule_version=1.0`、`contract_version=1.0`，均未变。
- **测试状态**：unit / property / golden / security 全部通过（92 项）；
  `forward`（独立前向测试）仍为 `pending`。
- **支持平台**：仍为「格式兼容」三家，`platforms.verified` 为空。
- **回滚版本**：`0.2.0`。

## [0.2.0] — 2026-08-04

**本版只动安装与元数据，不动对账行为。**`rule_version` 与 `contract_version` 均不变，
因此相同输入 + 相同配置的对账结果与 0.1.0 逐字节一致（NFR-05）。

### 新增

- `scripts/version.py`：本 Skill 运行期版本号的唯一事实源（`SKILL_VERSION`）。
- `agents/workbuddy.md`：WorkBuddy 平台专属配置骨架，与 `claude-code.md`、
  `openai.yaml` 形成三家对称。

### 变更

- `skill_version` 0.1.0 → **0.2.0**；`rule_version=1.0`、`contract_version=1.0` 不变；
  `status` 仍为 `Experimental`（发布状态与版本号无关）。
- `platforms.compatible` 填入 `claude-code, codex, workbuddy`（已提供安装提示词，
  路径见[多代理安装矩阵](../../docs/governance/agent-install.md)）；
  `platforms.verified` **仍为空**——FT-11 的 9 项验证项尚未执行。
- `agents/claude-code.md`、`agents/openai.yaml`：补齐安装位置、依赖与权限约定，
  不含任何对账业务逻辑（NFR-08）。

### 修复

- `scripts/reconcile.py` 不再硬编码 `skill_version="0.1.0"`，改从 `scripts/version.py` 取。
  原写法与 `SKILL_META.yaml` 各存一份，漏改一处会让运行清单（FT-08）里的版本号与实际
  发布版本不符，损害 NFR-04 可审计性。

### 版本与回滚

- `skill_version=0.2.0`，`rule_version=1.0`，`contract_version=1.0`，`status=Experimental`。
- **回滚版本**：`0.1.0`。规则与契约未变，回滚不影响既有运行清单与结果的可重复性。

## [0.1.0] — 2026-07-24

首个版本（工程完成于此日，当时未打 git tag，于 0.2.0 发布时追认）。

### 新增

- Skill 骨架：`SKILL.md`、`SKILL_META.yaml`、平铺 `scripts/` 模块、`references/`、`tests/`。
- 实现对账引擎（Task 0–14）：config / io_reader / normalizer / matcher（主键 + 复合键）/
  classifier / summary（勾稽）/ manifest / reporter（7 表）/ reconcile 编排 + CLI。
- `examples/`：对账演示数据与示例结果（12 行台账 vs 13 行银行流水，7 类典型差异）。
- 单元 / 属性 / 黄金 / 安全测试通过。

### 版本与回滚

- `skill_version=0.1.0`，`rule_version=1.0`，`contract_version=1.0`，`status=Experimental`。
- **回滚版本**：无（首个版本）。
