"""Agent loop tests with a fake screen and a scripted LLM (no Gemini API, no Windows)."""

from __future__ import annotations

from assistant.agent.loop import FALLBACK_MESSAGE, LLM_ERROR_MESSAGE, SCREEN_ERROR_MESSAGE, Agent
from assistant.agent.session import GREETING, RESET_MESSAGE, run_session
from assistant.llm.prompts import CONFIRM_SCHEMA, OUT_OF_STEPS
from assistant.screen.base import WindowNotFoundError
from tests.agent_fakes import (
    FAST_SCREEN,
    LLM_DOWN,
    FakeLlm,
    FakeScreen,
    RecordingOutput,
    act,
    agent_config,
    click,
    reply,
    select,
)
from tests.screen_fakes import button, check, text, window


def make_agent(screen: FakeScreen, llm: FakeLlm, **config: object) -> tuple[Agent, RecordingOutput]:
    output = RecordingOutput()
    return Agent(screen, llm, output, agent_config(**config), FAST_SCREEN), output


def start_and_options() -> FakeScreen:
    """Start page with "주문하기"; pressing it shows HOT/ICE options."""
    options = window(text("온도 선택"), check("HOT", on=True), check("ICE"), button("담기"))
    screen = FakeScreen(window(text("어서 오세요"), button("주문하기")))
    screen.on_press["주문하기"] = lambda: setattr(screen, "page", options)
    return screen


def screens_in(messages: list[dict[str, str]]) -> list[str]:
    return [m["content"] for m in messages if m["content"].startswith("CURRENT SCREEN:")]


def test_reply_only_turn_gives_exactly_one_message() -> None:
    screen = start_and_options()
    llm = FakeLlm(reply("어떤 메뉴를 드릴까요?"))
    agent, output = make_agent(screen, llm)
    result = agent.handle("안녕하세요")
    assert result.message == "어떤 메뉴를 드릴까요?"
    assert output.messages == [("ask", ("어떤 메뉴를 드릴까요?", []))]
    messages, _ = llm.requests[0]
    assert messages[0]["role"] == "system"
    assert messages[1]["content"] == 'Customer: "안녕하세요"'
    assert messages[-1]["content"] == 'CURRENT SCREEN:\nText "어서 오세요"\n[1] Button "주문하기"'


def test_act_then_ask_with_choices_from_new_screen() -> None:
    screen = start_and_options()
    llm = FakeLlm(
        act(click("주문하기")), reply("HOT과 ICE 중 어떤 걸로 드릴까요?", choices=["HOT", "ICE"])
    )
    agent, output = make_agent(screen, llm)
    agent.handle("아메리카노 주세요")

    assert screen.calls == [("invoke", "주문하기")]
    assert ("show", ["주문하기"]) in output.events
    assert output.messages == [("ask", ("HOT과 ICE 중 어떤 걸로 드릴까요?", ["HOT", "ICE"]))]
    second, _ = llm.requests[1]
    assert 'RESULT:\n- pressed Button "주문하기"' in [m["content"] for m in second]
    # Only the newest screen is in the context, as the last message.
    assert len(screens_in(second)) == 1
    assert "ICE" in second[-1]["content"]


def test_select_toggles_only_unchecked_choices() -> None:
    screen = start_and_options()
    llm = FakeLlm(
        act(click("주문하기")),
        act(select("ICE"), select("HOT")),
        reply("ICE로 골랐어요.", kind="tell"),
    )
    agent, _ = make_agent(screen, llm)
    agent.handle("아이스 아메리카노")
    # [1] HOT was already checked: no toggle; [2] ICE was toggled on.
    assert screen.calls == [("invoke", "주문하기"), ("toggle", "ICE")]
    notes = [m["content"] for m in llm.requests[2][0] if m["content"].startswith("RESULT")]
    assert 'CheckBox "HOT" was already selected' in notes[-1]


def test_invalid_id_is_reported_and_the_model_retries() -> None:
    screen = start_and_options()
    llm = FakeLlm(
        act(click("없는 버튼")), act(click("주문하기")), reply("다음 화면이에요.", kind="tell")
    )
    agent, output = make_agent(screen, llm)
    agent.handle("주문할게요")
    retry_messages, _ = llm.requests[1]
    assert any(
        '"없는 버튼" is not a control on the CURRENT SCREEN' in m["content"] for m in retry_messages
    )
    assert screen.calls == [("invoke", "주문하기")]
    assert output.messages == [("say", "다음 화면이에요.")]


