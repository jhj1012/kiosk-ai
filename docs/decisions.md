# Decision log

| Area | Decision | Reason |
|---|---|---|
| Language | Python 3.12 | Team knows Python; AI ecosystem is Python-first. 3.12 (not 3.13+) for best wheel availability of ML packages. |
| Package manager | `uv` + `pyproject.toml` + `uv.lock` | Identical dependency versions for every teammate. |
| Kiosk UI | PySide6 (Qt) | Exposes a rich Windows UI Automation tree, so the assistant can read it. |
| How the AI sees the screen | Windows UI Automation tree via `pywinauto` (uia backend) | Text-based, fast, precise. Works with a text-only LLM. Vision models are a possible later fallback. |
| Architecture rule | `assistant` must never import `kiosk_app` | The assistant must work on any on-screen program, not just ours. Enforced by `import-linter`. |
| LLM runtime | Ollama | Easy model management; each dev runs `ollama pull`. |
| LLM model | `qwen2.5:7b-instruct-q4_K_M` (default) | 4-bit quantized, ~4.7 GB VRAM, supports tool calling. `14b` variant is an option to evaluate for better Korean. |
| LLM output | Ollama structured outputs (JSON schema), not native tool calls | Measured on 9 steps from the real kiosk screens: qwen2.5 tool calls once generated 10k tokens without stopping and leaked malformed `<tool_call>` text; schema-constrained JSON always parses, and the schema is rebuilt per screen so the model can only name controls that exist. `act` vs `reply` is an `anyOf`, so each step either acts or ends the turn with one message. |
| Action targets | Control names, not numbers | The model copied element numbers from earlier answers and pressed the wrong control; names mean the same thing on every screen. |
| Safety | Payment and order-discarding buttons are blocked in code until the user says yes | Prompt rules alone were not enough: in tests the model pressed the home button (which empties the cart) to "go back". Patterns are per-kiosk settings. |
| Text-agent model | `qwen2.5:14b-instruct-q4_K_M` recommended (via `models.local.yaml`); shared default not changed yet | E2E on the test kiosk: 7B did not ask required options, invented quantities and repeated itself (2/9 in the step test). 14B completes the scenarios with occasional mistakes, see the PR. Changing the shared default is a team decision (more VRAM, slower). |
| Speech recognition | `faster-whisper` (`large-v3-turbo`, `int8_float16`) | Whisper models, faster and lighter. Quantized int8. Built-in Silero VAD. |
| TTS | `pyttsx3` (Windows SAPI, Korean voice "Heami") | Zero setup, offline. Hidden behind an interface so it can be swapped later (e.g. MeloTTS). |
| User language | Korean | |
| Model sharing | Models never committed. Names pinned in `configs/models.yaml`; each dev downloads locally. | Git is not for multi-GB binaries. |
| Repo | Private, `jhj1012/kiosk-ai` | |

## Reference hardware

Laptop with 32 GB RAM and an Intel Arc 140V iGPU (16 GB shared memory, Ollama via Vulkan).
Measured: qwen2.5 7B ~16 tokens/s, one agent step 3–6 s (7B) or 8–25 s (14B).
Estimated GPU memory use:

| Component | VRAM |
|---|---|
| Qwen2.5 7B Q4_K_M | ~5 GB |
| Whisper large-v3-turbo int8 | ~1.5 GB |
| **Total** | **~6.5 GB** (plenty of headroom; 14B Q4 at ~9 GB would also fit) |

Teammates with weaker machines: switch to `qwen2.5:3b-instruct-q4_K_M` and Whisper `small` on CPU
in `configs/models.yaml` (or a local override, see setup guide).
