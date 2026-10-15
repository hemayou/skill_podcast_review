#!/usr/bin/env bash
# run_pipeline.sh — 一条龙: 抓取 → 转写 → 整合, 产出 文字稿.md(+音频/shownotes/字幕)。
# 三份 MD(精读/启示与行动/哲学沉淀)由 agent 按 SKILL.md 在此之后生成, 不在本脚本内。
#
# 用法:
#   run_pipeline.sh <小宇宙单集URL | 本地音频文件> [输出目录]
#
# 环境自适应:
#   - 引擎: Apple 芯片 Mac → mlx-whisper(large-v3-turbo); 其他 → faster-whisper(large-v3)
#   - 运行方式: 有 uv → 用临时环境(不污染全局, 推荐); 否则用系统 Python(必要时 pip 安装)
#   - 中文(PTK_LANGUAGE=zh, 默认)且存在 FunASR 环境 → funasr(先用 ffmpeg 转 16k 单声道 wav)
#   - 可用环境变量覆盖: PTK_ENGINE(funasr|mlx|faster|openai) PTK_MODEL=<模型名>
#     PTK_LANGUAGE=zh|en|... PTK_FUNASR_PY=<FunASR 的 python, 默认 ~/funasr/.venv/bin/python>
set -euo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUT="${1:?用法: run_pipeline.sh <URL|音频文件> [输出目录]}"
OUTARG="${2:-}"

# ---------- 1. 抓取 or 直接用本地音频 ----------
if [[ "$INPUT" =~ ^https?:// ]]; then
  echo "==> [1/3] 抓取音频与 shownotes"
  FETCH_JSON="$(python3 "$SCRIPTS/fetch_episode.py" "$INPUT" ${OUTARG:+"$OUTARG"})"
  read_json() { printf '%s' "$FETCH_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin).get('$1') or '')"; }
  OUTDIR="$(read_json outdir)"; AUDIO="$(read_json audio_path)"
  META="$OUTDIR/meta.json"; SHOWNOTES="$OUTDIR/shownotes.md"
else
  echo "==> [1/3] 使用本地音频: $INPUT"
  AUDIO="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"
  OUTDIR="${OUTARG:-$(dirname "$AUDIO")}"; mkdir -p "$OUTDIR"
  META=""; SHOWNOTES=""
fi
[ -n "${AUDIO:-}" ] && [ -f "$AUDIO" ] || { echo "未拿到音频文件, 终止。"; exit 1; }

# ---------- 2. 选引擎 + 转写 ----------
LANGUAGE="${PTK_LANGUAGE:-zh}"
FUNASR_PY="${PTK_FUNASR_PY:-$HOME/funasr/.venv/bin/python}"
OS="$(uname -s)"; ARCH="$(uname -m)"
if [ -z "${PTK_ENGINE:-}" ] && [[ "$LANGUAGE" == zh* ]] && [ -x "$FUNASR_PY" ] \
   && "$FUNASR_PY" -c "import funasr" 2>/dev/null; then
  ENGINE=funasr
elif [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
  ENGINE="${PTK_ENGINE:-mlx}"
else
  ENGINE="${PTK_ENGINE:-faster}"
fi
case "$ENGINE" in mlx) PKG="mlx-whisper";; openai) PKG="openai-whisper";; *) PKG="faster-whisper";; esac
MODEL_ARG=(); [ -n "${PTK_MODEL:-}" ] && MODEL_ARG=(--model "$PTK_MODEL")
META_ARG=(); [ -n "$META" ] && [ -f "$META" ] && META_ARG=(--meta "$META")

if [ "$ENGINE" = funasr ]; then
  [ -x "$FUNASR_PY" ] || { echo "选了 funasr 但找不到 $FUNASR_PY (见 references/transcription-engines.md)"; exit 2; }
  command -v ffmpeg >/dev/null 2>&1 || { echo "funasr 需要 ffmpeg 先转 wav: brew install ffmpeg"; exit 2; }
  WAV="$OUTDIR/audio.16k.wav"
  echo "==> [2/3] 转 16k 单声道 wav → $WAV"
  ffmpeg -nostdin -loglevel error -y -i "$AUDIO" -ar 16000 -ac 1 -c:a pcm_s16le "$WAV"
  echo "==> [2/3] 转写 (引擎=funasr, python=$FUNASR_PY)"
  "$FUNASR_PY" "$SCRIPTS/transcribe.py" "$WAV" --outdir "$OUTDIR" --engine funasr \
    --language "$LANGUAGE" ${MODEL_ARG[@]+"${MODEL_ARG[@]}"} ${META_ARG[@]+"${META_ARG[@]}"}
  rm -f "$WAV"
else
TR=("$SCRIPTS/transcribe.py" "$AUDIO" --outdir "$OUTDIR" --engine "$ENGINE" --language "$LANGUAGE" ${MODEL_ARG[@]+"${MODEL_ARG[@]}"} ${META_ARG[@]+"${META_ARG[@]}"})

echo "==> [2/3] 转写 (引擎=$ENGINE, 首次会下载模型, 请耐心)"
py_has() { python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$1') else 1)" 2>/dev/null; }
ENGINE_MOD=$([ "$ENGINE" = mlx ] && echo mlx_whisper || { [ "$ENGINE" = faster ] && echo faster_whisper || echo whisper; })

if py_has "$ENGINE_MOD"; then
  echo "    (检测到已安装 $ENGINE_MOD, 直接调用)"
  python3 "${TR[@]}"
elif command -v uv >/dev/null 2>&1; then
  echo "    (用 uv 临时环境运行, 不污染全局)"
  uv run --with "$PKG" python "${TR[@]}"
else
  echo "    (未装 $ENGINE_MOD 且无 uv; 尝试 pip 安装 $PKG)"
  python3 -m pip install --user "$PKG" 2>/dev/null || python3 -m pip install "$PKG" || {
    echo "自动安装失败。请手动安装(见 references/transcription-engines.md):"
    echo "  - 推荐先装 uv:  curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "  - 或:  python3 -m pip install $PKG"
    exit 2; }
  python3 "${TR[@]}"
fi
fi

# ---------- 3. 整合成文字稿 ----------
echo "==> [3/3] 整合 → 文字稿.md"
ASM=("$SCRIPTS/assemble_transcript.py" "$OUTDIR/audio.json" --out "$OUTDIR/文字稿.md")
[ -n "$SHOWNOTES" ] && [ -f "$SHOWNOTES" ] && ASM+=(--shownotes "$SHOWNOTES")
[ -n "$META" ] && [ -f "$META" ] && ASM+=(--meta "$META")
[ -f "$OUTDIR/fixes.json" ] && ASM+=(--fixes "$OUTDIR/fixes.json")
python3 "${ASM[@]}"

echo
echo "✅ 完成。产出在: $OUTDIR"
echo "   audio.* / shownotes.md / 文字稿.md"
echo "下一步(交给 agent, 见 SKILL.md): 语义校订 → 生成 精读 / 启示与行动 / 哲学沉淀 三份 MD。"
