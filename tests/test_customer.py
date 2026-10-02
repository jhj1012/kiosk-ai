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
    screen = FakeScreen(window(text("결제할 금액 9000원"), button("결제")))
    llm = FakeLlm(
        act(click("결제"), message="총 9000원입니다."),
        {"answer": "yes"},
        reply("결제가 완료되었어요.", kind="tell"),
        act(click("결제"), message="총 9000원입니다."),
        {"answer": "no"},
        reply("무엇을 도와드릴까요?"),
    )
    agent, _ = start_on(screen, llm)
    agent.handle("결제해 주세요")
    agent.handle("고마워요")
    # The second payment check only sees messages after the payment.
    check_prompt = llm.requests[4][0][0]["content"]
    assert "고마워요" in check_prompt and "결제해 주세요" not in check_prompt
    assert screen.calls.count(("invoke", "결제")) == 1


def done_screen() -> FakeScreen:
    """A finished order still on screen; "처음으로" goes back to the idle screen."""
    screen = FakeScreen(window(text("어서 오세요"), button("주문하기")))
    screen.page = window(text("주문번호 1번"), button("처음으로"))
    screen.on_press["처음으로"] = lambda: setattr(
        screen, "page", window(text("어서 오세요"), button("주문하기"))
    )
    return screen


def start_on(screen: FakeScreen, llm: FakeLlm) -> tuple[Agent, RecordingOutput]:
    """Learn the idle screen first, then show `screen.page` (a later state)."""
    later = screen.page
    screen.page = window(text("어서 오세요"), button("주문하기"))
    agent, output = make_agent(screen, llm, Clock())
    screen.page = later
    return agent, output


def test_speaker_confirms_being_a_new_customer() -> None:
    screen = done_screen()
    llm = FakeLlm(
        reply("결제가 완료되었어요. 주문번호는 1번이에요.", kind="tell"),
        reply("새로 주문하시는 손님이신가요?", kind="new_customer"),
        {"answer": "yes"},  # "네" to the new-customer question
        reply("매장에서 드시나요, 포장하시나요?"),
    )
    agent, output = start_on(screen, llm)
    agent.handle("결제해 주세요")
    agent.handle("안녕하세요, 아이스티 하나 주세요")  # a different person, seconds later
    agent.handle("네")
    assert ("invoke", "처음으로") in screen.calls
    contents = [m["content"] for m in llm.requests[3][0]]
    customers = [c for c in contents if c.startswith("Customer:")]
    # The new conversation starts with the new customer's request, not "네" or the old order.
    assert customers == ['Customer: "안녕하세요, 아이스티 하나 주세요"']
    assert any(
        c.startswith("NOTE: The customer confirmed they are a new customer") for c in contents
    )
    assert output.messages[-1] == ("ask", ("매장에서 드시나요, 포장하시나요?", []))


def test_speaker_says_they_are_the_same_customer() -> None:
    screen = done_screen()
    llm = FakeLlm(
        reply("새로 주문하시는 손님이신가요?", kind="new_customer"),
        {"answer": "no"},
        reply("네, 주문번호 1번은 카운터에서 받으시면 돼요.", kind="tell"),
    )
    agent, _ = start_on(screen, llm)
    agent.handle("하나 더 물어볼게요")
    agent.handle("아니요, 아까 주문한 사람이에요")
    assert ("invoke", "처음으로") not in screen.calls
    customers = [m["content"] for m in llm.requests[2][0] if m["content"].startswith("Customer:")]
    assert len(customers) == 2  # the conversation continues


def test_new_customer_on_the_idle_screen_needs_no_button() -> None:
    screen = done_screen()
    screen.page = window(text("어서 오세요"), button("주문하기"))  # already back at the start
    llm = FakeLlm(
        reply("새로 주문하시는 손님이신가요?", kind="new_customer"),
        {"answer": "yes"},
        reply("무엇을 드릴까요?"),
    )
    agent, _ = start_on(screen, llm)
    agent.handle("주문할게요")
    agent.handle("네")
    assert screen.calls == []