def test_invalid_json_is_reported_and_the_model_retries() -> None:
    llm = FakeLlm('{"thought": "cut off', reply("네, 말씀하세요."))
    agent, output = make_agent(start_and_options(), llm)
    agent.handle("저기요")
    assert any("not valid JSON" in m["content"] for m in llm.requests[1][0])
    assert len(output.messages) == 1


def test_step_limit_ends_with_one_reply_from_reply_only_schema() -> None:
    screen = FakeScreen(window(button("새로고침")))
    llm = FakeLlm(
        *[act(click("새로고침"))] * 3, reply("세 번 눌렀지만 끝나지 않았어요.", kind="tell")
    )
    agent, output = make_agent(screen, llm, max_steps_per_request=3)
    agent.handle("계속 눌러 주세요")
    assert len(llm.requests) == 4
    final_messages, final_schema = llm.requests[3]
    assert final_schema["properties"]["next"]["enum"] == ["reply"]  # reply only
    assert any(m["content"] == OUT_OF_STEPS for m in final_messages)
    assert output.messages == [("say", "세 번 눌렀지만 끝나지 않았어요.")]


def test_repeating_a_failed_batch_ends_the_turn_early() -> None:
    screen = FakeScreen(window(button("결제")))  # blocked by the payment gate every time
    llm = FakeLlm(
        act(click("결제")), act(click("결제")), reply("결제 전에 주문을 확인할게요.", kind="tell")
    )
    agent, output = make_agent(screen, llm, max_steps_per_request=10)
    agent.handle("결제")
    assert len(llm.requests) == 3  # second identical batch is not run; then the final reply
    assert llm.requests[2][1]["properties"]["next"]["enum"] == ["reply"]
    assert output.messages == [("say", "결제 전에 주문을 확인할게요.")]


def test_step_limit_falls_back_to_fixed_message() -> None:
    screen = FakeScreen(window(button("새로고침")))
    llm = FakeLlm(act(click("새로고침")), act(click("새로고침")), "not json")
    agent, output = make_agent(screen, llm, max_steps_per_request=2)
    agent.handle("계속")
    assert output.messages == [("say", FALLBACK_MESSAGE)]


def test_llm_error_gives_one_apology() -> None:
    agent, output = make_agent(start_and_options(), FakeLlm(LLM_DOWN))
    agent.handle("아메리카노")
    assert output.messages == [("say", LLM_ERROR_MESSAGE)]


def test_screen_error_gives_one_apology() -> None:
    screen = start_and_options()
    screen.fail_read = WindowNotFoundError("gone")
    agent, output = make_agent(screen, FakeLlm())
    agent.handle("아메리카노")
    assert output.messages == [("say", SCREEN_ERROR_MESSAGE)]


def pay_screen() -> FakeScreen:
    screen = FakeScreen(window(text("결제할 금액 9000원"), check("카드"), button("결제")))
    screen.on_press["결제"] = lambda: setattr(
        screen, "page", window(text("결제 완료"), button("처음으로"))
    )
    return screen


def test_payment_button_is_blocked_without_confirmation() -> None:
    screen = pay_screen()
    llm = FakeLlm(
        act(select("카드"), click("결제")),
        reply("카드로 9000원 결제할까요?", kind="confirm"),
    )
    agent, output = make_agent(screen, llm)
    agent.handle("카드로 결제해 주세요")
    assert ("invoke", "결제") not in screen.calls
    assert ("toggle", "카드") in screen.calls
    notes = [m["content"] for m in llm.requests[1][0] if m["content"].startswith("RESULT")]
    assert "BLOCKED" in notes[-1]
    assert output.messages == [("ask", ("카드로 9000원 결제할까요?", []))]


def test_payment_allowed_after_confirm_and_yes() -> None:
    screen = pay_screen()
    llm = FakeLlm(
        reply("카드로 9000원 결제할까요?", kind="confirm"),
        act(click("결제")),
        {"answer": "yes"},  # confirmation check
        reply("결제가 완료되었어요.", kind="tell"),
    )
    agent, output = make_agent(screen, llm)
    agent.handle("결제할게요")
    agent.handle("네, 결제해 주세요")
    assert ("invoke", "결제") in screen.calls
    assert llm.requests[2][1] == CONFIRM_SCHEMA
    assert "네, 결제해 주세요" in llm.requests[2][0][0]["content"]
    assert [m[0] for m in output.messages] == ["ask", "say"]


