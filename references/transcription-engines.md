# 转写引擎：选择、安装与排错

`run_pipeline.sh` 已自动处理引擎选择与运行，多数情况下你不用读本文件。遇到安装/转写报错，
或想手动控制时再看这里。

## 引擎对照

| 引擎 | 适用 | 默认模型 | 备注 |
|---|---|---|---|
| **mlx-whisper** | Apple 芯片 Mac（arm64） | `mlx-community/whisper-large-v3-turbo` | 跑 Metal，最快，中文质量好。**首选** |
| **faster-whisper** | Windows / Linux / Intel Mac（CPU 或 NVIDIA GPU） | `large-v3` | 跨平台稳；有 GPU 更快 |
| **openai-whisper** | 兜底，任意平台 | `turbo` | 纯 PyTorch，最通用但偏慢 |

模型大小 vs 速度/准确：`turbo` / `large-v3-turbo` 已接近 `large-v3` 的中文准确度但快很多，是默认。
要极致准确可用 `PTK_MODEL=large-v3`（更慢、更吃内存）；机器弱可用 `medium`（更快、略降准确）。

## 运行方式（`run_pipeline.sh` 的自动策略）

1. 若目标引擎已能 import → 直接用当前 Python。
2. 否则若有 **uv** → `uv run --with <pkg> python transcribe.py …`（临时环境，**不污染全局，推荐**）。
3. 否则尝试 `pip install --user <pkg>` / `pip install <pkg>`，失败则给出手动指引。

环境变量覆盖：`PTK_ENGINE=mlx|faster|openai`、`PTK_MODEL=<模型名>`。

## 手动安装（按需）

```bash
# 推荐先装 uv（之后所有引擎都能用临时环境跑，免污染）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 直接装某个引擎到当前环境
python3 -m pip install mlx-whisper        # Apple 芯片 Mac
python3 -m pip install faster-whisper     # 跨平台
python3 -m pip install -U openai-whisper  # 兜底（还需要 ffmpeg）
```

## 已验证可用的一行命令（Apple 芯片 Mac）

```bash
uv run --with mlx-whisper python "<SKILL_DIR>/scripts/transcribe.py" \
  "<音频>" --outdir "<输出目录>" --meta "<输出目录>/meta.json" --engine mlx
```

## 依赖

- **ffmpeg**：openai-whisper 需要；mlx/faster 一般自带解码。装法：macOS `brew install ffmpeg`、
  Debian/Ubuntu `apt install ffmpeg`、Windows `winget install ffmpeg`。
- **curl**：抓取脚本优先用它（系统证书最稳）。基本所有 macOS/Linux 自带。

## 排错

- **`CERTIFICATE_VERIFY_FAILED`（抓取阶段）**：装了 curl 就不会触发；纯 urllib 路径可
  `pip install certifi`，或 macOS 跑 Python 的 `Install Certificates.command`。确知网络安全可给
  `fetch_episode.py` 加 `--insecure`（有 MITM 风险，不建议常用）。
- **模型下载慢/卡**：首次会拉 ~1.5GB；没登录 HuggingFace 会限速但能下完。换网络或重试即可。
- **PEP 668 / externally-managed-environment（pip 报错）**：用 uv（推荐），或建虚拟环境
  `python3 -m venv .venv && . .venv/bin/activate && pip install <pkg>`。
- **中文里夹大量英文/专名错**：正常，靠阶段 2 的 `fixes.json` 校订；也可在 `transcribe.py`
  传更长的 `--initial-prompt` 术语表。
- **结尾/静音处“鬼打墙”重复**：`assemble_transcript.py` 已折叠连续重复片段；若仍有零星重复，
  在 `fixes.json` 处理或手动删。
