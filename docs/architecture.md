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
| `assistant/userio` | `UserInput.listen()` and the event-based `UserOutput` (`say`, `ask`, `show_elements`, `set_state`). Console input and output (`console.py`), speech input (`speech.py`); TTS and the overlay implement `UserOutput` later. |
| `assistant/screen` | Read the target window's UIA tree into a `Snapshot` (`reader.py`, pure Python), render it for the LLM (`format.py`), wait for the screen to settle (`settle.py`). `uia.py` is the only Windows/pywinauto module. |
| `assistant/llm` | Gemini API client (structured JSON output, retries, clear key/model errors), the per-screen JSON schema, the system prompt. |
| `assistant/agent` | One user turn: decide, act, reply (`loop.py`); run actions (`executor.py`); safety gate for payment and order-discarding buttons (`confirm_gate.py`); conversation history (`history.py`); the listen loop (`session.py`). |
| `assistant/audio` | Voice activity detection (`vad.py`, energy-based, pure Python), WAV encoding (`wav.py`), one utterance from a frame source (`recorder.py`), the microphone (`mic.py`, the only `sounddevice` module), the half-duplex `SpeakingGate` (`duplex.py`). |
| `assistant/stt` | Speech recognition with the Gemini API audio input (`transcriber.py`): prompt, `{sounds, speech, text}` schema, non-speech filtering, vocabulary hints from the screen. |
| `assistant/tts` *(planned)* | Speech output. |
| `assistant/overlay` *(planned)* | PySide6 overlay window: avatar, subtitles, kiosk element images, blurred background. |

Run it with `uv run python -m assistant [--voice] [--debug] [--model NAME]`. Each session
logs every screen, model answer, action and recognized utterance to `logs/session-*.log`
(git-ignored). Typed: `/reset` starts a new conversation, `/quit` exits; voice: Ctrl+C exits.

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
  checks this). Each action is one flat object (`do`, `target`, `times`, ...): separate `anyOf`
  variants per action repeated the list of names and Gemini rejected the schema as too complex
  (400) on screens with ~18 controls. `max_output_tokens` stops runaway answers.
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
`configs/settings.yaml`, per kiosk) mark buttons that pay or throw the order away.

- **Pay** is allowed when the user has asked to pay ("결제할게요", even a few turns earlier)
  and has not changed the order since, judged by a small yes/no classification of their last
  messages, and when the same answer carries a short read-back of the order and total. The
  read-back is a statement, not a question, shown at the start of the turn's reply
  ("아이스 아메리카노 1잔, 초코 쿠키 1개, 총 6,500원입니다. 결제가 완료되었어요…"). The user is
  never asked "결제하시겠어요?": asking to pay is the approval.
- **Discard** is allowed only right after the user said yes to a `confirm` question.

The prompt also tells the model to remember earlier answers: kiosks ask some things twice
(eat in or take out at the start and again before payment), and the assistant answers the
second one itself instead of asking again.

### History

Only the latest screen is ever in the context. Finished turns are condensed to the user's
words and the final reply; the actions and results in between are only kept for the current
turn. Long contexts made answers worse in tests (and cost more), so this matters. The stable
prefix also lets the API reuse its prompt cache between the calls of one turn.

### Next customer

The assistant runs all day, like the kiosk. Each customer gets a fresh conversation, so the
previous customer's messages, remembered answers and payment approval are neither reused nor
sent to the model again (`agent/customer.py`):

- **From what is said:** in a busy cafe the next customer starts talking before any timer
  runs out. If a message sounds like a different person (a greeting and a new order right
  after a payment, "다음 손님이에요", ...), the model replies with kind `new_customer` and asks
  "새로 주문하시는 손님이신가요?". On yes (a small yes/no classification), the agent presses the
  kiosk's order-discarding button (e.g. "처음으로", if the kiosk is not already on its idle
  screen), starts a new conversation and continues with the new customer's original request,
  so they do not have to repeat it. On no, the conversation simply continues.
- **From time, as a fallback:** at start-up the assistant learns the kiosk's **idle screen** (the screen it shows while
  waiting; identified by its set of controls, so changing texts do not matter).
- Before each message: if the kiosk is back on the idle screen and nobody talked for
  `agent.new_customer_after_s` (30 s), a new conversation starts. A customer who asks
  "그러면 이제 어디로 가야 해요?" right after paying is still the same customer and gets an answer
  with their order number.
- If nobody talked for `agent.abandoned_after_s` (180 s) and the screen still shows an
  unfinished order, the next person is a new customer too; the model is told to ask whether to
  continue that order or start over.
- A request to pay is used up by the payment: an earlier "결제할게요" never approves a second
  payment.
- If the kiosk window is missing at start-up, the assistant waits for it instead of exiting.
- Start the assistant while the kiosk shows its idle screen (otherwise it learns the wrong one).

### Threading

`Agent.handle()` is a plain blocking call. `__main__` already runs the agent in a worker
thread (the main thread only waits), as the Qt overlay will need the main thread. `UiaScreen`
creates its COM objects in the thread that calls `attach()` and refuses calls from other
threads.

## Voice input

`uv run python -m assistant --voice` replaces the typed console input with `SpeechInput`
(`userio/speech.py`). It implements the same `UserInput.listen() -> str | None`, so the agent
and `run_session` are unchanged: the recognized text goes into `agent.handle()` exactly like
a typed line.

