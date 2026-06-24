# 跨 Agent 工具安装与使用

本技能是一个**自包含文件夹**：`SKILL.md`（指令）+ `scripts/`（确定性脚本）+ `references/`（细则）。
脚本只用 curl + Python 标准库 + 本地 Whisper，**不依赖任何特定工具的专有命令**，所以哪个 agent 都能用。

核心心法：**脚本到处能跑；让 agent“读 SKILL.md 并照做”即可。** 各工具差别只在于"怎么让 agent 自动发现这份技能"。

---

## 通用方法（任何 agent 工具都适用，最可靠）

1. 把整个 `podcast-to-knowledge/` 文件夹放到机器上任意位置。
2. 抓取+转写+整合（一行）：
   ```bash
   bash <技能目录>/scripts/run_pipeline.sh "<小宇宙链接或音频文件>"
   ```
3. 让你的 agent **读 `<技能目录>/SKILL.md` 和 `references/doc-templates.md`，然后按其阶段 2、3
   完成语义校订与三份 MD**。

只要这个 agent 能跑 shell、能读写文件，这套就成立——与它叫什么、是不是“支持 skills”无关。

---

## Claude Code

原生支持 skills。放到下面任一处，新开会话即自动发现，可 `/podcast-to-knowledge` 调用，
或在你给出小宇宙链接/说“把这期播客做成笔记”时自动触发：

- 个人级（跨所有项目）：`~/.claude/skills/podcast-to-knowledge/`  ← 本技能已装在这里
- 项目级（随仓库共享）：`<项目>/.claude/skills/podcast-to-knowledge/`

分享给同事：把文件夹拷给对方放进上述目录即可；或打包成 `.skill` 分发。

## Kimi Code

通常兼容 Claude Code 的技能布局。若它读取同样的 `~/.claude/skills/`（或其自有的 skills 目录），
把文件夹放进去即可；不确定就用上面的「通用方法」，效果一样。

## Codex（OpenAI）

若你的 Codex 版本支持 skills，按其文档把文件夹放进它的技能目录；并可在项目的 `AGENTS.md` 里加一句
指引（“处理播客/音频转知识时，读 `<路径>/SKILL.md` 并遵循它”）以提高触发率。
不确定其技能机制时，直接用「通用方法」：跑 `run_pipeline.sh` + 让它读 SKILL.md。

## OpenClaw 及其它/未知工具

不确定其是否有 skills 机制时，一律走「通用方法」：跑脚本 + 让 agent 读 `SKILL.md`。
这正是把确定性逻辑放进脚本、把指令放进 Markdown 的好处——不挑工具。

---

## 依赖检查清单（任何环境装好这些即可）

- `python3`（3.8+）
- `curl`（抓取用；macOS/Linux 一般自带）
- 本地 Whisper 引擎之一：mlx-whisper / faster-whisper / openai-whisper
  （`run_pipeline.sh` 会自动选并尝试安装；推荐先装 `uv` 让它用临时环境跑。详见
  `transcription-engines.md`）
- openai-whisper 还需 `ffmpeg`

不同操作系统（macOS / Windows / Linux）只是引擎和 ffmpeg 的装法不同，流程完全一致。
