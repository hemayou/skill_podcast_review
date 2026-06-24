#!/usr/bin/env python3
"""
transcribe.py — 用本地 Whisper 引擎把音频转成文字(json/srt/txt)。

本脚本只负责"在已经能 import 的引擎里择优并转写"。安装引擎的事交给
run_pipeline.sh(优先用 uv 临时环境, 不污染全局), 见 references/transcription-engines.md。

支持引擎(按 Mac/通用顺序自动探测):
    mlx        mlx-whisper      —— Apple 芯片最快, 中文质量好(默认 large-v3-turbo)
    faster     faster-whisper   —— 跨平台(CPU/GPU), 默认 large-v3
    openai     openai-whisper   —— 兜底, 默认 turbo

用法:
    python3 transcribe.py <音频路径> [--outdir DIR] [--meta meta.json]
                          [--engine auto|mlx|faster|openai] [--model NAME] [--language zh]

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


def pick_engine(prefer):
    if prefer and prefer != "auto":
        return prefer
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--meta", default=None)
    ap.add_argument("--engine", default="auto", choices=["auto", "mlx", "faster", "openai"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--language", default="zh")
    ap.add_argument("--initial-prompt", default=None)
    args = ap.parse_args()

    outdir = args.outdir or os.path.dirname(os.path.abspath(args.audio))
    os.makedirs(outdir, exist_ok=True)

    engine = pick_engine(args.engine)
    if not engine:
        print("[transcribe] 没找到任何可用的 Whisper 引擎(mlx_whisper/faster_whisper/whisper)。\n"
              "请先安装, 见 references/transcription-engines.md, 或用 run_pipeline.sh 自动处理。",
              file=sys.stderr)
        sys.exit(3)

    initial_prompt = args.initial_prompt or build_initial_prompt(args.meta)
    runner = {"mlx": run_mlx, "faster": run_faster, "openai": run_openai}[engine]
    language, segments, full_text = runner(args.audio, args.model, args.language, initial_prompt)

    base, n = write_outputs(outdir, language, segments, full_text)
    print(json.dumps({"engine": engine, "language": language, "segments": n,
                      "json": base + ".json", "srt": base + ".srt", "txt": base + ".txt"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
