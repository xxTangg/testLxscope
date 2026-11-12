---
name: internal-comms
description: "根据上传材料与内部知识库撰写工作周报、月度汇报、领导简报、内部通知、FAQ和项目进展，区分已完成、计划与问题。用于内部沟通和汇总汇报；无需连接外部办公平台。"
license: Complete terms in LICENSE.txt
---

## 内网系统适配

本技能使用企业内网模型、用户上传材料与已授权的内部知识库。只读取当前任务资料，不调用公网服务、在线解析或动态安装依赖；缺少本地能力时明确指出缺项。

技能目录使用宿主提供的实际路径（下文以 `$DIR` 表示）；脚本和参考资料按该目录解析，执行脚本使用绝对路径。产物写入当前会话工作区的输出目录，使用绝对路径提供下载；不写入系统共享目录或其他账号的目录。默认用中文交付。

## When to use this skill
To write internal communications, use this skill for:
- 3P updates (Progress, Plans, Problems)
- Company newsletters
- FAQ responses
- Status reports
- Leadership updates
- Project updates
- Incident reports

## How to use this skill

To write any internal communication:

1. **Identify the communication type** from the request
2. **Load the appropriate guideline file** from the `examples/` directory:
    - `examples/3p-updates.md` - For Progress/Plans/Problems team updates
    - `examples/company-newsletter.md` - For company-wide newsletters
    - `examples/faq-answers.md` - For answering frequently asked questions
    - `examples/general-comms.md` - For anything else that doesn't explicitly match one of the above
3. **Follow the specific instructions** in that file for formatting, tone, and content gathering

If the communication type doesn't match any existing guideline, ask for clarification or more context about the desired format.

## Keywords
3P updates, company newsletter, company comms, weekly update, faqs, common questions, updates, internal comms
