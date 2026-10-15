#!/usr/bin/env python3
"""
transcribe.py — 用本地 Whisper 引擎把音频转成文字(json/srt/txt)。

本脚本只负责"在已经能 import 的引擎里择优并转写"。安装引擎的事交给
run_pipeline.sh(优先用 uv 临时环境, 不污染全局), 见 references/transcription-engines.md。

支持引擎(按 Mac/通用顺序自动探测):
    mlx        mlx-whisper      —— Apple 芯片最快, 中文质量好(默认 large-v3-turbo)
    faster     faster-whisper   —— 跨平台(CPU/GPU), 默认 large-v3
    openai     openai-whisper   —— 兜底, 默认 turbo
    funasr     FunASR(阿里)     —— 中文首选: paraformer-zh + fsmn-vad + ct-punc,
                                   错字少; 无标点逐字结果 + 整段 ct-punc + 字符对齐回时间戳;
                                   需 16k 单声道 wav
                                   (run_pipeline.sh 会先转码, 并用 ~/funasr/.venv 跑)

auto 规则: --language 为 zh 且能 import funasr → funasr; 否则按 mlx/faster/openai 探测。

用法:
    python3 transcribe.py <音频路径> [--outdir DIR] [--meta meta.json]
                          [--engine auto|funasr|mlx|faster|openai] [--model NAME] [--language zh]

产出(写到 --outdir, 默认音频同目录):
    audio.json  {language, text, segments:[{id,start,end,text}]}
    audio.srt   带时间轴字幕
    audio.txt   纯文本(每段一行)
"""
import sys, os, re, json, argparse, importlib.util

BASE_GLOSSARY = [
    "元认知", "元数据", "元技能", "上下文", "大模型", "智能体", "提示词",
    "范畴论", "存在主义", "反身性", "Claude Code", "Codex", "Kimi Code",
    "soul.md", "memory.md", "token", "agent", "prompt", "context",
]


def has(mod):
    return importlib.util.find_spec(mod) is not None


def pick_engine(prefer, language=None):
    if prefer and prefer != "auto":
        return prefer
    if (language or "").lower().startswith("zh") and has("funasr"):
        return "funasr"
    is_mac_arm = sys.platform == "darwin" and os.uname().machine == "arm64"
    if is_mac_arm and has("mlx_whisper"):
        return "mlx"
    if has("faster_whisper"):
        return "faster"
    if has("whisper"):
        return "openai"
    if has("mlx_whisper"):
        return "mlx"
    return None


def build_initial_prompt(meta_path):
    terms = list(BASE_GLOSSARY)
    if meta_path and os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
            terms = list(meta.get("glossary_terms") or []) + terms
        except Exception:
            pass
    seen, out = set(), []
    for t in terms:
        t = (t or "").strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    prompt = "、".join(out)
    return prompt[:200]  # initial_prompt 过长会被截断, 控制在 ~200 字


