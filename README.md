# kiosk-ai

A voice assistant that helps people use a kiosk. The user speaks (Korean), and the assistant
understands the request, operates the kiosk program on screen, and answers with speech.

The assistant is a **separate tool**. It never imports kiosk code. It only interacts with
what is on the screen, through the Windows UI Automation (accessibility) tree.

```
 mic ──► STT (faster-whisper) ──► LLM (Ollama, Qwen2.5) ──► screen actions (UI Automation)
                                        │
                                        └──► TTS (pyttsx3) ──► speaker
```

## Repository layout

| Path | What it is |
|---|---|
| `kiosk_app/` | Simple PySide6 test kiosk. Kept small, used only for testing. |
| `assistant/` | The AI tool: audio, STT, LLM, TTS, screen control, agent loop. |
| `configs/` | Model and runtime settings (YAML). Changing a model = PR to this folder. |
| `scripts/` | Setup and developer helper scripts. |
| `tests/` | Unit tests. |
| `docs/` | Architecture, setup guide, decision log. |
| `models/` | Local model downloads. **Git-ignored, never committed.** |

## Quick start

See [docs/setup.md](docs/setup.md) for the full guide.

```powershell
uv sync                                    # install Python deps (creates .venv)
ollama pull qwen2.5:7b-instruct-q4_K_M     # download the LLM
uv run python -m kiosk_app                 # run the test kiosk
uv run python -m assistant                 # run the assistant
```

## Docs

- [docs/decisions.md](docs/decisions.md): what we chose and why
- [docs/architecture.md](docs/architecture.md): how the pieces fit together
- [docs/setup.md](docs/setup.md): developer environment setup
- [CONTRIBUTING.md](CONTRIBUTING.md): branch and PR workflow
