"""Tests for carrying out actions: idempotent select, batches, keypad typing, fallbacks."""

from __future__ import annotations

import pytest

from assistant.agent.confirm_gate import ConfirmationGate
from assistant.agent.decision import ActionRequest
from assistant.agent.executor import Executor, plan_keypad
from assistant.screen.reader import RawNode
from tests.agent_fakes import FakeScreen
from tests.screen_fakes import button, check, edit, snapshot, text, window


def run(screen: FakeScreen, *actions: ActionRequest, gate: ConfirmationGate | None = None):
    executor = Executor(
        screen,
        gate or ConfirmationGate(payment_pattern="^결제$"),
        settle=screen.read,
        pause=lambda s: None,
    )
    return executor.run(actions, screen.read())


def test_click_times_presses_repeatedly() -> None:
    screen = FakeScreen(window(text("수량 1개"), button("수량 증가")))
    result = run(screen, ActionRequest("click", ref=1, times=3))
    assert screen.calls == [("invoke", "수량 증가")] * 3
    assert result.lines == ['pressed Button "수량 증가" 3 times']
    assert not result.failed


def test_click_on_a_checkbox_selects_it_without_unchecking() -> None:
    screen = FakeScreen(window(check("ICE", on=True), check("Large")))
    result = run(screen, ActionRequest("click", ref=1), ActionRequest("click", ref=2))
    assert screen.calls == [("toggle", "Large")]
    assert result.lines == ['CheckBox "ICE" was already selected', 'selected CheckBox "Large"']


def test_unselect_turns_off_and_rejects_buttons() -> None:
    screen = FakeScreen(window(check("휘핑 추가", on=True), button("담기")))
    result = run(screen, ActionRequest("unselect", ref=1), ActionRequest("unselect", ref=2))
    assert screen.calls == [("toggle", "휘핑 추가")]
    assert result.failed
    assert result.lines[1] == 'ERROR: Button "담기" is not a choice that can be turned off.'


def test_unselect_in_single_choice_group_is_a_note_and_the_batch_continues() -> None:
    screen = FakeScreen(window(check("HOT", on=True), check("ICE")))
    real_toggle = screen.toggle
    # An exclusive group refuses to uncheck its selected choice.
    screen.toggle = lambda e: None if e.name == "HOT" else real_toggle(e)
    result = run(screen, ActionRequest("unselect", ref=1), ActionRequest("select", ref=2))
    assert not result.failed
    assert result.lines[0] == 'NOTE: CheckBox "HOT" stays on until another choice is selected'
    assert result.lines[1] == 'selected CheckBox "ICE"'


def test_batch_stops_when_the_screen_changes() -> None:
    menu = window(button("아메리카노"), button("라떼"))
    screen = FakeScreen(menu)
    screen.on_press["아메리카노"] = lambda: setattr(screen, "page", window(check("HOT")))
    result = run(screen, ActionRequest("click", ref=1), ActionRequest("click", ref=2))
    assert screen.calls == [("invoke", "아메리카노")]
    assert not result.failed  # normal: the model continues on the new screen
    assert result.lines[1].startswith("SKIPPED the remaining 1 action(s): the screen changed")
    assert result.snapshot.elements[0].name == "HOT"  # the model gets the new screen


def test_batch_stops_after_a_tab_switch_even_if_the_next_target_still_exists() -> None:
    # Planned: switch to the latte tab, then press a number guessed for a latte item. That
    # number belongs to the checkout button, which exists on both tabs: it must not be pressed.
    checkout = button("결제하기")
    coffee_tab, latte_tab = check("커피", on=True), check("라떼")
    screen = FakeScreen(window(coffee_tab, latte_tab, button("아메리카노"), checkout))
    latte_page = window(coffee_tab, latte_tab, button("카페라떼"), checkout)
    real_toggle = screen.toggle

    def switch_tab(element):  # noqa: ANN001, ANN202
        real_toggle(element)
        screen.page = latte_page

    screen.toggle = switch_tab
    result = run(screen, ActionRequest("select", ref=2), ActionRequest("click", ref=4))
    assert screen.calls == [("toggle", "라떼")]
    assert "the screen changed" in result.lines[1]


