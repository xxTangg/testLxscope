# Claude Code 平台专属配置

平台专属适配说明（安装 / 发现 / 调用 / 权限 / 网络限制），**不含对账业务逻辑**（NFR-08）。
支持级别：**格式兼容**（未逐项实测），验证项清单见
[docs/governance/agent-install.md](../../../docs/governance/agent-install.md) §4。

## 安装位置

| 范围 | 目标目录 |
|---|---|
| 用户级 | `~/.claude/skills/fcs-reconcile/` |
| 项目级 | `<项目根>/.claude/skills/fcs-reconcile/` |

安装方式统一走提示词，见 [README「安装」](../../../README.md#安装)。装完须新开会话才加载。

## 运行约定

- **入口**：`scripts/reconcile.py --config <config.yaml>`
- **解释器**：必须是装过 `requirements.txt`（`pandas` / `openpyxl` / `pyyaml`）的那一个；
  与安装依赖时用的解释器不一致的表现是 `ModuleNotFoundError: pandas`。
- **网络**：运行期禁用——`guard.block_network()` 在管线第一步执行，外连抛
  `NetworkDisabledError`。仅安装期（装依赖）需要网络。
- **文件访问**：仅用户在配置里指定的输入与输出路径；源文件只读，运行前后 SHA-256 比对；
  输出路径覆盖输入时直接拒绝执行。
- **上交给模型的内容**：只有 `summary`（匹配率、各状态计数、勾稽结论）。
  原始明细、DataFrame、标准行不越界，终端也不打印交易明细。

## 运行前确认

Skill 须先展示数据处理声明（读写文件数、原始数据是否进模型、网络状态、源文件是否修改、
输入完整性校验）并等待用户确认，确认前不落盘。声明格式见 `SKILL.md`「数据处理声明」。
