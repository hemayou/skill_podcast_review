#!/usr/bin/env python3
"""
fetch_episode.py — 从小宇宙(xiaoyuzhou)单集链接抓取音频 + shownotes + 元数据。

用法:
    python3 fetch_episode.py <小宇宙单集URL> [输出目录]

产出(写入输出目录, 默认为当前目录下以单集标题命名的文件夹):
    audio.m4a       音频本体
    shownotes.md    节目简介 + 时间轴(从页面结构化数据提取)
    meta.json       标题/播客名/时长/音频直链/从shownotes提取的专名词表(供转写纠偏)

只用 Python 标准库, 不依赖 curl / 第三方包, 便于在不同机器/不同 agent 工具里直接跑。
"""
import sys, os, re, json, html, argparse, shutil, subprocess, ssl
import urllib.request, urllib.error

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")


INSECURE = False  # 仅当用户显式传 --insecure 时为 True


def _secure_context():
    """优先用 certifi 的根证书(修 macOS Python 常见的 cert 缺失), 否则用系统默认。"""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _urlopen(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        return urllib.request.urlopen(req, timeout=120, context=_secure_context())
    except urllib.error.URLError as e:
        is_cert = isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError) or \
                  "CERTIFICATE_VERIFY_FAILED" in str(e)
        if is_cert and INSECURE:
            print("[fetch] ⚠️ --insecure: 跳过证书校验(有 MITM 风险)重试", file=sys.stderr)
            return urllib.request.urlopen(req, timeout=120, context=ssl._create_unverified_context())
        if is_cert:
            raise SystemExit("[fetch] 证书校验失败。优先装 curl(系统证书最稳); 或 `pip install certifi`; "
                             "macOS 可跑 Python 的 Install Certificates.command。确知风险可加 --insecure。")
        raise


