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
| `assistant/overlay` *(planned)* | PySide6 overlay window: avatar, subtitles, kiosk element images, blurred background. |

## Agent loop (planned)

1. User presses a talk key and speaks: "아이스 아메리카노 두 잔 주세요"
2. `stt` returns the Korean text.
3. `screen` lists visible elements, e.g. `[12] Button "아이스 아메리카노"`.
4. `llm` receives the request + element list, returns tool calls like `click(12)`.
5. `screen` executes them, re-reads the screen, loop until done.
6. `tts` speaks the result: "아이스 아메리카노 두 잔을 담았습니다."

Risky steps (payment) require spoken confirmation from the user.

## Planned: visual overlay

A later phase adds a visual layer so users can also *see* what the assistant is doing.

```
┌──────────────────── screen ────────────────────┐
│  Test Kiosk window (blurred behind overlay)    │
│   ┌──────────── overlay window ─────────────┐  │
│   │  [avatar]   subtitle: what the AI says  │  │
│   │                                         │  │
│   │   ┌───────┐  ┌───────┐                  │  │
│   │   │  HOT  │  │  ICE  │  <- images       │  │
│   │   └───────┘  └───────┘     cropped from │  │
│   │                            the kiosk    │  │
│   └─────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

| Part | Plan |
|---|---|
| Window | Separate PySide6 window owned by `assistant`: frameless, always on top, translucent, positioned over the target window. Still never imports `kiosk_app`. |
| Blur | Capture the kiosk window, blur it, and use it as the overlay background (refreshed when the screen changes). Windows 11 DWM acrylic is an alternative. |
| Avatar | Animated character with states: idle, listening, thinking, speaking. |
| Subtitles | Text of what the AI says, synced to TTS (pyttsx3 word callbacks). |
| Kiosk images | Crop screenshots of the elements being discussed, using their UIA bounding rectangles (e.g. show the HOT / ICE buttons when asking about temperature). |

### Constraints for earlier phases

These keep the overlay a plug-in addition instead of a rewrite:

- **Event-based output interface.** Not just `say(text)`: also e.g. `ask(question, choices)`,
  `show_elements(...)`, `set_state(idle|listening|thinking|speaking)`. The console implementation
  just prints them; the overlay renders them.
- **Keep bounding rectangles** of elements in screen snapshots (not needed in the LLM text).
- **Agent loop must not own the main thread.** Qt needs the main thread, so the agent runs in a
  worker thread and sends events to the UI via signals.
- **Act through UIA patterns (Invoke / Toggle), not mouse clicks.** Patterns work even when the
  overlay covers the kiosk. If a mouse fallback is ever needed, the overlay must be click-through
  (`Qt.WindowTransparentForInput`) or hide during the click.
- **Exclude the overlay from screen capture** with `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`,
  so kiosk screenshots never contain the overlay itself.

## Kiosk requirements for accessibility

So that the assistant can find elements reliably, every interactive widget in `kiosk_app`
must have a meaningful `accessibleName` (and `objectName`). Real-world kiosks may not,
which is why a vision fallback may be added later.

### Lessons from the test kiosk (verified with pywinauto)

- Widgets placed inside list items with `QListWidget.setItemWidget()` are **not** in the UIA
  tree. The cart therefore uses plain row widgets in a `QScrollArea`.
- Checkable `QPushButton`s (category tabs, options, payment methods) appear as `CheckBox`
  with a Toggle pattern. A UIA `toggle()` does not emit `clicked`, so the kiosk reacts to
  `toggled`. Checked buttons also add " (선택됨)" to their name.
- Option selection is a page inside the main window, not a separate `QDialog`, so everything
  stays under the "Test Kiosk" window.
- A window on another Windows virtual desktop is "cloaked" and cannot be found through UIA.
- `uv run python scripts/dump_uia_tree.py [--full | --check]` prints what the assistant sees.
