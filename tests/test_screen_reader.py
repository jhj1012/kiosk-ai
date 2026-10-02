"""Tests for turning raw UIA trees into snapshots and snapshot text."""

from assistant.screen.format import EMPTY_SCREEN, format_snapshot
from assistant.screen.model import Rect
from assistant.screen.reader import RawNode, clean_name
from tests.screen_fakes import button, check, edit, group, scrollbar, snapshot, text


def lines(*children: RawNode) -> list[str]:
    return format_snapshot(snapshot(*children)).splitlines()


def test_enabled_controls_are_numbered_in_order() -> None:
    assert lines(
        text("메뉴 선택"),
        button("처음으로"),
        button("결제하기", enabled=False),
        check("ICE", on=True),
        check("HOT"),
    ) == [
        'Text "메뉴 선택"',
        '[1] Button "처음으로"',
        'Button "결제하기" (disabled)',
        '[2] CheckBox "ICE" checked',
        '[3] CheckBox "HOT" unchecked',
    ]


def test_title_bar_and_offscreen_elements_are_dropped() -> None:
    title_bar = RawNode("TitleBar", "", children=[button("닫기"), button("최소화")])
    hidden = button("숨김")
    hidden.offscreen = True
    assert lines(title_bar, hidden, button("주문하기")) == ['[1] Button "주문하기"']


def test_unnamed_containers_are_flattened_and_named_ones_become_regions() -> None:
    assert lines(
        group("", button("A")),
        group("메뉴 목록", button("B"), group("", button("C"))),
        button("D"),
    ) == [
        '[1] Button "A"',
        "<메뉴 목록>",
        '  [2] Button "B"',
        '  [3] Button "C"',
        '[4] Button "D"',
    ]


def test_whole_window_region_is_unwrapped_and_region_chains_merge() -> None:
    page = group(
        "키오스크 화면",
        group("메뉴 목록 스크롤 영역", group("", group("메뉴 목록", button("아메리카노")))),
        button("담기"),
    )
    assert lines(page) == ["<메뉴 목록>", '  [1] Button "아메리카노"', '[2] Button "담기"']


def test_text_repeating_region_name_and_empty_regions_are_dropped() -> None:
    row_rect = Rect(10, 500, 590, 560)  # one row of a taller list: the list is not a wrapper
    row = group("라떼 2개 9000원", text("라떼 2개 9000원"), button("라떼 삭제"), rect=row_rect)
    cart = group("장바구니 목록", row, rect=Rect(0, 490, 600, 800))
    assert lines(cart, group("빈 목록"), text("합계")) == [
        "<장바구니 목록>",
        "  <라떼 2개 9000원>",
        '    [1] Button "라떼 삭제"',
        'Text "합계"',
    ]


def test_scrollbar_makes_its_region_scrollable_and_numbered() -> None:
    area = group("옵션 스크롤 영역", group("옵션 목록", check("A"), check("B")), scrollbar(0, 300))
    snap = snapshot(area, button("담기"))
    assert format_snapshot(snap).splitlines() == [
        "[1] <옵션 목록> (scrollable: more below)",
        '  [2] CheckBox "A" unchecked',
        '  [3] CheckBox "B" unchecked',
        '[4] Button "담기"',
    ]
    assert snap.scroll_refs == [1]
    assert snap.by_ref(1).scroll is not None


def test_scroll_hint_and_unusable_scrollbars() -> None:
    middle = snapshot(group("목록", button("A"), scrollbar(150, 300)))
    first_line = format_snapshot(middle).splitlines()[0]
    assert first_line == "[1] <목록> (scrollable: more above and below)"
    read_only = snapshot(group("목록", button("A"), scrollbar(0, 300, read_only=True)))
    no_range = snapshot(group("목록", button("A"), scrollbar(0, 0)))
    assert read_only.scroll_refs == no_range.scroll_refs == []


def test_children_scrolled_out_of_the_viewport_are_clipped() -> None:
    viewport = Rect(0, 100, 600, 500)
    inside = check("보임", rect=Rect(10, 120, 200, 200))
    partly = check("반쯤", rect=Rect(10, 450, 200, 550))
    below = check("아래", rect=Rect(10, 600, 200, 700))
    nested = check("아래 그룹", rect=Rect(10, 610, 200, 700))
    nested_below = group("", nested, rect=Rect(0, 600, 600, 720))
    content = group("", inside, partly, below, nested_below, rect=Rect(0, 100, 600, 1000))
    snap = snapshot(group("옵션 목록", group("", content, rect=viewport)))
    visible = {e.name: e.visible_rect for e in snap.elements}
    assert visible["보임"] == Rect(10, 120, 200, 200)
    assert visible["반쯤"] == Rect(10, 450, 200, 500)
    assert visible["아래"] is None
    assert visible["아래 그룹"] is None
    # Clipped elements stay in the snapshot: UIA patterns work on them without scrolling.
    assert snap.by_ref(4).name == "아래 그룹"


def test_edit_field_shows_its_value() -> None:
    assert lines(edit("전화번호", "010")) == ['[1] Edit "전화번호" value="010"']


def test_names_are_cleaned() -> None:
    assert clean_name('  아메리카노\n4,000원  "HOT" ') == "아메리카노 4,000원 'HOT'"


def test_snapshot_lookup_and_busy() -> None:
    snap = snapshot(button("A"), button("B", enabled=False), text("T"))
    a = snap.by_ref(1)
    assert a is not None and snap.find(a.runtime_id) == a
    assert snap.by_ref(2) is None
    assert not snap.busy
    assert snapshot(button("A", enabled=False), text("결제 중입니다")).busy


def test_empty_screen_text() -> None:
    assert format_snapshot(snapshot()) == EMPTY_SCREEN
