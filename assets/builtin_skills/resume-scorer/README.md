<div align="center">

# 📄 resume-scorer

### 结构化五维评分 Skill · 简历 / 项目经历 / JD 全覆盖

[![License: MIT](https://img.shields.io/badge/License-MIT-0d9488?style=for-the-badge&logo=open-source-initiative&logoColor=white)](./LICENSE)
[![Skill](https://img.shields.io/badge/Skill-resume--scorer-0d9488?style=for-the-badge&logo=anthropic&logoColor=white)](./SKILL.md)
[![Claude Code](https://img.shields.io/badge/Claude_Code-compatible-1f6feb?style=for-the-badge&logo=anthropic&logoColor=white)](./INSTALL.md)
[![Cursor](https://img.shields.io/badge/Cursor-compatible-6e56cf?style=for-the-badge&logoColor=white)](./INSTALL.md)
[![Version](https://img.shields.io/badge/version-1.1.0-f59e0b?style=for-the-badge&logo=git&logoColor=white)](./CHANGELOG.md)

<br/>

**对中文或英文简历、单段项目经历、岗位 JD 做结构化五维打分，附 JD 匹配分析与按优先级排序的改写建议。**

<br/>

[**功能概览**](#-功能概览) · [**快速开始**](#-快速开始) · [**评分维度**](#-评分维度) · [**输出契约**](#-输出契约) · [**示例**](#-示例) · [**质量边界**](#-质量边界) · [**贡献**](#-贡献)

<br/>

> 本 Skill 为纯 Markdown 实现，**无需安装任何运行时或 Python 依赖**。

</div>

---

## 📑 目录

- [功能概览](#-功能概览)
- [适用场景](#-适用场景)
- [快速开始](#-快速开始)
- [受众模式](#-受众模式)
- [评分维度](#-评分维度)
- [输入识别流程](#-输入识别流程)
- [输出契约](#-输出契约)
- [示例](#-示例)
- [项目结构](#-项目结构)
- [质量边界](#-质量边界)
- [版本与变更](#-版本与变更)
- [贡献](#-贡献)
- [致谢与参考](#-致谢与参考)
- [许可证](#-许可证)

---

## ✨ 功能概览

`resume-scorer` 是一个**纯 Markdown Skill**，不依赖任何 Python 包或外部服务。安装后，AI 助手会按固定流程识别输入类型、调用对应评分规则，并按统一输出契约返回结果。

| 能力 | 说明 |
| --- | --- |
| 🗂️ **五类输入** | 完整简历、单段项目经历、岗位 JD，以及「简历 + JD」「项目 + JD」对标分析 |
| 🎯 **五维打分** | 每类输入各有一套五维评分体系，统一 **0–100 分** 并附打分理由 |
| 🤝 **JD 匹配** | 提供目标 JD 时，额外输出 **岗位匹配度（fit score）**、已匹配与缺失关键词 |
| ✍️ **改写建议** | 3–5 条按优先级排序的修改建议；可按需生成优化后的 bullet 或段落 |
| 🌐 **中英双语** | 同一套规则覆盖中文与英文简历 / JD |
| 🧭 **双重视角** | 支持求职者（job_seeker）与招聘方（recruiter）两种受众模式 |
| 🛡️ **可追溯** | 所有结论必须能追溯到用户提供的原文，**绝不编造**事实或指标 |

## 👥 适用场景

### 求职者（默认模式）

- 评估完整简历或单段项目经历的完整度、影响力与针对性
- 将现有材料与目标 JD 对标，找出关键词缺口
- 获取可执行的改写建议，迭代投递材料

### 招聘方

- 快速初筛候选人简历，判断是否值得进入面试
- 评估岗位 JD 的清晰度、筛选效率与吸引力
- 以结构化维度辅助团队对齐筛选标准（**不构成**录用或拒信依据）

## 🚀 快速开始

### 1. 安装

按 [INSTALL.md](./INSTALL.md) 将本仓库 clone 到对应 Skill 目录，三平台一致：

| 平台 | 路径（项目级） | 路径（全局） |
| --- | --- | --- |
| **Claude Code** | `<repo>/.claude/skills/resume-scorer` | `~/.claude/skills/resume-scorer` |
| **Cursor** | `<repo>/.cursor/skills/resume-scorer` | `~/.cursor/skills/resume-scorer` |
| **OpenClaw** | — | `~/.openclaw/workspace/skills/resume-scorer` |

**项目级安装**（推荐，单项目可见）：

```bash
cd $(git rev-parse --show-toplevel)
mkdir -p .claude/skills   # 或 .cursor/skills
git clone https://github.com/myrice12/resume-scorer-skill.git .claude/skills/resume-scorer
```

**全局安装**（个人所有项目可用）：

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/myrice12/resume-scorer-skill.git ~/.claude/skills/resume-scorer
```

### 2. 触发

在对话中输入：

```text
/resume-scorer
```

或使用自然语言（任意一条）：

- 「帮我给这份简历打分」
- 「看看这段项目经历适不适合这个 JD」
- 「这个岗位 JD 写得怎么样」
- 「帮我把这份英文简历按目标岗位优化一下」
- 「score this resume against the JD」
- 「screen this candidate against the JD」

### 3. 提供输入

支持四种输入方式：

| 方式 | 用法 |
| --- | --- |
| **A. 指定文件** | 给出简历 / JD 文件路径，Skill 用 `Read` 读取 |
| **B. 粘贴文本** | 直接在对话中粘贴内容 |
| **C. 双输入对标** | 同时提供「简历 / 项目 + JD」，自动按对标分析处理 |
| **D. 关键词搜索** | 让 Skill 用 `Glob` 搜索本地 `**/*.md`、`**/*.txt`、`**/*.pdf` 中相关文件 |

读取后会回显确认：

```text
已读取内容：{文件名或内容来源}
检测到类型：{resume / project / jd / resume+jd / project+jd}
语言：{中文 / English / mixed}
下一步开始结构化评分。
```

## 🧭 受众模式

Skill 会根据用户意图自动选择受众模式（未指定时默认为 `job_seeker`）：

| 模式 | 触发示例 | 语气与侧重 |
| --- | --- | --- |
| `job_seeker`（默认） | 「帮我改改这段项目」 | **怎么改**——补量化、突出角色、对齐 JD 关键词 |
| `recruiter` | 「帮我筛这份简历」 | **筛什么 / 缺什么**——是否达标、关键缺口、是否值得面试 |

> ⚠️ 受众模式**仅影响**建议的侧重与语气；五维评分、0–100 刻度与证据抽取规则不变。

## 🎯 评分维度

三类输入各用五维评分，统一 0–100 刻度，分数段含义固定：

| 分数段 | 等级 | 含义 |
| --- | --- | --- |
| **80–100** | 🟢 强 | 该维度表现突出，可直接作为亮点或筛选依据 |
| **60–79** | 🟡 中 | 基本达标，仍有明显可改进空间 |
| **0–59** | 🔴 弱 | 存在结构性缺口或表达问题，需优先处理 |

> 完整定义见 [`references/rubric.md`](./references/rubric.md)；维度名修改须先改此文件再同步 prompts。

### 简历（resume）五维

| 维度 | 关注点 |
| --- | --- |
| **完整度** | 联系方式、个人摘要、工作/项目经历、技能栈、教育背景等关键模块是否齐全 |
| **影响力** | 是否使用动作词、是否有量化结果、是否能体现业务价值 |
| **清晰度** | 是否按时间顺序组织、bullet 精炼、一条一事 |
| **针对性** | 是否贴合目标岗位、关键词覆盖、最相关经历是否前置 |
| **可信度** | 时间信息、职责边界、工具/规模说明是否具体可信 |

### 项目经历（project）五维

| 维度 | 关注点 |
| --- | --- |
| **背景上下文** | 项目为什么存在、服务对象是谁、业务/技术目标是什么 |
| **个人主导度** | 是否区分团队行为与个人行为、是否体现角色边界 |
| **技术深度** | 技术方案、架构设计、约束条件、性能/稳定性/扩展性等工程问题 |
| **影响力** | 覆盖范围、上线范围、性能/效率数据，是否说明业务或团队变化 |
| **清晰度** | 是否遵循「背景 → 动作 → 结果」，是否好读 |

### 岗位 JD（jd）五维

| 维度 | 关注点 |
| --- | --- |
| **岗位清晰度** | 岗位名称、级别、团队/业务方向、角色定位 |
| **要求具体度** | 是否写明核心技能、经验范围、场景要求，是否避免空话 |
| **结构完整度** | 职责 / 任职要求 / 加分项 / 团队背景 / 补充信息分层 |
| **吸引力** | 是否说明业务价值、成长机会、薪资/福利/远程政策 |
| **筛选效率** | 是否区分 must-have / nice-to-have、是否减少冗余 |

## 🔄 输入识别流程

```
                    ┌───────────────────────┐
                    │  用户输入（文件 / 文本） │
                    └───────────┬───────────┘
                                │
                                ▼
                  ┌─────────────────────────┐
                  │  Step 1 读取并确认来源    │
                  └───────────┬─────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │  Step 2 prompts/classifier.md │
                │  判定：resume / project / jd  │
                │  判定：是否含目标 JD          │
                └───────────┬───────────────────┘
                            │
                ┌───────────┼───────────┬──────────────────┐
                ▼           ▼           ▼                  ▼
            resume        project        jd         resume+jd / project+jd
                │           │           │                  │
                ▼           ▼           ▼                  ▼
       scorer_resume   scorer_project  scorer_jd   主评分 + fit score
                │           │           │                  │
                └───────────┴───────────┴──────────────────┘
                                │
                                ▼
                ┌───────────────────────────────┐
                │   references/output-contract.md│
                │   按统一顺序输出总评/分项/建议 │
                └───────────┬───────────────────┘
                            │
                            ▼
                  ┌─────────────────────────┐
                  │  （可选）改写稿 / 导出文件 │
                  └─────────────────────────┘
```

完整流程定义见 [`SKILL.md`](./SKILL.md)；分类规则见 [`prompts/classifier.md`](./prompts/classifier.md)。

## 📋 输出契约

Skill 默认按 [`references/output-contract.md`](./references/output-contract.md) 输出：

```text
一句话总评

总分：X/100
岗位匹配度：Y/100（如果有 JD）

分项评分：
- 维度 A：X/100 — 简短理由
- 维度 B：Y/100 — 简短理由

主要优势：
- ...

主要问题：
- ...

优先修改建议：
1. ...
2. ...
3. ...
```

可选字段（按场景输出）：

| 字段 | 触发条件 |
| --- | --- |
| 匹配关键词 / 缺失关键词 | 输入含 JD 时 |
| 改写稿 | 用户要求改写时 |
| `{stem}.scored.md` | 用户要求保存评分结果时 |
| `{stem}.rewritten.md` | 用户要求保存改写稿时 |

改写或补全信息时，对原文未提供且不应编造的内容统一使用占位符：

```text
[待补充：具体说明缺什么]
```

> 示例：`[待补充：上线后的 QPS 或响应时间]`、`[待补充：团队规模与个人职责边界]`。

## 🧪 示例

三个完整示意示例存放于 `examples/`，输出结构对齐 [`references/output-contract.md`](./references/output-contract.md)：

| 示例 | 视角 | 展示内容 |
| --- | --- | --- |
| [`examples/lihua_before_after.md`](./examples/lihua_before_after.md) | 求职者 | 单段项目经历的评分 + 改写前后对比 + 占位符使用 |
| [`examples/resume_jd_fit.md`](./examples/resume_jd_fit.md) | 求职者 | 简历对标 JD，含 fit score、匹配/缺失关键词 |
| [`examples/recruiter_screen.md`](./examples/recruiter_screen.md) | 招聘方 | 候选人摘要筛选、缺口清单、是否值得推进面试 |

精简示意——项目经历评分：

```text
总评：这段项目经历有基础信息，但还不足以支撑高质量简历中的项目亮点。

总分：58/100

分项评分：
- 背景上下文：52/100
- 个人主导度：60/100
- 技术深度：55/100
- 影响力：48/100
- 清晰度：75/100

主要问题：
- 没说明平台解决的业务问题
- 没说明你本人负责了哪些关键模块

优先修改建议：
1. 补一句背景，说明这是为了解决什么审批流程问题
2. 明确你负责的是权限模型、表单迁移还是流程引擎
3. 加入量化结果：覆盖团队数、审批效率提升比例、人工处理时间减少情况
```

## 🗂️ 项目结构

```text
resume-scorer-skill/
├── SKILL.md                       # Skill 主入口与主流程
├── README.md                      # 本文件
├── INSTALL.md                     # Claude Code / Cursor / OpenClaw 安装
├── CHANGELOG.md                   # 版本变更记录（Keep a Changelog）
├── CONTRIBUTING.md                # 贡献指南与提交自检清单
├── LICENSE                        # MIT
├── .gitignore
├── prompts/
│   ├── classifier.md              # 输入类型识别与基础信号提取
│   ├── scorer_resume.md           # 简历五维评分规则
│   ├── scorer_project.md          # 项目经历五维评分规则
│   └── scorer_jd.md               # JD 五维评分规则
├── references/
│   ├── rubric.md                  # 五维定义与统一分数段（单一事实源）
│   ├── output-contract.md         # 默认输出结构与占位符约定
│   └── disclaimer.md              # 边界与免责声明
└── examples/
    ├── lihua_before_after.md      # 项目经历改写前后对比
    ├── resume_jd_fit.md           # 简历对标 JD
    └── recruiter_screen.md        # 招聘方快速筛选
```

## 🛡️ 质量边界

- ✅ 评分与建议须可追溯到用户提供的原文，**不编造**工作经历、项目成果或量化指标
- ✅ 各维度分数与 fit score 为结构化辅助意见，**不构成**录用、拒信或法律意义上的决策依据
- ✅ 简历与 JD 可能含敏感信息，分享示例前请脱敏；输出文件权限由用户自行负责
- ✅ 模型输出可能有偏差，关键决策请人工复核

完整说明见 [`references/disclaimer.md`](./references/disclaimer.md)。

## 🧾 版本与变更

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

完整历史见 [`CHANGELOG.md`](./CHANGELOG.md)。

## 🤝 贡献

欢迎提交 Issue 与 Pull Request。提交前请阅读 [`CONTRIBUTING.md`](./CONTRIBUTING.md)，要点：

- 文档默认中文；专有名词、工具名、文件名可保留英文
- 修改 prompts 时维度名须与 [`references/rubric.md`](./references/rubric.md) 保持一致
- 新示例须标注「示意」，且输出结构须对齐 [`references/output-contract.md`](./references/output-contract.md)
- 本仓库**不接受** Python 脚本、依赖或 CI 步骤

## 🙏 致谢与参考

- [Claude Code Skills](https://docs.claude.com/en/docs/claude-code/skills) — Skill 协议与目录约定
- [Cursor Skills](https://docs.cursor.com) — Cursor Agent Skill 集成
- [Keep a Changelog](https://keepachangelog.com/) — 变更日志规范
- [Semantic Versioning](https://semver.org/) — 语义化版本

## 📄 许可证

[MIT License](./LICENSE) © 2026 myrice12

---

<div align="center">

如果这个 Skill 对你找工作 / 招人有所帮助，欢迎点 ⭐ 支持。

<sub>纯 Markdown · 零运行时依赖 · 一行 clone 即可使用</sub>

</div>