def test_payment_blocked_when_customer_does_not_agree() -> None:
    screen = pay_screen()
    llm = FakeLlm(
        reply("카드로 9000원 결제할까요?", kind="confirm"),
        act(click("결제")),
        {"answer": "no"},
        reply("알겠어요, 결제하지 않을게요.", kind="tell"),
    )
    agent, _ = make_agent(screen, llm)
    agent.handle("결제할게요")
    agent.handle("아니요 잠깐만요")
    assert ("invoke", "결제") not in screen.calls


def test_confirmation_only_counts_for_the_next_turn() -> None:
    screen = pay_screen()
    llm = FakeLlm(
        reply("카드로 9000원 결제할까요?", kind="confirm"),
        reply("쿠폰은 없어요.", kind="tell"),
        act(click("결제")),
        reply("결제 전에 다시 확인할게요.", kind="tell"),
    )
    agent, _ = make_agent(screen, llm)
    agent.handle("결제할게요")
    agent.handle("쿠폰 있어요?")
    agent.handle("결제")
    assert ("invoke", "결제") not in screen.calls


def test_payment_gate_can_be_disabled() -> None:
    screen = pay_screen()
    llm = FakeLlm(act(click("결제")), reply("결제했어요.", kind="tell"))
    agent, _ = make_agent(screen, llm, confirm_before_payment=False)
    agent.handle("결제")
    assert ("invoke", "결제") in screen.calls


def test_history_keeps_turns_but_not_old_screens() -> None:
    screen = start_and_options()
    llm = FakeLlm(
        reply("무엇을 드릴까요?"), act(click("주문하기")), reply("HOT, ICE 중 골라 주세요.")
    )
    agent, _ = make_agent(screen, llm)
    agent.handle("안녕하세요")
    agent.handle("아메리카노")
    last_messages, _ = llm.requests[-1]
    contents = [m["content"] for m in last_messages]
    assert 'Customer: "안녕하세요"' in contents and 'Customer: "아메리카노"' in contents
    assert len(screens_in(last_messages)) == 1


class ScriptedInput:
    def __init__(self, *lines: str) -> None:
        self.lines = list(lines)

    def listen(self) -> str | None:
        return self.lines.pop(0) if self.lines else None


def test_session_greets_handles_commands_and_ends() -> None:
    screen = start_and_options()
    llm = FakeLlm(reply("무엇을 드릴까요?"), reply("다시 무엇을 드릴까요?"))
    agent, output = make_agent(screen, llm)
    run_session(agent, ScriptedInput("안녕", "  ", "/reset", "안녕", "/quit", "무시됨"), output)
    assert [m[1] if m[0] == "say" else m[1][0] for m in output.messages] == [
        GREETING,
        "무엇을 드릴까요?",
        RESET_MESSAGE,
        "다시 무엇을 드릴까요?",
    ]
    # After /reset the first turn is forgotten.
    assert 'Customer: "안녕"' in [m["content"] for m in llm.requests[1][0]]
    assert len([m for m in llm.requests[1][0] if m["content"].startswith("Customer")]) == 1


def test_repeating_an_invalid_answer_ends_the_turn_early() -> None:
    llm = FakeLlm(
        act(click("없는 버튼")),
        act(click("없는 버튼")),
        reply("다시 말씀해 주시겠어요?", kind="tell"),
    )
    agent, output = make_agent(start_and_options(), llm, max_steps_per_request=10)
    agent.handle("주문")
    assert len(llm.requests) == 3
    assert output.messages == [("say", "다시 말씀해 주시겠어요?")]


def test_discard_button_needs_confirmation_too() -> None:
    home = {"pressed": False}
    screen = FakeScreen(window(text("옵션 선택"), button("처음으로"), button("취소")))
    screen.on_press["처음으로"] = lambda: home.update(pressed=True)
    llm = FakeLlm(
        act(click("처음으로")),  # blocked: it would throw away the order
        act(click("취소")),  # the model uses the item's cancel button instead
        reply("메뉴 화면으로 돌아왔어요.", kind="tell"),
        reply("주문을 모두 취소할까요?", kind="confirm"),
        act(click("처음으로")),
        {"answer": "yes"},
        reply("처음 화면으로 돌아갔어요.", kind="tell"),
    )
    agent, _ = make_agent(screen, llm)
    agent.handle("이거 말고 다른 거 볼게요")
    assert not home["pressed"]
    assert any("throws away the whole order" in m["content"] for m in llm.requests[1][0])
    agent.handle("처음부터 다시 할래요")
    agent.handle("네")
    assert home["pressed"]
