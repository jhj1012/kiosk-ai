# Architecture

## Two programs, one repo

```
┌──────────────────────┐                 ┌──────────────────────────────┐   HTTPS   ┌────────────┐
│  kiosk_app (PySide6) │  ◄── UIA ────   │  assistant                   │ ◄───────► │ Gemini API │
│  - menu / cart / pay │   read tree,    │  audio → stt → agent → tts   │           └────────────┘
│  - knows nothing     │   click, type   │            │                 │
│    about the AI      │                 │            ▼                 │
└──────────────────────┘                 │         screen (UIA)         │
                                         └──────────────────────────────┘
```

The two programs run as separate processes. The only connection between them is the
Windows accessibility (UI Automation) layer. The AI model runs in the cloud (Gemini API); the
assistant sends it the conversation and the text of the kiosk screen. `assistant` must never import `kiosk_app`
(checked by `import-linter` in CI).

## assistant modules

| Module | Responsibility |
|---|---|
| `assistant/config.py` | Typed settings from `configs/*.yaml`, with `*.local.yaml` merged on top; loads the API key from a git-ignored `.env`. |
| `assistant/userio` | `UserInput.listen()` and the event-based `UserOutput` (`say`, `ask`, `show_elements`, `set_state`). Console implementation now; STT, TTS and the overlay implement the same interfaces later. |
| `assistant/screen` | Read the target window's UIA tree into a `Snapshot` (`reader.py`, pure Python), render it for the LLM (`format.py`), wait for the screen to settle (`settle.py`). `uia.py` is the only Windows/pywinauto module. |
| `assistant/llm` | Gemini API client (structured JSON output, retries, clear key/model errors), the per-screen JSON schema, the system prompt. |
| `assistant/agent` | One user turn: decide, act, reply (`loop.py`); run actions (`executor.py`); safety gate for payment and order-discarding buttons (`confirm_gate.py`); conversation history (`history.py`); the listen loop (`session.py`). |
| `assistant/audio`, `stt`, `tts` *(planned)* | Microphone, speech recognition, speech output. |
| `assistant/overlay` *(planned)* | PySide6 overlay window: avatar, subtitles, kiosk element images, blurred background. |

Run it with `uv run python -m assistant [--debug] [--model NAME]`. Each session logs every
screen, model answer and action to `logs/session-*.log` (git-ignored). `/reset` starts a new
conversation, `/quit` exits.

## How one user turn works

```
user text ──► read screen ──► LLM (history + CURRENT SCREEN) ──► "act"   ──► executor ──┐
                  ▲                                         └──► "reply" ──► say / ask   │
                  └──────────── settled new screen + RESULT notes ◄──────────────────────┘
```

1. `screen` reads the target window and waits until it has settled.
2. The LLM gets the system prompt, the history and the **current** screen as the last message.
3. It answers with JSON in one of two shapes (Gemini structured output with a JSON schema):
   - `act`: a short list of actions on the current screen. The executor runs them, the screen
     is read again, a `RESULT` note is added, and the loop asks the LLM again.
   - `reply`: a message to the user (`ask`, `tell`, or `confirm`). This ends the turn.
4. Every turn ends with exactly one `say()` or `ask()`: also on errors, when the model gets
   stuck, and at the step limit (`agent.max_steps_per_request` LLM calls), where a reply-only
   schema asks the model to sum up what was done.

### Screen snapshot

The reader drops window chrome, flattens unnamed containers, shows named containers as
`<regions>`, removes texts that repeat their region's name, and numbers enabled controls:

```
Text "옵션 선택"
[1] Button "처음으로"
[2] <옵션 목록> (scrollable: more below)
  Text "온도 선택"
  [3] CheckBox "온도 HOT +0원 (선택됨)" checked
  [4] CheckBox "온도 ICE +0원" unchecked
Button "수량 감소" (disabled)
Text "수량 1개"
[17] Button "수량 증가"
[19] Button "담기"
```

Each `Element` also keeps its bounding rectangle, the part not clipped by scroll areas, its
UIA RuntimeId and its patterns. That data is not in the LLM text; it is for the executor and
the planned overlay.

### LLM answer

```json
{"screen": "options for americano", "todo": "아이스 아메리카노 1잔",
 "need_to_ask": ["사이즈"], "next": "act",
 "actions": [{"do": "select", "target": "온도 ICE +0원"}]}
{"screen": "...", "todo": "...", "need_to_ask": ["사이즈"], "next": "reply", "kind": "ask",
 "message": "사이즈는 Regular와 Large 중 어떤 걸로 드릴까요?",
 "choices": ["사이즈 Regular +0원", "사이즈 Large +500원"]}
```

- Actions: `click` (with `times`), `select`, `unselect`, `type_text`, `scroll`, `wait`.
- **Targets are control names**, limited by the schema to the controls on the current screen
  (repeated names get a " (2)" suffix). With numbers, the model copied stale numbers from
  earlier answers and pressed the wrong control.
