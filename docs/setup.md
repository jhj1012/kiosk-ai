# Developer setup (Windows)

## 1. Install tools (once)

```powershell
winget install --id Git.Git
winget install --id astral-sh.uv
winget install --id GitHub.cli        # optional, for PRs from the terminal
```

Restart the terminal afterwards so the new commands are on PATH.

## 2. Install the Korean voice for TTS (once)

Windows Settings → Time & language → Language & region → Add a language → **한국어**
→ make sure **Speech** (text-to-speech) is checked. This installs the "Microsoft Heami" voice
used by `pyttsx3` (planned TTS phase).

## 3. Clone and install Python dependencies

```powershell
git clone https://github.com/jhj1012/kiosk-ai.git
cd kiosk-ai
uv sync                      # installs Python 3.12 if needed, creates .venv, installs deps
uv run pre-commit install    # auto-format and lint on every commit
```

## 4. Gemini API key

The assistant's AI runs in the cloud through the Gemini API; nothing is downloaded.

1. Create a key in [Google AI Studio](https://aistudio.google.com/apikey) (Get API key).
2. Put it in a file named `.env` in the repository root (git-ignored, never commit it):

   ```powershell
   Set-Content .env "GEMINI_API_KEY=your-key-here"
   ```

   Setting `GEMINI_API_KEY` as an environment variable works too; it wins over `.env`.

Each teammate uses their own key. Check the free-tier limits and pricing of the model you use
in AI Studio. What the assistant sends to Google: the conversation and the text of the kiosk
screen (no screenshots, no audio yet).

### Choosing another model

The model is set in `configs/models.yaml` (default `gemini-3.8-flash`). To try another one on
your PC only, create `configs/models.local.yaml` (git-ignored):

```yaml
llm:
  model: gemini-3.5-flash-lite   # faster and cheaper
  thinking_level: minimal        # minimal | low | medium | high
```

`uv run python -m assistant --model <name>` also works for a single run.

## 5. Run

Start the kiosk first, then the assistant in a second terminal, on the same virtual desktop:

```powershell
uv run python -m kiosk_app
uv run python -m assistant            # type Korean at the "나>" prompt
uv run python -m assistant --debug    # also print each screen, model answer and action
```

Every session writes a log to `logs/`. Commands: `/reset` starts a new conversation,
`/quit` exits.
