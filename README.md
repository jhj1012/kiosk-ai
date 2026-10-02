# kiosk-ai

A voice assistant that helps people use a kiosk. The user speaks (Korean), and the assistant
understands the request, operates the kiosk program on screen, and answers with speech.

The assistant is a **separate tool**. It never imports kiosk code. It only interacts with
what is on the screen, through the Windows UI Automation (accessibility) tree. The AI runs in
the cloud through the **Gemini API**, so it works on ordinary PCs without a strong GPU.

```
 mic ──► STT (planned) ──► LLM (Gemini API) ──► screen actions (UI Automation)
                                  │
                                  ├──► TTS (pyttsx3, planned) ──► speaker
                                  └──► visual overlay (planned): avatar, subtitles,
                                       kiosk button images, blurred kiosk behind
```

## Roadmap

| # | Phase | Status |
|---|---|---|
| 1 | Test kiosk (`kiosk_app`) + UIA dump script | ✅ Done |
| 2 | Text-only agent: typed Korean in, kiosk operated via UIA, proactive questions | ✅ Done |
| 3 | Speech recognition (Gemini API audio input) + voice activity detection | ⏳ Next |
| 4 | TTS (pyttsx3, Korean voice) | Planned |
| 5 | Visual overlay: AI avatar, subtitles, cropped kiosk UI images, blurred kiosk background | Planned |

See [docs/architecture.md](docs/architecture.md#planned-visual-overlay) for the overlay design.

## Repository layout

| Path | What it is |
|---|---|
| `kiosk_app/` | Simple PySide6 test kiosk. Kept small, used only for testing. |
| `assistant/` | The AI tool: screen control, Gemini client, agent loop, user I/O; later audio, STT, TTS and the overlay UI. |
| `configs/` | Model and runtime settings (YAML). Changing the model = PR to this folder. |
| `scripts/` | Setup and developer helper scripts. |
| `tests/` | Unit tests. |
| `docs/` | Architecture, setup guide, decision log. |

## Quick start

See [docs/setup.md](docs/setup.md) for the full guide. You need a Gemini API key from
[Google AI Studio](https://aistudio.google.com/apikey).

```powershell
uv sync                                         # install Python deps (creates .venv)
Set-Content .env "GEMINI_API_KEY=your-key-here" # once; .env is git-ignored
uv run python -m kiosk_app                      # run the test kiosk
uv run python -m assistant                      # run the assistant (type Korean; --debug shows its steps)
```

### When the Gemini model is busy

Gemini models are shared, and at busy times Google answers slowly or refuses requests with
errors like `503 UNAVAILABLE ("This model is currently experiencing high demand")`,
`429 RESOURCE_EXHAUSTED` (your quota is used up) or `504 DEADLINE_EXCEEDED`. The free tier
allows only about 15 requests per minute per model, and one assistant turn can use several,
so talking quickly can hit it. The assistant retries automatically (for `429` it waits as long
as Google asks, up to a minute); if it still fails, it says
"죄송해요, 지금 잠시 문제가 생겼어요…" and you can simply say it again. If it keeps happening:

- wait a few minutes (demand spikes are usually short), or
- switch to another model in `configs/models.local.yaml`, e.g. `gemini-3.5-flash-lite` ↔
  `gemini-3.8-flash` (see [docs/setup.md](docs/setup.md#choosing-another-model)), or
- check your quota in [Google AI Studio](https://aistudio.google.com/) for `429` errors.

In our tests a step normally took 1–6 s, but some took ~50 s during busy periods.

## Running all day

Like a real kiosk, the assistant keeps running between customers, and each customer gets a
fresh conversation: nothing from the previous customer is remembered or sent to Gemini.

- If someone sounds like a new customer (e.g. "안녕하세요, 아이스티 하나 주세요" right after the
  last order was paid), the assistant asks "새로 주문하시는 손님이신가요?". On yes it presses
  "처음으로" and starts over with their request.
- As a fallback for quiet times: when the kiosk is back on its start screen and nobody has
  talked for 30 seconds (or nobody for 3 minutes, whatever the screen shows), the next message
  starts a new conversation. Start the assistant while the kiosk shows its start
screen; the times are `new_customer_after_s` / `abandoned_after_s` in `configs/settings.yaml`.

## Docs

- [docs/decisions.md](docs/decisions.md): what we chose and why
- [docs/architecture.md](docs/architecture.md): how the pieces fit together
- [docs/setup.md](docs/setup.md): developer environment setup
- [CONTRIBUTING.md](CONTRIBUTING.md): branch and PR workflow