- `screen`, `todo` and `need_to_ask` are short notes written *before* the decision. They ground
  the model on the current screen. `need_to_ask` lists required choices the customer has not
  given. While it is not empty, the answer may only select choices; pressing on (e.g. add to
  cart) is rejected, so a default cannot silently decide for the customer. Entries are only
  enforced if they appear on the screen, and count as answered if the same answer selects an
  option containing them.
- The schema uses only keywords Gemini supports (no `const`, no string lengths; a unit test
  checks this). `max_output_tokens` stops runaway answers.
- Why JSON schema instead of function calling: see [decisions.md](decisions.md).

### Executor rules

- Act through UIA patterns: Invoke, Toggle, SelectionItem, Value, RangeValue (scroll bars).
  The mouse is only a logged fallback for controls without any pattern.
- `select`/`unselect` read the toggle state first, so they are idempotent. Unchecking the
  selected option of a single-choice group is impossible in UIA; that is a note, not an error.
- After each action the screen is re-read. The next target is found by RuntimeId. If controls
  appeared or disappeared (new page, other tab, rebuilt cart), the rest of the batch is
  skipped and the model looks again.
- A repeated press whose target disappears (a delete button removing its row) stops quietly.
- `type_text` sets an edit field's value, or presses on-screen keys whose names end with each
  character (e.g. "숫자 1").

### Safety gates (code, not prompt)

`agent.payment_button_pattern` and `agent.discard_button_pattern` (regexes in
`configs/settings.yaml`, per kiosk) mark buttons that pay or throw the order away. Pressing
one is blocked unless the previous reply was a `confirm` (for payment: order and total read
back) and a small yes/no classification of the user's answer says yes.

### History

Only the latest screen is ever in the context. Finished turns are condensed to the user's
words and the final reply; the actions and results in between are only kept for the current
turn. Long contexts made answers worse in tests (and cost more), so this matters. The stable
prefix also lets the API reuse its prompt cache between the calls of one turn.

### Threading

`Agent.handle()` is a plain blocking call. `__main__` already runs the agent in a worker
thread (the main thread only waits), as the Qt overlay will need the main thread. `UiaScreen`
creates its COM objects in the thread that calls `attach()` and refuses calls from other
threads.

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
| Avatar | Animated character with states: idle, listening, thinking, acting, speaking. |
| Subtitles | Text of what the AI says, synced to TTS (pyttsx3 word callbacks). |
| Kiosk images | Crop screenshots of the elements being discussed, using their UIA bounding rectangles (e.g. show the HOT / ICE buttons when asking about temperature). |

### Constraints for earlier phases

These keep the overlay a plug-in addition instead of a rewrite. The text agent follows them:

- ✅ **Event-based output interface**: `say(text)`, `ask(question, choices)` (each choice carries
  its `Element` with rectangles), `show_elements(elements)`, `set_state(...)`.
- ✅ **Bounding rectangles** (full and visible part) are kept in snapshots.
- ✅ **Agent loop does not own the main thread.** A Qt `UserOutput` must forward calls to the
  GUI thread with signals.
- ✅ **Act through UIA patterns**, which work while an overlay covers the kiosk. If the mouse
  fallback is ever used, the overlay must be click-through (`Qt.WindowTransparentForInput`)
  or hide during the click.
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
  This also happens when the user switches desktops after starting the kiosk; restart it on
  the current desktop.
- `uv run python scripts/dump_uia_tree.py [--full | --check]` prints the raw tree.

Learned while building the agent:

- The title bar (system menu, minimize/maximize/close) is part of the window's tree; the
  reader drops the `TitleBar` subtree.
- Children scrolled out of a `QScrollArea` still report `IsOffscreen = False` and stay in the
  tree, and Invoke/Toggle work on them without scrolling. Visibility must be computed by
  clipping with the ancestors' rectangles.
- `QScrollArea` has no Scroll pattern. Its `QScrollBar` has RangeValue (value in pixels,
  LargeChange only 20 px); scrolling sets that value.
- Toggling the checked button of an exclusive `QButtonGroup` does nothing; in a non-exclusive
  group it unchecks. Check the toggle state before toggling.
- Names are not unique across control types (a `Text "결제"` title and a `Button "결제"`):
  never act on a name without the control type.
- Qt labels and containers also report an Invoke pattern; only the control type tells what can
  really be used.
- While the test kiosk "processes" a payment, every button is disabled for ~2 s but the order
  list rows stay enabled. "Busy" detection ignores list/tree/data rows.
- One cache request (`BuildUpdatedCache` with the subtree scope) reads the whole window in
  10–30 ms, fast enough to poll for a settled screen every 100 ms.
- Two assistants attached to the same kiosk fight over it: run only one.
