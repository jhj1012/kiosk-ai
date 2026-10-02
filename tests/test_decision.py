"""Tests for parsing the model's answers and for the per-screen JSON schema."""

from __future__ import annotations

import json

import pytest

from assistant.agent.decision import DecisionError, clean_message, parse_decision
from assistant.agent.history import Conversation
from assistant.llm.schema import decision_schema, reply_schema
from tests.screen_fakes import button, check, edit, group, scrollbar, snapshot, text

SCREEN = snapshot(
    text("수량 1개"),
    group("옵션", check("HOT", on=True), check("ICE"), scrollbar()),
    button("수량 증가"),
    button("담기"),
)  # refs: [1] <옵션> (scrollable), [2] HOT, [3] ICE, [4] 수량 증가, [5] 담기


def parse(data: object):
    return parse_decision(json.dumps(data, ensure_ascii=False), SCREEN)


def test_parse_act() -> None:
    decision = parse(
        {
            "thought": "ice, then add",
            "next": "act",
            "actions": [
                {"do": "select", "target": "ICE"},
                {"do": "click", "target": "수량 증가", "times": 99},
                {"do": "scroll", "target": "옵션", "direction": "up"},
                {"do": "wait", "seconds": 0},
                {"do": "type_text", "text": " 0101 "},
            ],
        }
    )
    assert decision.reply is None
    assert [(a.do, a.ref) for a in decision.actions] == [
        ("select", 3),
        ("click", 4),
        ("scroll", 1),
        ("wait", None),
        ("type_text", None),
    ]
    assert decision.actions[1].times == 20  # clamped
    assert decision.actions[2].direction == "up"
    assert decision.actions[3].seconds == 1
    assert decision.actions[4].text == "0101"
    assert json.loads(decision.to_json())["next"] == "act"


def test_parse_reply_cleans_message_and_choices() -> None:
    decision = parse(
        {
            "thought": "",
            "next": "reply",
            "kind": "ask",
            "message": "[2] HOT, [3] ICE?",
            "choices": ["HOT", "ICE", "ICE", "없음", 7],
        }
    )
    assert decision.reply is not None
    assert decision.reply.message == "HOT, ICE?"
    assert decision.reply.choices == (2, 3)


def test_reply_kind_is_guessed_when_missing() -> None:
    assert parse({"next": "reply", "message": "뭘 드릴까요?"}).reply.kind == "ask"
    assert parse({"next": "reply", "message": "담았어요."}).reply.kind == "tell"


@pytest.mark.parametrize(
    ("data", "error"),
    [
        ({"next": "act", "actions": []}, "at least one action"),
        ({"next": "act", "actions": [{"do": "fly", "target": "HOT"}]}, "Unknown action"),
        (
            {"next": "act", "actions": [{"do": "click", "target": "피자"}]},
            '"피자" is not a control',
        ),
        ({"next": "act", "actions": [{"do": "click", "target": "옵션"}]}, "is a group"),
        ({"next": "act", "actions": [{"do": "scroll", "target": "담기"}]}, "cannot be scrolled"),
        ({"next": "act", "actions": [{"do": "type_text", "text": " "}]}, "needs a"),
        ({"next": "reply", "message": ""}, "needs a"),
        ({"next": "maybe"}, '"next" must be'),
        (["not", "an", "object"], "JSON object"),
    ],
)
def test_invalid_answers(data: object, error: str) -> None:
    with pytest.raises(DecisionError, match=error.replace("[", r"\[").replace("]", r"\]")):
        parse(data)


def test_invalid_json() -> None:
    with pytest.raises(DecisionError, match="not valid JSON"):
        parse_decision('{"thought": "abc', SCREEN)


def test_clean_message() -> None:
    assert clean_message("[12] 아메리카노를 [3]골랐어요") == "아메리카노를 골랐어요"


