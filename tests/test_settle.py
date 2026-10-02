"""Tests for waiting until the screen settles after an action."""

from assistant.screen.model import Snapshot
from assistant.screen.reader import RawNode
from assistant.screen.settle import wait_until_settled
from tests.screen_fakes import button, group, snapshot, text


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def time(self) -> float:
        return self.now


def run(reads: list[Snapshot], timeout_s: float = 1.0) -> tuple[Snapshot, int]:
    clock = FakeClock()
    calls = 0

    def read() -> Snapshot:
        nonlocal calls
        calls += 1
        return reads[min(calls, len(reads)) - 1]

    result = wait_until_settled(
        read, timeout_s=timeout_s, interval_s=0.1, sleep=clock.sleep, clock=clock.time
    )
    return result, calls


def test_returns_after_two_equal_reads() -> None:
    a = snapshot(button("A"))
    result, calls = run([a, a, a])
    assert result is a and calls == 2


def test_waits_while_screen_changes() -> None:
    a, b = snapshot(button("A")), snapshot(button("B"))
    result, calls = run([a, b, b])
    assert result is b and calls == 3


def test_waits_while_busy() -> None:
    busy = snapshot(button("결제", enabled=False), text("결제 중입니다"))
    done = snapshot(button("건너뛰기"))
    result, calls = run([busy, busy, busy, busy, done, done])
    assert result is done and calls == 6


def test_gives_up_after_timeout() -> None:
    busy = snapshot(text("잠시만 기다려 주세요"))
    result, calls = run([busy], timeout_s=0.5)
    assert result is busy and 5 <= calls <= 7


def test_list_rows_do_not_make_a_busy_screen_usable() -> None:
    row = RawNode("ListItem", "1번 쿠키 1개", rect=button("x").rect, runtime_id=(5, 5))
    paying = snapshot(group("주문 내역", row), button("결제", enabled=False), text("결제 중"))
    assert paying.busy