def http_get(url, binary=False):
    # 优先 curl(走系统证书, 跨平台最稳); 没有 curl 再用 urllib(带证书兜底)
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-fsSL", "-A", UA, url], capture_output=True)
        if r.returncode == 0:
            return r.stdout if binary else r.stdout.decode("utf-8", "replace")
        print(f"[fetch] curl 失败(code {r.returncode}), 改用 urllib", file=sys.stderr)
    with _urlopen(url) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def download_file(url, path):
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-fsSL", "-A", UA, url, "-o", path])
        if r.returncode == 0:
            return
        print(f"[fetch] curl 下载失败(code {r.returncode}), 改用 urllib", file=sys.stderr)
    with _urlopen(url) as r, open(path, "wb") as out:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def find_episode(o):
    """在 __NEXT_DATA__ 里递归找单集对象(含 title + shownotes)。"""
    if isinstance(o, dict):
        if o.get("type") == "EPISODE" or ("title" in o and "shownotes" in o):
            return o
        for v in o.values():
            r = find_episode(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_episode(v)
            if r:
                return r
    return None


def shownotes_to_md(raw):
    s = re.sub(r"<br\s*/?>", "\n", raw)
    s = re.sub(r"</p>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def extract_glossary(meta, shownotes_md):
    """从 shownotes 抽取可能的专名/英文术语, 供转写时做 initial-prompt 纠偏。
    思路: 时间轴里出现的关键词、英文 token、嘉宾/播客名 —— 这些最容易被同音听错。"""
    terms = set()
    for key in ("title",):
        if meta.get(key):
            terms.add(meta[key])
    if meta.get("podcast"):
        terms.add(meta["podcast"])
    # 英文/数字混合 token (产品名、模型名等)
    for m in re.findall(r"[A-Za-z][A-Za-z0-9\.\-+]{1,}", shownotes_md):
        if len(m) >= 2:
            terms.add(m)
    # 时间轴标题里的中文短语(去掉 mm:ss 前缀)
    for line in shownotes_md.splitlines():
        m = re.match(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s+(.+?)\s*[⭐️*]*$", line)
        if m:
            phrase = m.group(1).strip()
            # 只收短词组(更像专名), 长句对 ASR 纠偏价值低还占 initial-prompt 预算
            if 1 < len(phrase) <= 10:
                terms.add(phrase)
    # 清理
    out = [t.strip() for t in terms if t and len(t.strip()) > 1]
    return sorted(set(out))[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("outdir", nargs="?", default=None)
    ap.add_argument("--no-audio", action="store_true", help="只抓 shownotes/meta, 不下载音频")
    ap.add_argument("--insecure", action="store_true",
                    help="urllib 路径证书校验失败时跳过校验(有 MITM 风险, 仅在确知安全的网络下用)")
    args = ap.parse_args()
    global INSECURE
    INSECURE = args.insecure

    print(f"[fetch] 抓取页面: {args.url}", file=sys.stderr)
    htmltext = http_get(args.url)

    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', htmltext, re.S)
    ep = {}
    if m:
        try:
            ep = find_episode(json.loads(m.group(1))) or {}
        except json.JSONDecodeError:
            ep = {}

    # 标题/音频直链兜底: og: meta 标签
    def og(prop):
        mm = re.search(rf'<meta property="og:{prop}" content="([^"]*)"', htmltext)
        return mm.group(1) if mm else None

    title = ep.get("title") or og("title") or "episode"
    audio_url = None
    enc = ep.get("enclosure") or ep.get("media") or {}
    if isinstance(enc, dict):
        audio_url = enc.get("url")
    audio_url = audio_url or og("audio")
    if not audio_url:
        mm = re.search(r'https://[^"\s]+\.(?:m4a|mp3)[^"\s]*', htmltext)
        audio_url = mm.group(0) if mm else None

    meta = {
        "title": title,
        "podcast": (ep.get("podcast") or {}).get("title") if isinstance(ep.get("podcast"), dict) else None,
        "pubDate": ep.get("pubDate"),
        "duration_sec": ep.get("duration"),
        "audio_url": audio_url,
        "source_url": args.url,
    }
    shownotes_md = shownotes_to_md(ep.get("shownotes") or "")
    meta["glossary_terms"] = extract_glossary(meta, shownotes_md)

    # 输出目录: 默认用标题(去非法字符)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or "episode"
    outdir = args.outdir or safe
    os.makedirs(outdir, exist_ok=True)

    # shownotes.md
    sn_path = os.path.join(outdir, "shownotes.md")
    header = f"# {title}\n\n"
    if meta["podcast"]:
        header += f"> 播客：{meta['podcast']}"
    if meta["duration_sec"]:
        header += f"｜时长：约 {round(meta['duration_sec']/60)} 分钟"
    if meta["pubDate"]:
        header += f"｜发布：{meta['pubDate']}"
    header += f"\n> 链接：{args.url}\n\n---\n\n"
    with open(sn_path, "w", encoding="utf-8") as f:
        f.write(header + (shownotes_md or "（页面未提供文字版 shownotes）") + "\n")

    # meta.json
    with open(os.path.join(outdir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 下载音频
    audio_path = None
    if audio_url and not args.no_audio:
        ext = ".m4a" if ".m4a" in audio_url else (".mp3" if ".mp3" in audio_url else ".m4a")
        audio_path = os.path.join(outdir, "audio" + ext)
        print(f"[fetch] 下载音频 -> {audio_path}", file=sys.stderr)
        download_file(audio_url, audio_path)
        size = os.path.getsize(audio_path)
        print(f"[fetch] 音频 {size/1e6:.1f} MB", file=sys.stderr)

    # 把关键路径以 JSON 打到 stdout, 方便编排脚本/agent 解析
    result = {
        "outdir": os.path.abspath(outdir),
        "title": title,
        "audio_path": os.path.abspath(audio_path) if audio_path else None,
        "shownotes_path": os.path.abspath(sn_path),
        "meta_path": os.path.abspath(os.path.join(outdir, "meta.json")),
        "audio_url": audio_url,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as e:
        print(f"[fetch] 网络错误: {e}", file=sys.stderr)
        sys.exit(2)