def srt_time(sec):
    sec = max(0, float(sec)); h = int(sec // 3600); m = int((sec % 3600) // 60)
    s = int(sec % 60); ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_outputs(outdir, language, segments, full_text):
    base = os.path.join(outdir, "audio")
    norm = [{"id": i, "start": float(s["start"]), "end": float(s["end"]),
             "text": s["text"].strip()} for i, s in enumerate(segments)]
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump({"language": language, "text": full_text, "segments": norm},
                  f, ensure_ascii=False, indent=2)
    with open(base + ".srt", "w", encoding="utf-8") as f:
        for i, s in enumerate(norm, 1):
            f.write(f"{i}\n{srt_time(s['start'])} --> {srt_time(s['end'])}\n{s['text']}\n\n")
    with open(base + ".txt", "w", encoding="utf-8") as f:
        f.write("\n".join(s["text"] for s in norm) + "\n")
    return base, len(norm)


def run_mlx(audio, model, language, initial_prompt):
    import mlx_whisper
    model = model or "mlx-community/whisper-large-v3-turbo"
    print(f"[transcribe] 引擎=mlx-whisper 模型={model}", file=sys.stderr)
    r = mlx_whisper.transcribe(
        audio, path_or_hf_repo=model, language=language,
        initial_prompt=initial_prompt, verbose=False)
    return r.get("language", language), r["segments"], r.get("text", "")


def run_faster(audio, model, language, initial_prompt):
    from faster_whisper import WhisperModel
    model = model or "large-v3"
    print(f"[transcribe] 引擎=faster-whisper 模型={model}", file=sys.stderr)
    m = WhisperModel(model, device="auto", compute_type="auto")
    seg_iter, info = m.transcribe(audio, language=language,
                                  initial_prompt=initial_prompt)
    segs = [{"start": s.start, "end": s.end, "text": s.text} for s in seg_iter]
    text = "".join(s["text"] for s in segs)
    return getattr(info, "language", language), segs, text


def run_openai(audio, model, language, initial_prompt):
    import whisper
    model = model or "turbo"
    print(f"[transcribe] 引擎=openai-whisper 模型={model}", file=sys.stderr)
    m = whisper.load_model(model)
    r = m.transcribe(audio, language=language, initial_prompt=initial_prompt,
                     verbose=False)
    return r.get("language", language), r["segments"], r.get("text", "")


PUNC_MAP = {",": "，", ".": "。", "?": "？", "!": "！"}
END_PUNC = "。？！"


def _is_ascii_word(t):
    return bool(t) and t[0].isascii() and t[0].isalnum()


def align_punc(tokens, punc_text):
    """把整段标点结果按字符对齐回 ASR token, 返回每个 token 之后的标点(可为空)。"""
    after = [""] * len(tokens)
    i, n = 0, len(punc_text)
    for j, tok in enumerate(tokens):
        for ch in tok.casefold():
            while i < n and (punc_text[i].isspace() or punc_text[i] in "，。？！、,.?!"
                             ) and punc_text[i].casefold() != ch:
                i += 1
            if i < n and punc_text[i].casefold() == ch:
                i += 1
            # 对不上就跳过该字符, 不让误差向后漂移
        k = i
        while k < n and (punc_text[k].isspace() or punc_text[k] in "，。？！、,.?!"):
            if not punc_text[k].isspace():
                after[j] += punc_text[k]
            k += 1
        i = k
    return after


def build_sentences(tokens, stamps, after, maxlen=60):
    segs, buf, start = [], "", None
    def emit(end):
        nonlocal buf, start
        t = buf.strip()
        if t.strip("，。？！、 "):
            segs.append({"start": start / 1000.0, "end": end / 1000.0, "text": t})
        buf, start = "", None
    prev = None
    for tok, (st, en), pu in zip(tokens, stamps, after):
        if start is None:
            start = st
        if (prev is not None and buf and buf[-1] not in "，。？！、"
                and (_is_ascii_word(prev) or _is_ascii_word(tok))):
            buf += " "  # 英文词之间、中英交界处留空格
        buf += tok
        pu = "".join(PUNC_MAP.get(c, c) for c in pu)[:1]
        buf += pu
        prev = tok
        if pu and (pu in END_PUNC or (pu == "，" and len(buf) >= maxlen)):
            emit(en)
            prev = None
    if buf:
        emit(stamps[-1][1])
    # 修掉中英之间多余的空格紧挨标点
    for sg in segs:
        sg["text"] = re.sub(r" ([，。？！、])", r"\1", sg["text"])
    return segs


def run_funasr(audio, model, language, initial_prompt):
    """FunASR: 先出无标点逐字结果+时间戳, 再把整段文本一次性过 ct-punc, 最后按字符对齐回时间戳。

    不用 generate(punc_model=..., sentence_timestamp=True): funasr 1.4.x 内部把标点数组
    映射回 token 时, 遇到英文词(two/shall/AI/人名)会错位, 之后的标点整体前后漂移,
    出现"话，题""教，育"这类把词从中间断开的情况。
    """
    from funasr import AutoModel
    model = model or "paraformer-zh"
    punc_name = os.environ.get("PTK_FUNASR_PUNC", "ct-punc")
    print(f"[transcribe] 引擎=funasr 模型={model}+fsmn-vad, 标点={punc_name}(整段)", file=sys.stderr)
    asr = AutoModel(model=model, vad_model="fsmn-vad", disable_update=True)
    r = asr.generate(input=os.path.abspath(audio), batch_size_s=300)
    res = r[0] if r else {}
    tokens = (res.get("text") or "").split()
    stamps = res.get("timestamp") or []
    if not tokens:
        return language or "zh", [], ""
    punc = AutoModel(model=punc_name, disable_update=True)
    punc_text = punc.generate(input=" ".join(tokens))[0]["text"]
    if len(stamps) != len(tokens):  # 极少见: 没有逐字时间戳, 整段输出
        return language or "zh", [{"start": 0.0, "end": 0.0, "text": punc_text}], punc_text
    after = align_punc(tokens, punc_text)
    segs = build_sentences(tokens, stamps, after)
    return language or "zh", segs, "".join(s["text"] for s in segs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--meta", default=None)
    ap.add_argument("--engine", default="auto", choices=["auto", "funasr", "mlx", "faster", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--language", default="zh")
    ap.add_argument("--initial-prompt", default=None)
    args = ap.parse_args()

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.audio))
    os.makedirs(outdir, exist_ok=True)

    engine = pick_engine(args.engine, args.language)
    if not engine:
        print("[transcribe] 没找到任何可用的转写引擎(funasr/mlx_whisper/faster_whisper/whisper)。\n"
              "请先安装, 见 references/transcription-engines.md, 或用 run_pipeline.sh 自动处理。",
              file=sys.stderr)
        sys.exit(3)

    initial_prompt = args.initial_prompt or build_initial_prompt(args.meta)
    runner = {"funasr": run_funasr, "mlx": run_mlx, "faster": run_faster, "openai": run_openai}[engine]
    language, segments, full_text = runner(args.audio, args.model, args.language, initial_prompt)

    base, n = write_outputs(outdir, language, segments, full_text)
    print(json.dumps({"engine": engine, "language": language, "segments": n,
                      "json": base + ".json", "srt": base + ".srt", "txt": base + ".txt"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