def test_toggling_options_does_not_count_as_a_screen_change() -> None:
    screen = FakeScreen(window(check("ICE"), button("수량 감소", enabled=False), button("담기")))
    result = run(screen, ActionRequest("select", ref=1), ActionRequest("click", ref=2))
    assert screen.calls == [("toggle", "ICE"), ("invoke", "담기")]
    assert not result.failed


def test_later_actions_find_their_element_again_after_a_change() -> None:
    screen = FakeScreen(window(check("ICE"), check("Large"), button("담기")))
    run(
        screen,
        ActionRequest("select", ref=1),
        ActionRequest("select", ref=2),
        ActionRequest("click", ref=3),
    )
    assert screen.calls == [("toggle", "ICE"), ("toggle", "Large"), ("invoke", "담기")]


def test_payment_button_blocked_by_gate() -> None:
    screen = FakeScreen(window(button("결제")))
    result = run(screen, ActionRequest("click", ref=1))
    assert screen.calls == [] and result.failed and result.lines[0].startswith("BLOCKED")


def test_mouse_is_only_a_fallback() -> None:
    plain = RawNode("Button", "아이콘", rect=button("x").rect, runtime_id=(9, 9))  # no patterns
    screen = FakeScreen(window(plain))
    run(screen, ActionRequest("click", ref=1))
    assert screen.calls == [("click", "아이콘")]


def keypad() -> RawNode:
    keys = [button(f"숫자 {d}") for d in "1234567890"]
    return window(text("휴대폰 번호"), *keys, button("한 글자 지우기"), button("적립하기"))


def test_plan_keypad_maps_characters_to_key_buttons() -> None:
    keys = plan_keypad("010-12", snapshot(*keypad().children))
    assert [k.name for k in keys] == ["숫자 0", "숫자 1", "숫자 0", "숫자 1", "숫자 2"]


def test_plan_keypad_rejects_missing_or_ambiguous_keys() -> None:
    with pytest.raises(ValueError, match="no on-screen key"):
        plan_keypad("12a", snapshot(*keypad().children))
    with pytest.raises(ValueError, match="more than one"):
        plan_keypad("1", snapshot(button("층 1"), button("방 1")))


def test_type_text_uses_keypad_or_edit_field() -> None:
    screen = FakeScreen(keypad())
    run(screen, ActionRequest("type_text", text="0101"))
    assert screen.calls == [("invoke", f"숫자 {d}") for d in "0101"]

    form = FakeScreen(window(edit("전화번호"), button("확인")))
    result = run(form, ActionRequest("type_text", text="01012345678"))
    assert form.calls == [("set_value", "01012345678")]
    assert result.snapshot.elements[0].value == "01012345678"


def test_wait_and_scroll() -> None:
    from tests.screen_fakes import group, scrollbar

    screen = FakeScreen(window(group("목록", button("A"), scrollbar())))
    result = run(screen, ActionRequest("wait", seconds=2), ActionRequest("scroll", ref=1))
    assert screen.calls == [("scroll", "down")]
    assert result.lines == ["waited 2 s", "scrolled <목록> down"]


def test_repeated_press_stops_quietly_when_the_target_disappears() -> None:
    # "삭제" removes its cart row: a second press finds nothing. That is success, not an error.
    row = button("라떼 삭제")
    screen = FakeScreen(window(row, button("결제하기")))
    screen.on_press["라떼 삭제"] = lambda: setattr(screen, "page", window(button("결제하기")))
    result = run(screen, ActionRequest("click", ref=1, times=2))
    assert screen.calls == [("invoke", "라떼 삭제")]
    assert not result.failed
    assert result.lines == [
        'pressed Button "라떼 삭제" 1 time(s); after that it was gone, so it was not pressed again'
    ]
