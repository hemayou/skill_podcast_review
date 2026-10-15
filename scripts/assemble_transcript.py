#!/usr/bin/env python3
"""
assemble_transcript.py — 把转写 json + shownotes 整合成可读的「文字稿.md」。

只做"安全的机械活":
  - 用 shownotes 的时间轴自动分章
  - 折叠连续重复片段(消除片尾静音导致的"鬼打墙"幻听)
  - 按停顿间隔分段, 补轻标点
  - 套用一份校订表 fixes(内置极少数全局安全项 + 可选 --fixes 文件)

语义层的专名/同音字校订交给 agent(见 SKILL.md): agent 比对 shownotes 与上下文,
把该改的写进 fixes.json, 本脚本负责可复现地套用。这样既自动化又不乱改。

用法:
    python3 assemble_transcript.py <audio.json> --shownotes shownotes.md
            [--meta meta.json] [--fixes fixes.json] [--out 文字稿.md]
"""
import sys, os, re, json, argparse

# 全局安全校订: "元认知"是规范术语, "原认知"非标准词, 全局替换安全。
# 其余领域相关的同音字(如 原技能/原数据 在别的语境可能是对的)不内置, 交给 agent 经 --fixes 决定。
BUILTIN_FIXES = {"原认知": "元认知"}


def to_sec(ts):
    parts = [int(x) for x in ts.split(":")]
    if len(parts) == 3:
        return parts[0]*3600 + parts[1]*60 + parts[2]
    return parts[0]*60 + parts[1]


def parse_chapters(shownotes_md):
    """兼容两种时间轴写法:
       纯文本行  "00:12 标题"
       表格行    "| 00:12 | 标题 |"
    """
    chs = []
    for line in shownotes_md.splitlines():
        m = re.match(r"^\s*\|?\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*[|\s]\s*(.+?)\s*$", line)
        if m:
            title = m.group(2).strip().strip("|").strip()
            title = re.sub(r"\s*[⭐️*]+\s*$", "", title).strip()
            if title:
                chs.append((to_sec(m.group(1)), title))
    chs.sort(key=lambda x: x[0])
    if chs and chs[0][0] > 0:
        chs.insert(0, (0, "开场"))
    return chs


def mmss(sec):
    sec = int(sec); h = sec//3600; m = (sec % 3600)//60; s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def chapter_index(start, chapters):
    idx = 0
    for i, (cst, _) in enumerate(chapters):
        if start >= cst:
            idx = i
    return idx


def apply_fixes(text, fixes):
    for a, b in fixes.items():
        text = text.replace(a, b)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("audio_json")
    ap.add_argument("--shownotes", default=None)
    ap.add_argument("--meta", default=None)
    ap.add_argument("--fixes", default=None, help="JSON: {错词:正词}")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pause", type=float, default=1.3, help="分段的停顿阈值(秒)")
    ap.add_argument("--maxlen", type=int, default=110, help="单段最大字数")
    args = ap.parse_args()

    data = json.load(open(args.audio_json, encoding="utf-8"))
    segs = data.get("segments", [])

    fixes = dict(BUILTIN_FIXES)
    if args.fixes and os.path.exists(args.fixes):
        fixes.update(json.load(open(args.fixes, encoding="utf-8")))

    shownotes_md = ""
    if args.shownotes and os.path.exists(args.shownotes):
        shownotes_md = open(args.shownotes, encoding="utf-8").read()
    chapters = parse_chapters(shownotes_md)

    meta = {}
    if args.meta and os.path.exists(args.meta):
        meta = json.load(open(args.meta, encoding="utf-8"))

    # 清洗 + 折叠连续重复
    rows, prev = [], None
    for sg in segs:
        t = apply_fixes(sg["text"].strip(), fixes).strip(" ，。、,.")
        if not t or t == prev:
            continue
        prev = t
        ci = chapter_index(sg["start"], chapters) if chapters else 0
        rows.append((sg["start"], sg["end"], t, ci))

    # 组装 markdown
    out = []
    title = meta.get("title", "播客文字稿")
    out.append(f"# 文字稿 ·《{title}》\n")
    line = "> "
    if meta.get("podcast"):
        line += f"播客「{meta['podcast']}」"
    if meta.get("duration_sec"):
        line += f"｜约 {round(meta['duration_sec']/60)} 分钟"
    if meta.get("source_url"):
        line += f"｜{meta['source_url']}"
    out.append(line if line.strip() != ">" else "")
    out.append("> 由本地语音识别(FunASR/Whisper)自动转写并按时间轴整合, 已折叠重复、补轻标点、套用校订表。"
               "机器转写难免同音/专名误差, 引用前请对照音频。\n")

    cur = -1
    buf, buf_end = [], None

    def flush():
        nonlocal buf, buf_end
        if buf:
            out.append("，".join(buf) + "。")
            out.append("")
        buf, buf_end = [], None

    for st, en, t, ci in rows:
        if chapters and ci != cur:
            flush()
            cur = ci
            cst, ctitle = chapters[ci]
            out.append(f"## [{mmss(cst)}] {ctitle}\n")
        if buf and (buf_end is not None and st - buf_end > args.pause
                    or len("，".join(buf)) > args.maxlen):
            flush()
        buf.append(t); buf_end = en
    flush()

    outpath = args.out or os.path.join(os.path.dirname(os.path.abspath(args.audio_json)), "文字稿.md")
    with open(outpath, "w", encoding="utf-8") as f:
        f.write("\n".join(out).rstrip() + "\n")

    print(json.dumps({"out": os.path.abspath(outpath), "segments_kept": len(rows),
                      "chapters": len(chapters), "fixes_applied": len(fixes)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
