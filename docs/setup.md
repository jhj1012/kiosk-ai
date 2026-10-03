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
screen (no screenshots), and in voice mode the recording of each utterance. The free tier also
has a **daily** limit per model (500 requests in our tests); voice mode uses a second model for
speech recognition, so it has its own limits.

### Choosing another model

The model is set in `configs/models.yaml` (default `gemini-3.5-flash-lite`). To try another
one on your PC only, create `configs/models.local.yaml` (git-ignored):

```yaml
llm:
  model: gemini-3.8-flash        # stronger, but slower
  thinking_level: medium         # minimal | low | medium | high
```

`uv run python -m assistant --model <name>` also works for a single run.

## 5. Run

Start the kiosk first, then the assistant in a second terminal, on the same virtual desktop:

```powershell
uv run python -m kiosk_app
uv run python -m assistant            # type Korean at the "나>" prompt
uv run python -m assistant --debug    # also print each screen, model answer and action
uv run python -m assistant --voice    # speak instead of typing (see 6.)
```

Every session writes a log to `logs/`. Typed commands: `/reset` starts a new conversation,
`/quit` exits. In voice mode, Ctrl+C exits.

## 6. Microphone (voice mode)

1. **Allow microphone access**: Windows Settings → Privacy & security → Microphone → turn on
   **Microphone access** and **Let desktop apps access your microphone**. If this is off, the
   microphone delivers only silence and the assistant says so ("마이크 소리가 전혀 들어오지 않아요").
2. Check the microphone and speech recognition:

   ```powershell
   uv run python scripts/mic_check.py --list       # input devices; * = Windows default
   uv run python scripts/mic_check.py --levels 10  # live levels; "|" marks the speech threshold
   uv run python scripts/mic_check.py              # say something: prints the text and latency
   ```

3. To use another device or tune the voice detection on your PC only, create
   `configs/settings.local.yaml` (git-ignored):

   ```yaml
   audio:
     device: USB          # index or part of the name from --list
     min_threshold: 200   # quieter microphone: lower; noisy room: raise
     silence_end_ms: 1000 # people who pause while speaking
   ```

Run `uv run python -m assistant --voice`. After "(말씀하시면 듣고 있어요)", just speak; the
assistant detects the start and end of speech by itself, shows what it understood as
`나(음성)> ...` and answers. Stay quiet for the first second (it measures the background
noise). Developer options:

- `--push-to-talk`: press Enter before each utterance (useful in a noisy room).
- `--save-audio`: save each utterance to `recordings/` (git-ignored; never commit recordings).
- `--debug`: also shows ignored sounds ("말소리가 아니에요").

The speech recognition model is `stt.model` in `configs/models.yaml` (change it per PC in
`configs/models.local.yaml`). Keep it different from the agent's `llm.model`, so each has its
own rate limits.
