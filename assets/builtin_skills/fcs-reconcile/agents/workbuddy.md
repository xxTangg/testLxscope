# WorkBuddy 平台专属配置

平台专属适配说明（安装 / 发现 / 调用 / 权限 / 网络限制），**不含对账业务逻辑**（NFR-08）。
支持级别：**格式兼容**（未逐项实测），验证项清单见
[docs/governance/agent-install.md](../../../docs/governance/agent-install.md) §4。

## 安装位置

| 范围 | 目标目录 |
|---|---|
| 用户级 | `~/.workbuddy/skills/fcs-reconcile/` |
| 项目级 | `<项目根>/.codebuddy/skills/fcs-reconcile/` |

⚠ **用户级与项目级目录名不对称**：项目级沿用底层 CodeBuddy 内核的 `.codebuddy/`，
不是 `.workbuddy/`。写错的表现是技能一个都不出现、且没有任何报错。

⚠ 复制的是 `fcs-reconcile` 这个目录本身，不要把整个 `skills/` 目录套进去——WorkBuddy 按
目录层级给技能命名，多套一层技能名会变成 `skills:fcs-reconcile`。

安装方式统一走提示词，见 [README「安装」](../../../README.md#安装)。装完须新开会话才加载，
可在「技能」面板核对是否装齐。

## 运行约定

- **入口**：`scripts/reconcile.py --config <config.yaml>`
- **解释器**：必须是装过 `requirements.txt`（`pandas` / `openpyxl` / `pyyaml`）的那一个。
- **网络**：运行期禁用（`guard.block_network()`）；仅安装期装依赖需要网络。
- **文件访问**：仅配置中指定的输入输出路径；源文件只读，运行前后 SHA-256 比对；
  输出路径覆盖输入时拒绝执行。
- **上交给模型的内容**：只有 `summary`；原始明细不越界，终端不打印交易明细。

## 运行前确认

先展示数据处理声明（读写文件数、原始数据是否进模型、网络状态、源文件是否修改、
输入完整性校验）并等待用户确认，确认前不落盘。声明格式见 `SKILL.md`「数据处理声明」。
