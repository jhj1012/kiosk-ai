"""Tests for switching to the next customer (fake clock, fake screen, scripted LLM)."""

from __future__ import annotations

from assistant.agent.customer import CustomerTracker, Switch
from assistant.agent.loop import NEW_CUSTOMER_NOTE, Agent
from tests.agent_fakes import (
    FAST_SCREEN,
    FakeLlm,
    FakeScreen,
    RecordingOutput,
    act,
    agent_config,
    click,
    reply,
)
from tests.screen_fakes import button, snapshot, text, window

IDLE = snapshot(text("어서 오세요"), button("주문하기"))
MENU = snapshot(button("아메리카노"), button("결제하기"))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def tracker(clock: Clock) -> CustomerTracker:
    t = CustomerTracker(new_customer_after_s=30, abandoned_after_s=180, clock=clock)
    t.learn_idle_screen(IDLE)
    return t


def test_same_customer_while_talking_or_right_after_the_order() -> None:
    clock = Clock()
    t = tracker(clock)
    assert t.check(IDLE) is Switch.SAME  # nobody talked yet
    t.touch()
    clock.now = 10
    assert t.check(MENU) is Switch.SAME
    assert t.check(IDLE) is Switch.SAME  # "이제 어디로 가요?" right after paying


def test_new_customer_when_idle_and_quiet() -> None:
    clock = Clock()
    t = tracker(clock)
    t.touch()
    clock.now = 31
    assert t.check(IDLE) is Switch.AFTER_IDLE
    assert t.check(MENU) is Switch.SAME  # a customer still in the middle of an order
    clock.now = 181
    assert t.check(MENU) is Switch.ABANDONED
    assert t.check(IDLE) is Switch.AFTER_IDLE
    t.forget()
    assert t.check(MENU) is Switch.SAME


def test_idle_screen_is_recognised_by_its_controls_not_its_text() -> None:
    t = tracker(Clock())
    assert t.is_idle(snapshot(text("다른 안내 문구"), button("주문하기")))
    assert not t.is_idle(MENU)


def make_agent(screen: FakeScreen, llm: FakeLlm, clock: Clock) -> tuple[Agent, RecordingOutput]:
    output = RecordingOutput()
    agent = Agent(screen, llm, output, agent_config(), FAST_SCREEN, clock=clock)
    agent.start()
    return agent, output


def customers_in(llm: FakeLlm, request: int) -> list[str]:
    messages, _ = llm.requests[request]
    return [m["content"] for m in messages if m["content"].startswith("Customer:")]


def test_next_customer_gets_a_fresh_conversation() -> None:
    clock = Clock()
    screen = FakeScreen(window(text("어서 오세요"), button("주문하기")))
    llm = FakeLlm(
        reply("주문이 완료되었어요. 주문번호는 1번이에요.", kind="tell"),
        reply("주문번호 1번이 불리면 카운터에서 받으시면 돼요.", kind="tell"),
        reply("어서 오세요! 무엇을 드릴까요?"),
    )
    agent, _ = make_agent(screen, llm, clock)
    agent.handle("결제해 주세요")
    clock.now = 15  # the same customer asks right after the order
    agent.handle("그러면 이제 어디로 가야 해요?")
    assert customers_in(llm, 1) == [
        'Customer: "결제해 주세요"',
        'Customer: "그러면 이제 어디로 가야 해요?"',
    ]
    clock.now = 100  # the kiosk is idle and nobody talked for a while
    agent.handle("안녕하세요")
    assert customers_in(llm, 2) == ['Customer: "안녕하세요"']  # nothing from the last customer


def test_abandoned_order_is_not_silently_inherited() -> None:
    clock = Clock()
    idle = window(text("어서 오세요"), button("주문하기"))
    screen = FakeScreen(idle)
    menu = window(button("아메리카노"), text("장바구니 1개"))
    screen.on_press["주문하기"] = lambda: setattr(screen, "page", menu)
    llm = FakeLlm(
        act(click("주문하기")),
        reply("무엇을 드릴까요?"),
        reply("이전 손님의 주문이 남아 있어요. 이어서 하실까요, 처음부터 하실까요?"),
    )
    agent, _ = make_agent(screen, llm, clock)
    agent.handle("주문할게요")
    clock.now = 500  # walked away; the menu with a cart is still on screen
    agent.handle("아메리카노 주세요")
    messages, _ = llm.requests[2]
    contents = [m["content"] for m in messages]
    assert 'Customer: "주문할게요"' not in contents
    assert NEW_CUSTOMER_NOTE in contents


def test_a_payment_request_is_used_up_by_the_payment() -> None:
    clock = Clock()
    screen = FakeScreen(window(text("결제할 금액 9000원"), button("결제")))
    llm = FakeLlm(
        act(click("결제"), message="총 9000원입니다."),
        {"answer": "yes"},
        reply("결제가 완료되었어요.", kind="tell"),
        act(click("결제"), message="총 9000원입니다."),
        {"answer": "no"},
        reply("무엇을 도와드릴까요?"),
    )
    agent, _ = make_agent(screen, llm, clock)
    agent.handle("결제해 주세요")
    agent.handle("고마워요")
    # The second payment check only sees messages after the payment.
    check_prompt = llm.requests[4][0][0]["content"]
    assert "고마워요" in check_prompt and "결제해 주세요" not in check_prompt
    assert screen.calls.count(("invoke", "결제")) == 1
