---
name: fcs-reconcile
description: "用本地确定性程序核对银行流水与台账、应收回款、应付付款或两份业务明细，输出差异复核Excel。原始明细留在本地，仅汇总进入模型。用于对账和差异定位；不用于记账过账或税务结论。"
license: MIT
---

## 内网系统适配

本技能使用企业内网模型、用户上传材料与已授权的内部知识库。只读取当前任务资料，不调用公网服务、在线解析或动态安装依赖；缺少本地能力时明确指出缺项。

技能目录使用宿主提供的实际路径（下文以 `$DIR` 表示）；脚本和参考资料按该目录解析，执行脚本使用绝对路径。产物写入当前会话工作区的输出目录，使用绝对路径提供下载；不写入系统共享目录或其他账号的目录。默认用中文交付。

# fcs-reconcile（对账）

> 本 Skill 是工具集**安全、输出与质量标准的参考实现**。确定性对账引擎已实现（v0.3.0，发布状态 Preview）。

## 何时使用 / 不使用

- **应触发**：银行流水 vs 收付款台账对账；应收与回款核对；应付与付款核对；两个业务系统交易明细核对。
- **不应触发**：生成报表（→ 未来 `fcs-report`）、数据清洗（→ `fcs-clean`）、凭证过账、税务/会计政策结论、需联网登录外部系统的任务。

## 数据处理声明（运行前须向用户展示并确认）

```text
运行模式：本地隔离
将读取：N 个本地文件 ｜ 将写入：M 个结果文件
原始数据进入模型：否
网络访问：已禁用
源文件修改：否
终端输出交易明细：否
输入完整性：读取前后 SHA-256 校验
```

## 使用流程

1. 用户选择左表（业务台账）与右表（银行流水/对方系统）。
2. 运行前确认字段映射、匹配规则、容差、输出位置与隐私运行模式（见
   [docs/contracts/fcs-reconcile/input-contract.md](references/input-contract.md)）。
3. 本地程序执行对账（`scripts/reconcile.py`）。
4. **AI 只接收汇总结果**（匹配率、各状态计数、勾稽结论），原始明细留本地。
5. 生成结果工作簿与运行清单，用户复核并保存。

## 核心约束（不可退让）

- 只有**候选唯一且规则完全满足**时才自动确认（误判率 0，NFR-01）。
- 容差只用于**差异分级**，不放宽自动确认（技术设计 §5.3）。
- 金额一律 `Decimal`，不参与浮点运算。

## 关键规则与术语

- 匹配阶段与自动确认铁律：见 [references/matching-rules.md](references/matching-rules.md)。
- 中文财务术语与字段释义：见 [references/field-glossary.md](references/field-glossary.md)。

## 运行

```bash
python scripts/reconcile.py --config <config.yaml>
```

配置字段（字段映射、`match.primary_key` / `match.composite_keys` / `amount_tolerance` /
`date_tolerance_days` / `direction_rule`、`output.path`）见
[docs/contracts/fcs-reconcile/input-contract.md](references/input-contract.md)。