```
listen() ──► recorder.record() ──► utterance (WAV) ──► Gemini STT ──► {"sounds", "speech", "text"}
   ▲          mic frames + VAD                         (stt.model)          │
   │                                                           not speech ──┤ (noise, cough,
   └───────────── keep listening ◄─────────────────────────────────────────┘  silence)
                                                               speech ──► return text ──► agent
```

1. `run_session` sets `LISTENING` and calls `listen()` in the agent thread.
2. The first call opens the microphone and measures the background noise for
   `audio.calibration_s` (1 s). Audio captured before each `listen()` is dropped: it was
   recorded while the assistant was thinking or speaking.
3. **Voice activity detection** (`audio/vad.py`): a 30 ms frame is *loud* when its RMS level
   is above max(noise x `threshold_factor`, `min_threshold`). An utterance starts when the last
   300 ms contain `start_ms` (90 ms) of loud audio. The frames don't have to be in a row:
   syllables have short dips, and a quick "네" has only ~150 ms of loud audio. It keeps
   `pre_roll_ms` (300 ms) from before the first loud frame, so the first syllable isn't cut.
   It ends after `silence_end_ms` (800 ms) of quiet, and at `max_utterance_s` (15 s) at the
   latest. Sounds with less than `min_utterance_ms` (120 ms) of loud audio are dropped. While
   nobody speaks, the noise level keeps adapting.
4. The utterance is sent as WAV to the speech model (`stt.model`, a different model than the
   agent's, see [decisions.md](decisions.md)), while the state is `THINKING`. The answer is
   structured JSON: `sounds` (a few words on what is audible, written first; it grounds the
   decision like the agent's `screen` note), `speech` and `text`. Non-speech answers are
   ignored and listening continues, so noise never reaches the agent.
5. Speech is printed as `나(음성)> ...`, logged, and returned to `run_session`.

Vocabulary hints: with `stt.vocabulary_hints`, the names on the current kiosk screen (prices
and "(선택됨)" removed) are added to the prompt as a spelling list, which fixed
"할메가 커피" → "할메가커피" and "포장이여" → "포장이요" in tests. The prompt says the list
is *not* what was said: an earlier prompt with a cafe framing made the model invent
"아이스 아메리카노 한 잔 주세요" from silence. The hints are read by calling `screen.read()`
from inside `listen()`, which runs in the agent thread, so UIA objects stay in that thread.

Errors never end the all-day loop:

| Problem | What happens |
|---|---|
| No microphone, device busy or unplugged | `MicError`; the console shows it once, the mic is retried every 5 s, "마이크가 다시 연결되었어요." when it works again. |
| Windows microphone privacy setting off | The stream opens but delivers only zeros. Calibration detects this (`SilentMicError`) and the console explains the setting. |
| Gemini error (rate limit, 5xx, timeout) | The client's retries (same code as the agent's). If it still fails, the assistant says "죄송해요, 잘 못 들었어요. 다시 한 번 말씀해 주시겠어요?" and listens again. |
| Steady loud noise (coffee grinder) | Utterances run to the 15 s cap and come back as non-speech; after two in a row the noise level is measured again. |
| Device refuses 16 kHz (WDM-KS) | The microphone opens at the device's own rate; the VAD and Gemini handle any rate. |

Developer options: `--push-to-talk` waits for Enter before each utterance (the VAD still
finds the start and end), `--save-audio` writes each utterance to `recordings/` (git-ignored).
`scripts/mic_check.py` lists devices, shows live levels and transcribes one utterance or a
WAV file.

### Half-duplex and the TTS phase

The assistant must not hear itself. Today `say()` is synchronous and `listen()` drops the
audio captured before it starts, so nothing the assistant outputs is ever transcribed. For TTS
that plays in the background, `audio/duplex.py` has a `SpeakingGate`: the microphone drops
frames while it is set and for `audio.echo_tail_ms` (300 ms) afterwards, and a muted
microphone is not mistaken for a lost one. `__main__._speech_input` creates the gate; the TTS
phase should:

1. Create the gate once in `__main__` and pass it to both `Microphone` and the TTS output.
2. Wrap every playback in `with gate.speaking(): ...` (also on errors).
3. Keep `say()` blocking until playback has ended (or the gate set until then), so the
   avatar's `SPEAKING` state and the subtitles stay in sync.

Barge-in (the customer interrupting the assistant) is not supported: it would need echo
cancellation, which the laptop's microphone array partly does in hardware but we can't rely
on.

### Requests per spoken turn

Measured in the voice E2E test (iced americano, take-out, size, card payment):

- **Speech recognition: exactly 1 request per utterance** on `stt.model` (2.0–2.9 s each),
  including noise that the VAD let through and that came back as non-speech.
- **Agent: 1–4 requests per turn** on `llm.model` (decisions plus the yes/no checks; about 2.4
  on average), the same as for typed input. Speech adds nothing to the agent's requests.
- So a five-turn order costs ~5 STT + ~12 agent requests. At ~15 requests/min per model, the
  agent's model is the bottleneck, which is why STT uses a different model. Daily limits
  matter more in long test sessions: ~500 requests/day for the flash-lite models, but only
  20/day (5/min) for `gemini-3.8-flash` on the free tier.

Latency from the end of speech to the text: 3.2–5.3 s, which is 0.8 s of silence detection
(`silence_end_ms`) plus the STT request. Lower `silence_end_ms` makes it faster but cuts off
people who pause.

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
