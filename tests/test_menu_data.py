"""Tests for loading menu.json."""

import copy
import json

import pytest

from kiosk_app.menu_data import DEFAULT_MENU_PATH, load_menu, parse_menu


@pytest.fixture
def raw_menu() -> dict:
    return json.loads(DEFAULT_MENU_PATH.read_text(encoding="utf-8"))


def test_bundled_menu_loads() -> None:
    menu = load_menu()
    assert 8 <= len(menu.items) <= 12
    for category in menu.categories:
        assert menu.items_in(category.id), f"empty category {category.name}"


def test_default_choices_are_valid_for_every_item() -> None:
    for item in load_menu().items:
        item.validate_choices(item.default_choices())


def test_unknown_category_rejected(raw_menu: dict) -> None:
    bad = copy.deepcopy(raw_menu)
    bad["items"][0]["category"] = "nope"
    with pytest.raises(ValueError, match="unknown category"):
        parse_menu(bad)


def test_unknown_option_rejected(raw_menu: dict) -> None:
    bad = copy.deepcopy(raw_menu)
    bad["items"][0]["options"] = ["nope"]
    with pytest.raises(ValueError, match="unknown options"):
        parse_menu(bad)


def test_duplicate_item_rejected(raw_menu: dict) -> None:
    bad = copy.deepcopy(raw_menu)
    bad["items"].append(bad["items"][0])
    with pytest.raises(ValueError, match="duplicate"):
        parse_menu(bad)