def test_decision_schema_limits_numbers_to_the_screen() -> None:
    schema = decision_schema(SCREEN)
    act, reply = schema["anyOf"]
    variants = act["properties"]["actions"]["items"]["anyOf"]
    by_do = {json.dumps(v["properties"]["do"]): v["properties"] for v in variants}
    controls = ["HOT", "ICE", "수량 증가", "담기"]
    assert by_do['{"const": "click"}']["target"]["enum"] == controls
    assert by_do['{"const": "scroll"}']["target"]["enum"] == ["옵션"]
    assert "target" not in by_do['{"const": "type_text"}']  # no edit field: keypad typing
    assert reply["properties"]["choices"]["items"]["enum"] == controls
    assert act["required"] == ["screen", "todo", "need_to_ask", "next", "actions"]


def test_schema_variants_follow_the_screen() -> None:
    form = snapshot(edit("이름"), button("확인"))
    variants = decision_schema(form)["anyOf"][0]["properties"]["actions"]["items"]["anyOf"]
    type_text = next(v for v in variants if v["properties"]["do"] == {"const": "type_text"})
    assert type_text["properties"]["target"]["enum"] == ["이름"]
    assert not any(v["properties"]["do"] == {"const": "scroll"} for v in variants)

    empty = snapshot(text("결제 중입니다"))
    assert reply_schema(empty)["properties"]["choices"] == {"type": "array", "maxItems": 0}
    only_wait = decision_schema(empty)["anyOf"][0]["properties"]["actions"]["items"]["anyOf"]
    assert {json.dumps(v["properties"]["do"]) for v in only_wait} == {
        '{"const": "type_text"}',
        '{"const": "wait"}',
    }


def test_conversation_trims_whole_old_turns() -> None:
    conversation = Conversation("system", max_messages=4)
    for turn in range(3):
        conversation.add_customer(f"turn {turn}")
        conversation.add_model("{}")
        conversation.add_note("RESULT")
    conversation.add_customer("turn 3")
    contents = [m["content"] for m in conversation.messages]
    assert contents == ['Customer: "turn 2"', "{}", "RESULT", 'Customer: "turn 3"']
    built = conversation.build('[1] Button "A"')
    assert built[0] == {"role": "system", "content": "system"}
    assert built[-1]["content"].startswith("CURRENT SCREEN:")


def test_open_required_choices_only_allow_selecting() -> None:
    def answer(*actions: dict) -> object:
        return {"next": "act", "need_to_ask": ["옵션"], "actions": list(actions)}

    # [5] 담기 would decide the open choice with the screen's default
    with pytest.raises(DecisionError, match="need to ask"):
        parse(
            answer({"do": "select", "target": "ICE"}, {"do": "click", "target": "담기", "times": 1})
        )
    assert len(parse(answer({"do": "select", "target": "ICE"})).actions) == 1
    assert (
        len(parse(answer({"do": "click", "target": "ICE", "times": 1})).actions) == 1
    )  # a check box
    click_add = [{"do": "click", "target": "담기", "times": 1}]
    no_missing = {"next": "act", "need_to_ask": [], "actions": click_add}
    assert parse(no_missing).actions[0].ref == 5


def test_missing_choices_not_on_the_screen_do_not_block() -> None:
    # The model sometimes lists a choice of a later screen (size, while on the menu).
    menu = snapshot(text("메뉴"), button("카페라떼 4500원"))
    answer = {
        "next": "act",
        "need_to_ask": ["사이즈"],
        "actions": [{"do": "click", "target": "카페라떼 4500원"}],
    }
    assert parse_decision(json.dumps(answer, ensure_ascii=False), menu).actions[0].ref == 1
    options = snapshot(text("사이즈 선택"), check("Regular", on=True), button("담기"))
    with pytest.raises(DecisionError):
        parse_decision(
            json.dumps({**answer, "actions": [{"do": "click", "target": "담기"}]}), options
        )


def test_choice_selected_in_the_same_answer_counts_as_answered() -> None:
    options = snapshot(
        text("사이즈 선택"), check("사이즈 Regular", on=True), check("사이즈 Large"), button("담기")
    )
    answer = {
        "next": "act",
        "need_to_ask": ["사이즈"],
        "actions": [{"do": "select", "target": "사이즈 Large"}, {"do": "click", "target": "담기"}],
    }
    decision = parse_decision(json.dumps(answer, ensure_ascii=False), options)
    assert [a.ref for a in decision.actions] == [2, 3]
