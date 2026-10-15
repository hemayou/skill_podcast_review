---
name: podcast-to-knowledge
description: |
  Use this skill whenever the user has an existing podcast episode or an audio recording and wants it written up into a transcript and/or reusable notes. 把一期现成的播客 / 一段音频转写成文字稿，并整理成可长期复用的笔记。

  满足以下任意一条即触发：
  - 给出小宇宙单集链接（xiaoyuzhoufm.com）或本地音频文件（mp3/m4a/wav）——哪怕只丢来链接 / 音频、没说要做什么；
  - 想把它转成文字稿、听记，或整理成笔记；
  - 想要「精读」「启示与行动」「哲学沉淀（反思）」这三份 Markdown 中的任意一份或多份；
  - 想提炼能用的行动建议、结合自己当下的项目或处境从某期里找启发、把内容沉淀成自己的思考；
  - 想把常听的几档播客攒成可复用的知识库。

  不要用于：创作 / 策划自己的播客（写脚本、起标题、做封面图）、总结 B 站等视频、把钉钉会议录音整理成纪要、导出播客订阅列表。
---

# Podcast → Knowledge

把"听过"变成"可复用的 context"。一条流水线：**抓取 → 转写 → 校订 → 三份文档**。

设计原则：确定性的活（抓取/转写/整合）由 `scripts/` 里的脚本完成，任何 agent 直接跑即可；
判断性的活（语义校订、写三份文档）由你（agent）按本文件 + `references/doc-templates.md` 完成。
脚本只用系统工具（curl、Python 标准库）和本地 Whisper，**不绑定任何特定 agent 工具的专有命令**，
所以在 Claude Code / Codex / Kimi Code 等之间通用（安装方式见 `references/cross-agent-install.md`）。

`SKILL_DIR` 指本技能所在目录（本文件所在目录）。

---

## 阶段 0 · 认清输入

- **小宇宙单集链接**（形如 `https://www.xiaoyuzhoufm.com/episode/...`）→ 走完整流程。
- **本地音频文件**（mp3/m4a/wav…）→ 跳过抓取，直接转写+整合（无 shownotes 时不分章，属正常）。
- 其它播客平台链接：本技能的抓取脚本只懂小宇宙；其它平台请让用户提供音频文件，再走"本地音频"路径。

确认输出目录：默认在当前工作目录下新建一个**以单集标题命名的文件夹**，所有产物都放进去，保持整洁。

---

## 阶段 1 · 抓取与转写（跑脚本）

一条命令搞定抓取+转写+整合：

```bash
bash "$SKILL_DIR/scripts/run_pipeline.sh" "<小宇宙链接或音频文件>" ["输出目录"]
```

它会自动：判断输入类型 → 抓音频和 shownotes → 选转写引擎：**中文节目（默认 `PTK_LANGUAGE=zh`）且装了 FunASR
（`~/funasr/.venv`）时用 FunASR**（paraformer-zh + fsmn-vad + ct-punc，先用 ffmpeg 转 16k 单声道 wav，
错字明显少于 Whisper、自带标点和句级时间戳）；**英文节目请设 `PTK_LANGUAGE=en`**，走 Whisper（Apple 芯片 Mac 用
mlx-whisper 的 large-v3-turbo；其他系统用 faster-whisper）→ Whisper 路径 优先用 `uv` 临时环境运行（不污染全局），没有 uv 再退化到
系统 Python / pip → 整合出 `文字稿.md`。**首次运行会下载模型（约 1.5GB），耐心等。**

产出：`audio.*`（音频+srt/vtt/txt/json）、`shownotes.md`、`文字稿.md`。

> 若某一步在某个工具/环境里报错，可分步单独跑（见各脚本头部说明），或查 `references/transcription-engines.md`
> 的手动安装与排错（含已验证可用的 `uv run --with mlx-whisper …` 一行命令）。

