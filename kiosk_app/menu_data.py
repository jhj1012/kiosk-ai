"""Load the menu from JSON into the plain dataclasses in `order.py`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kiosk_app.order import Category, Discount, Menu, MenuItem, OptionChoice, OptionGroup

DEFAULT_MENU_PATH = Path(__file__).parent / "data" / "menu.json"


def load_menu(path: Path = DEFAULT_MENU_PATH) -> Menu:
    """Read and validate a menu file."""
    with path.open(encoding="utf-8") as f:
        return parse_menu(json.load(f))


def parse_menu(data: dict[str, Any]) -> Menu:
    """Build a Menu from already-decoded JSON. Raises ValueError on inconsistent data."""
    categories = tuple(Category(c["id"], c["name"]) for c in data["categories"])
    category_ids = {c.id for c in categories}

    groups: dict[str, OptionGroup] = {}
    for g in data.get("option_groups", []):
        choices = tuple(
            OptionChoice(g["id"], c["id"], c["name"], int(c.get("price", 0))) for c in g["choices"]
        )
        if not choices:
            raise ValueError(f"option group {g['id']!r} has no choices")
        groups[g["id"]] = OptionGroup(g["id"], g["name"], bool(g.get("multi", False)), choices)

    items: list[MenuItem] = []
    for i in data["items"]:
        if i["category"] not in category_ids:
            raise ValueError(f"item {i['id']!r} has unknown category {i['category']!r}")
        unknown = [o for o in i.get("options", []) if o not in groups]
        if unknown:
            raise ValueError(f"item {i['id']!r} has unknown options {unknown}")
        items.append(
            MenuItem(
                id=i["id"],
                name=i["name"],
                category=i["category"],
                price=int(i["price"]),
                option_groups=tuple(groups[o] for o in i.get("options", [])),
                emoji=i.get("emoji", ""),
            )
        )

    for kind, ids in (("item", [i.id for i in items]), ("item name", [i.name for i in items])):
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate {kind} in menu")

    discounts = tuple(
        Discount(d["id"], d["name"], int(d["amount"])) for d in data.get("discounts", [])
    )
    return Menu(categories, tuple(items), discounts)
