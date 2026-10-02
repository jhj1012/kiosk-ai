# Architecture

## Two programs, one repo

```
┌──────────────────────┐                 ┌──────────────────────────────┐
│  kiosk_app (PySide6) │  ◄── UIA ────   │  assistant                   │
│  - menu / cart / pay │   read tree,    │  audio → stt → agent → tts   │
│  - knows nothing     │   click, type   │            │                 │
│    about the AI      │                 │            ▼                 │
└──────────────────────┘                 │         screen (UIA)         │
                                         └──────────────────────────────┘
```

The two programs run as separate processes. The only connection between them is the
Windows accessibility (UI Automation) layer. `assistant` must never import `kiosk_app`
(checked by `import-linter` in CI).

## assistant modules

| Module | Responsibility |
|---|---|
| `assistant/audio` | Microphone capture (push-to-talk first, VAD later). |
| `assistant/stt` | Speech → text with faster-whisper (Korean). |
| `assistant/llm` | Ollama client, system prompts, tool definitions. |
| `assistant/tts` | Text → speech. Common interface; `pyttsx3` engine first. |
| `assistant/screen` | Read the UIA tree of the target window into a compact text list; perform actions (click, type, scroll). |
| `assistant/agent` | Main loop: listen → transcribe → read screen → LLM decides tool calls → act → speak. |

## Agent loop (planned)

1. User presses a talk key and speaks: "아이스 아메리카노 두 잔 주세요"
2. `stt` returns the Korean text.
3. `screen` lists visible elements, e.g. `[12] Button "아이스 아메리카노"`.
4. `llm` receives the request + element list, returns tool calls like `click(12)`.
5. `screen` executes them, re-reads the screen, loop until done.
6. `tts` speaks the result: "아이스 아메리카노 두 잔을 담았습니다."

Risky steps (payment) require spoken confirmation from the user.

## Kiosk requirements for accessibility

So that the assistant can find elements reliably, every interactive widget in `kiosk_app`
must have a meaningful `accessibleName` (and `objectName`). Real-world kiosks may not,
which is why a vision fallback may be added later.
