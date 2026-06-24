# podcast-to-knowledge

把播客（尤其[小宇宙](https://www.xiaoyuzhoufm.com)单集链接）或本地音频，变成**可长期复用的知识资产**。
一条流水线：**抓取 → 本地 Whisper 转写 → 结合 shownotes 校订专名 → 整合带时间轴文字稿 → 生成三份 Markdown**。

> 三份文档：**01 精读**（客观深读）· **02 启示与行动**（结合使用者处境的落地）· **03 哲学沉淀**
> （去技术、回到事物本身，第一人称草稿态，留白给本人，可并入 soul.md）。

## 安装

**方式一 · `.skill` 包**（最省事，适合微信 / 邮件分享）
拿到 `podcast-to-knowledge.skill` 后，在 Claude Code 里安装；或解压后把文件夹放进技能目录。

**方式二 · 从本仓库**
```bash
git clone https://github.com/hemayou/skill_podcast_review.git
# Claude Code：放进个人技能目录即可（新开会话自动发现）
mkdir -p ~/.claude/skills/podcast-to-knowledge
cp -r skill_podcast_review/* ~/.claude/skills/podcast-to-knowledge/
```
其它 agent 工具（Codex / Kimi Code 等）的装法见 [references/cross-agent-install.md](references/cross-agent-install.md)。
依赖与排错见 [references/transcription-engines.md](references/transcription-engines.md)。

## 这是什么

一个自包含的 [Agent Skill](https://docs.claude.com)：`SKILL.md` + `scripts/` + `references/`。
确定性的活（抓取/转写/整合）在脚本里，判断性的活（校订/写文档）由 agent 按 `SKILL.md` 完成。
不绑定任何工具的专有命令，**Claude Code / Codex / Kimi Code 等通用**。

## 快速开始

```bash
# 抓取 + 转写 + 整合（首次会下载 Whisper 模型 ~1.5GB）
bash scripts/run_pipeline.sh "https://www.xiaoyuzhoufm.com/episode/xxxxxxxx"

# 或处理本地音频
bash scripts/run_pipeline.sh "/path/to/audio.m4a"
```

跑完得到 `audio.*`、`shownotes.md`、`文字稿.md`。然后让你的 agent 读 `SKILL.md`，完成语义校订
（写 `fixes.json`）并生成三份 MD。

## 目录结构

```
podcast-to-knowledge/
├── SKILL.md                         主指令（流程 + 三份文档要求）
├── README.md
├── scripts/
│   ├── run_pipeline.sh              一条龙编排（环境自适应）
│   ├── fetch_episode.py             小宇宙链接 → 音频 + shownotes + meta（+专名词表）
│   ├── transcribe.py                本地 Whisper 转写（自动择引擎，initial-prompt 纠偏）
│   └── assemble_transcript.py       分章 + 去重 + 套校订表 → 文字稿.md
└── references/
    ├── doc-templates.md             三份文档的结构/口吻/范例 + 自主权约定
    ├── transcription-engines.md     引擎选择 / 安装 / 排错
    └── cross-agent-install.md       各 agent 工具的安装与使用
```

## 依赖

`python3` · `curl` · 本地 Whisper 引擎（mlx-whisper / faster-whisper / openai-whisper，脚本会自动选并尝试装；
推荐先装 `uv`）· openai-whisper 还需 `ffmpeg`。详见 `references/transcription-engines.md`。

## 设计取舍

- **脚本做确定性、agent 做判断**：可复现 + 保留人/AI 的判断力。
- **语义校订半自动**：agent 比对 shownotes 与上下文定错（如同音的「元/原」、英文专名），写进 `fixes.json`，
  脚本可复现套用——既自动又不乱改。
- **三份文档层层递进**，第三份刻意留白、尊重使用者对 soul.md 的自主权。
