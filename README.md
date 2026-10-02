# kiosk-ai

A voice assistant that helps people use a kiosk. The user speaks (Korean), and the assistant
understands the request, operates the kiosk program on screen, and answers with speech.

The assistant is a **separate tool**. It never imports kiosk code. It only interacts with
what is on the screen, through the Windows UI Automation (accessibility) tree.

```
 mic ──► STT (faster-whisper) ──► LLM (Ollama, Qwen2.5) ──► screen actions (UI Automation)
                                        │
                                        ├──► TTS (pyttsx3) ──► speaker
                                        └──► visual overlay (planned): avatar, subtitles,
                                             kiosk button images, blurred kiosk behind
```

## Roadmap

| # | Phase | Status |
|---|---|---|
| 1 | Test kiosk (`kiosk_app`) + UIA dump script | ✅ Done |
| 2 | Text-only agent: typed Korean in, kiosk operated via UIA, proactive questions | ✅ Done |
| 3 | Speech recognition (faster-whisper) + voice activity detection | ⏳ Next |
| 4 | TTS (pyttsx3, Korean voice) | Planned |
| 5 | Visual overlay: AI avatar, subtitles, cropped kiosk UI images, blurred kiosk background | Planned |

See [docs/architecture.md](docs/architecture.md#planned-visual-overlay) for the overlay design.

## Repository layout

| Path | What it is |
|---|---|
| `kiosk_app/` | Simple PySide6 test kiosk. Kept small, used only for testing. |
| `assistant/` | The AI tool: audio, STT, LLM, TTS, screen control, agent loop, (planned) overlay UI. |
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
uv run python -m assistant                 # run the assistant (type Korean; --debug shows its steps)
```

## Docs

- [docs/decisions.md](docs/decisions.md): what we chose and why
- [docs/architecture.md](docs/architecture.md): how the pieces fit together
- [docs/setup.md](docs/setup.md): developer environment setup
- [CONTRIBUTING.md](CONTRIBUTING.md): branch and PR workflow
