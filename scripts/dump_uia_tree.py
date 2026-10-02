"""Dump the UI Automation tree of the running test kiosk (developer helper).

Start the kiosk first (`uv run python -m kiosk_app`), then run:

    uv run python scripts/dump_uia_tree.py            # compact list of controls
    uv run python scripts/dump_uia_tree.py --full     # pywinauto print_control_identifiers()
    uv run python scripts/dump_uia_tree.py --check    # exit 1 if a control has no name

The compact list is roughly what the assistant's screen reader will see.
"""

from __future__ import annotations

import argparse
import sys

from pywinauto import Application

WINDOW_TITLE = "Test Kiosk"
# Control types the assistant interacts with or reads; each must have a name.
NAMED_TYPES = {"Button", "Text", "List", "ListItem", "CheckBox", "RadioButton", "Edit"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="print_control_identifiers()")
    parser.add_argument("--check", action="store_true", help="fail on unnamed controls")
    parser.add_argument("--title", default=WINDOW_TITLE)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    window = (
        Application(backend="uia").connect(title=args.title, timeout=10).window(title=args.title)
    )
    if args.full:
        window.print_control_identifiers()
        return 0

    unnamed = 0
    names: dict[tuple[str, str], int] = {}
    for control in window.descendants():
        info = control.element_info
        if not control.is_visible():
            continue
        kind, name = info.control_type, info.name
        state = "" if control.is_enabled() else "  [disabled]"
        print(f"{kind:<10} {name!r:<45} id={info.automation_id}{state}")
        if kind in NAMED_TYPES:
            if not name.strip():
                unnamed += 1
            names[(kind, name)] = names.get((kind, name), 0) + 1
    duplicates = {k: n for k, n in names.items() if n > 1 and k[0] == "Button"}
    print(f"\nunnamed controls: {unnamed}, duplicate button names: {duplicates or 'none'}")
    return 1 if args.check and (unnamed or duplicates) else 0


if __name__ == "__main__":
    sys.exit(main())