def test_after_a_finished_order_nothing_is_pressed_before_asking() -> None:
    """Live bug: "여보세요?" after a paid order started a new order with the old choices."""
    idle = window(text("어서 오세요"), button("주문하기"))
    screen = FakeScreen(window(text("결제할 금액 4500원"), button("결제")))
    screen.on_press["결제"] = lambda: setattr(screen, "page", idle)  # done, back to the start
    llm = FakeLlm(
        act(click("결제"), message="총 4500원입니다."),
        {"answer": "yes"},  # payment check
        reply("주문이 완료되었어요.", kind="tell"),
        act(click("주문하기")),  # "여보세요?": the model wants to start an order
        reply("새로 주문하시는 손님이신가요?", kind="new_customer"),
    )
    agent, output = start_on(screen, llm)
    agent.handle("결제해 주세요")
    agent.handle("여보세요?")
    assert ("invoke", "주문하기") not in screen.calls
    notes = [m["content"] for m in llm.requests[4][0]]
    assert any(n.startswith("BLOCKED: the order is already paid") for n in notes)
    assert output.messages[-1] == ("ask", ("새로 주문하시는 손님이신가요?", []))


def test_same_customer_may_order_again_after_saying_so() -> None:
    idle = window(text("어서 오세요"), button("주문하기"))
    screen = FakeScreen(window(text("결제할 금액 4500원"), button("결제")))
    screen.on_press["결제"] = lambda: setattr(screen, "page", idle)
    llm = FakeLlm(
        act(click("결제"), message="총 4500원입니다."),
        {"answer": "yes"},
        reply("주문이 완료되었어요.", kind="tell"),
        reply("새로 주문하시는 손님이신가요?", kind="new_customer"),
        {"answer": "no"},  # "아니요, 저 하나 더 살게요"
        act(click("주문하기")),
        reply("매장에서 드시나요, 포장하시나요?"),
    )
    agent, _ = start_on(screen, llm)
    agent.handle("결제해 주세요")
    agent.handle("하나 더 주문할게요")
    agent.handle("아니요, 저 하나 더 살게요")
    assert ("invoke", "주문하기") in screen.calls


def test_start_clears_a_leftover_order_and_learns_the_real_start_screen() -> None:
    """Started while the kiosk was mid-order: the menu must not become the idle screen."""
    start = window(text("어서 오세요"), button("주문하기"))
    screen = FakeScreen(window(button("아메리카노"), button("처음으로"), text("장바구니 1개")))
    screen.on_press["처음으로"] = lambda: setattr(screen, "page", start)
    agent = Agent(screen, FakeLlm(), RecordingOutput(), agent_config(), FAST_SCREEN)
    agent.start()
    assert screen.calls == [("invoke", "처음으로")]
    assert agent.customers.idle_controls == frozenset({"Button:주문하기"})


def test_decisions_are_remembered_across_turns() -> None:
    screen = FakeScreen(window(text("결제수단"), button("카드")))
    llm = FakeLlm(
        {**reply("카드로 결제할까요?"), "customer_said": ["포장"]},
        {**reply("결제할게요.", kind="tell"), "customer_said": ["포장", "결제수단 카드"]},
        reply("더 필요하신 게 있나요?"),
    )
    agent, _ = start_on(screen, llm)
    agent.handle("포장이요")
    agent.handle("네")  # "네" to the card suggestion: decided
    agent.handle("감사합니다")
    contents = [m["content"] for m in llm.requests[2][0]]
    assert "THE CUSTOMER ALREADY DECIDED: 포장; 결제수단 카드" in contents
    agent.reset()
    assert agent.conversation.customer_said == ()


def test_notes_not_from_this_conversation_are_dropped() -> None:
    """Live bug: the model copied the prompt's burger example into its notes."""
    screen = FakeScreen(window(text("메뉴"), button("아메리카노")))
    copied = {"customer_said": ["치즈버거 세트 2개", "음료 사이다", "포장"]}
    llm = FakeLlm({**reply("어떤 메뉴로 드릴까요?"), **copied})
    agent, _ = start_on(screen, llm)
    agent.handle("포장이요")
    assert agent.conversation.customer_said == ("포장",)
