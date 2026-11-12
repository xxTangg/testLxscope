# 贡献指南

感谢你对 resume-scorer-skill 的关注。本仓库是纯 Markdown Skill，无 Python 运行时；贡献时请保持这一约束。

## 语言

- 文档、示例与 PR 说明默认使用**中文**。
- 专有名词、工具名、文件名可保留英文。

## 修改 prompts

- 评分维度名称须与 [`references/rubric.md`](references/rubric.md) 及现有 `prompts/scorer_*.md` 保持一致，勿自行增删或改名维度。
- 若需调整 rubric，请先改 `references/rubric.md`，再同步更新相关 prompts。

## 新增示例

- 新示例须明确标注为**示意**（虚构或脱敏数据，不代表真实个人或公司）。
- 示例输出结构须对齐 [`references/output-contract.md`](references/output-contract.md) 或当前 `SKILL.md` 中的输出结构约定。

## 提交 Pull Request 前自检

- [ ] 文档内链接可正常打开（相对路径正确、锚点有效）。
- [ ] 未编造事实、数据或引用不存在的文件。
- [ ] 未引入 Python 脚本、依赖或 CI 步骤（本 Skill 仅 Markdown / prompt）。
- [ ] prompts 维度名与 [`references/rubric.md`](references/rubric.md) 及现有 `prompts/scorer_*.md` 一致。
- [ ] 新示例已标注「示意」，且输出结构符合 [`references/output-contract.md`](references/output-contract.md) 或当前 `SKILL.md`。

## 提交流程

1. Fork 本仓库并在功能分支上修改。
2. 确保变更范围聚焦，避免无关文件。
3. 打开 PR，简要说明改动动机与影响范围。

如有疑问，可在 Issue 中讨论后再动手修改。
