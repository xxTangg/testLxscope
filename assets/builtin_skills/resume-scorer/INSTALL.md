# 安装说明

本 Skill 仅含 Markdown 与 prompt 文件，**无需安装 Python 或任何额外依赖**。将仓库 clone 到对应平台的 Skill 目录即可使用。

**Clone URL（固定）：**

```text
https://github.com/myrice12/resume-scorer-skill.git
```

---

## Claude Code

### 安装到当前项目

在 git 仓库根目录执行：

```bash
cd $(git rev-parse --show-toplevel)
mkdir -p .claude/skills
git clone https://github.com/myrice12/resume-scorer-skill.git .claude/skills/resume-scorer
```

### 安装到全局

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/myrice12/resume-scorer-skill.git ~/.claude/skills/resume-scorer
```

---

## Cursor

### 安装到当前项目

在 git 仓库根目录执行：

```bash
cd $(git rev-parse --show-toplevel)
mkdir -p .cursor/skills
git clone https://github.com/myrice12/resume-scorer-skill.git .cursor/skills/resume-scorer
```

### 安装到个人目录

```bash
mkdir -p ~/.cursor/skills
git clone https://github.com/myrice12/resume-scorer-skill.git ~/.cursor/skills/resume-scorer
```

---

## OpenClaw

```bash
mkdir -p ~/.openclaw/workspace/skills
git clone https://github.com/myrice12/resume-scorer-skill.git ~/.openclaw/workspace/skills/resume-scorer
```

---

## 触发方式

安装完成后，在对话中输入：

```text
/resume-scorer
```

或使用自然语言，例如：

- 「帮我给这份简历打分」
- 「把简历和 JD 对标一下」
- 「帮我筛这份简历」
- 「score this resume against the JD」

Skill 会自动识别输入类型（简历 / 项目 / JD / 对标分析），并按 [SKILL.md](./SKILL.md) 中的流程输出结构化评分与建议。
