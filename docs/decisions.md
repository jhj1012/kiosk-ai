# Decision log

| Area | Decision | Reason |
|---|---|---|
| Language | Python 3.12 | Team knows Python; AI ecosystem is Python-first. |
| Package manager | `uv` + `pyproject.toml` + `uv.lock` | Identical dependency versions for every teammate. |
| Kiosk UI | PySide6 (Qt) | Exposes a rich Windows UI Automation tree, so the assistant can read it. |
| How the AI sees the screen | Windows UI Automation tree via `pywinauto` (uia backend) | Text-based, fast, precise. Works with a text-only LLM. Vision models are a possible later fallback. |
| Architecture rule | `assistant` must never import `kiosk_app` | The assistant must work on any on-screen program, not just ours. Enforced by `import-linter`. |
| LLM | Gemini API (`google-genai`), default `gemini-3.5-flash-lite`, thinking level `low` | Our PCs cannot run a good local model: on the reference laptop (below) local Qwen2.5 7B/14B took 8–25 s per step and still made mistakes (skipped required questions, wrong quantities, pressed the wrong buttons). Gemini needs no GPU. In E2E tests `gemini-3.5-flash-lite` passed all six scenarios at 1–6 s per step (spikes up to ~50 s under Google's load); `gemini-3.8-flash` was overloaded at the time (~30 s for one word, 503 errors). Trade-off: needs internet and an API key, and the conversation and the kiosk screen text are sent to Google. |
| LLM output | Structured JSON output (JSON schema), not function calling | Measured with local models: tool calls ran away or came out malformed, while schema-constrained JSON always parses. The schema is rebuilt per screen, so the model can only name controls that exist. Kept for Gemini: it is model-independent. |
| Action targets | Control names, not numbers | The model copied element numbers from earlier answers and pressed the wrong control; names mean the same thing on every screen. |
| Safety | Payment and order-discarding buttons are blocked in code until the user says yes | Prompt rules alone were not enough: in tests the model pressed the home button (which empties the cart) to "go back". Patterns are per-kiosk settings. |
| Speech recognition | Planned: Gemini API (audio input) | No local Whisper: too slow on our PCs. To be confirmed in phase 3. |
| TTS | `pyttsx3` (Windows SAPI, Korean voice "Heami") | Built into Windows, instant, no AI model. Hidden behind an interface so it can be swapped later (e.g. Gemini TTS). |
| User language | Korean | |
| Secrets | API key in `GEMINI_API_KEY` (environment or git-ignored `.env`) | Never committed; each teammate uses their own key. |
| Repo | Private, `jhj1012/kiosk-ai` | |

## Reference hardware

Laptop with 32 GB RAM and an Intel Arc 140V integrated GPU (16 GB shared memory). This is why
the project moved from local models (Ollama, Qwen2.5) to the Gemini API: a 7B model ran at
~16 tokens/s and a 14B model needed 8–25 s for each agent step.
