# Developer setup (Windows)

## 1. Install tools (once)

```powershell
winget install --id Git.Git
winget install --id astral-sh.uv
winget install --id Ollama.Ollama
winget install --id GitHub.cli        # optional, for PRs from the terminal
```

Restart the terminal afterwards so the new commands are on PATH.

## 2. Install the Korean voice for TTS (once)

Windows Settings → Time & language → Language & region → Add a language → **한국어**
→ make sure **Speech** (text-to-speech) is checked. This installs the "Microsoft Heami" voice used by `pyttsx3`.

## 3. Clone and install Python dependencies

```powershell
git clone https://github.com/jhj1012/kiosk-ai.git
cd kiosk-ai
uv sync                      # installs Python 3.12 if needed, creates .venv, installs deps
uv run pre-commit install    # auto-format and lint on every commit
```

## 4. Download models

Models are **never** committed to git. Model names are pinned in `configs/models.yaml`.

```powershell
ollama pull qwen2.5:7b-instruct-q4_K_M
```

The Whisper model downloads automatically into the Hugging Face cache the first time the assistant runs.

### Weaker machines

Create `configs/models.local.yaml` (git-ignored) to override settings for your PC only, e.g.:

```yaml
llm:
  model: qwen2.5:3b-instruct-q4_K_M
stt:
  model: small
  device: cpu
  compute_type: int8
```

### Using a teammate's GPU over the network

On the GPU machine, set the environment variable `OLLAMA_HOST=0.0.0.0` and restart Ollama.
On your machine, set `llm.host` in `models.local.yaml` to `http://<that-ip>:11434`.

## 5. Run

```powershell
uv run python -m kiosk_app
uv run python -m assistant
```