英文节目示例：`PTK_LANGUAGE=en bash "$SKILL_DIR/scripts/run_pipeline.sh" "<音频>" "<输出目录>"`；
强制指定引擎：`PTK_ENGINE=funasr|mlx|faster|openai`。

Whisper 路径下脚本已用 shownotes 抽出的专名词表做 `initial-prompt` 从源头纠偏（FunASR 不支持该参数，英文人名常被拼错，如 Robert Hall→"robt haall"）——但**这不能完全消除同音/专名错**，
真正的校订在下一步。

---

## 阶段 2 · 语义校订（你来做，这步最容易被偷懒）

机器转写有两类必然的错，且**靠上下文就能判定**，所以必须由你这道"语义关"来兜：

1. **同音术语错**。最典型：「元认知 / 元数据 / 元技能」常被听成「原…」。
   判据：凡"**产生 X 的 X**""**关于 X 的 X**"这种自指定义，几乎一定是"**元（meta-）**"，不是"原"。
   （脚本已内置最安全的 `原认知→元认知`；其余交给你判断，别盲目全局替换——"原技能/原数据"在别的语境可能是对的。）
2. **专名错**：人名、播客名、英文产品/模型名（如 Claude Code、Codex、模型版本号）易被听岔。

**做法**：把 `文字稿.md` 与 `shownotes.md` 对照着扫一遍（shownotes 里的写法是权威，冲突时以它为准），
把确认要改的写成一个校订表，存到输出目录的 `fixes.json`：

```json
{ "错词": "正词", "良主": "良渚", "原数据": "元数据" }
```

然后重跑整合以可复现地套用（`run_pipeline.sh` 和 `assemble_transcript.py` 都会自动读取同目录的 `fixes.json`）：

```bash
python3 "$SKILL_DIR/scripts/assemble_transcript.py" "<输出目录>/audio.json" \
  --shownotes "<输出目录>/shownotes.md" --meta "<输出目录>/meta.json" \
  --fixes "<输出目录>/fixes.json" --out "<输出目录>/文字稿.md"
```

这样"语义判断 → 写表 → 机械套用"分工清楚：判断在你，套用可复现，不会手抖漏改。

---

## 阶段 3 · 生成三份 Markdown

完整的结构、口吻与范例在 **`references/doc-templates.md`**，先读它再动笔。三份的定位：

- **`01-精读.md`** — 客观深读：一句话概括 → 主讲/嘉宾的核心观点（结合 shownotes + 文字稿）→
  **你（agent）的真实感受**（容许保留意见，别一味叫好）→ 带时间轴的金句。
- **`02-启示与行动.md`** — 结合**当前使用者**的处境。**关键：先了解"现在用这个技能的人是谁"**——
  读其记忆/项目上下文，或直接问几句（近期在 agent 上做的课题、正在做的项目、长期惦记的事），
  **不要写死成任何特定人的背景**。再给出反身性的启示 + 可勾选的具体行动。
- **`03-哲学沉淀.md`** — 去技术、回到事物本身。第一人称、**草稿态**、留白与开放性，
  作者权归使用者：明确标"这是提议、非定论"，留"只有你能填"的空格与"尚未定论的张力"，
  并提醒 AI 是镜子而非立法者。详见模板里的"自主权与开放性"约定。

写作口吻：朴实、有判断，避免 AI 腔与学术地雷词（如"不是 X 而是 Y""三重结构性叠加"等）；
中文为主（除非使用者另有偏好）。

---

## 输出目录约定

```
<单集标题>/
├── audio.m4a / audio.srt / audio.vtt / audio.txt / audio.json
├── shownotes.md
├── meta.json
├── fixes.json            （阶段2 你写的校订表，可选）
├── 文字稿.md
├── 01-精读.md
├── 02-启示与行动.md
└── 03-哲学沉淀.md
```

给用户引用文件时用可点击的相对/绝对路径链接，方便他直接打开。
