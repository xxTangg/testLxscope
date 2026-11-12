# fcs-reconcile 输入契约

> 版本化的**权威**输入契约（骨架）。详尽逐字段 schema 属下游"详尽实现规格"。
> 上游：[技术设计 §3](../../design/fcs-reconcile-technical-design-v0.1.md)。

- `contract_version`: `1.0`

## 输入文件

- 两份 `.xlsx` 或 `.csv`：**左表**（业务台账/账）与**右表**（银行流水/对方系统）。
- 支持指定工作表、非首行表头、左右字段名不同。

## ReconcileConfig（骨架）

```yaml
left:  { file, sheet, header_row, fields: {no, amount, date, counterparty, direction} }
right: { file, sheet, header_row, fields: {no, amount, date, counterparty, direction} }
match:
  primary_key: "no"          # 主键（引擎按业务编号 no 分组匹配）
  composite_keys: []         # 可选复合键，如 ["amount","date","counterparty"]；
                             # 启用时必须包含 amount（否则拒绝加载，防金额不一致误判）
  amount_tolerance: "0.00"   # 金额容差（绝对值，Decimal 字符串；仅分级，不放宽自动确认）
  date_tolerance_days: 0     # 日期容差（天，仅用于复合键中的 date 近似）
  direction_rule: signed     # signed=按 direction 列归一为带符号金额；none=金额已带符号按原值用
  amount_scale: 2            # 金额量化小数位（四舍五入 HALF_UP）
output:
  path: <用户指定>           # 禁止覆盖任一输入文件（integrity 强校验）
rule_version: "1.0"
contract_version: "1.0"
```

## 校验（加载即校验，任一不满足则终止）

字段存在、类型可解析、`output.path` 不等于任一输入路径、`amount_tolerance` 为合法非负有限 Decimal；
`direction_rule` ∈ {signed, none}（signed 时左右表须配置 direction 字段）；
`composite_keys` 字段合法且必须包含 amount。任一不满足即抛 `ConfigError` 并终止。

> 注：字段映射键（如 `no`）即使不加引号也可用——加载器会还原 YAML 将裸 `no` 误解析的布尔值。
