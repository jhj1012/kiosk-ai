"""Order and cart logic. Plain Python with no Qt imports, so it can be unit tested."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

MAX_QUANTITY = 20
NONE_CHOICE_ID = "none"


@dataclass(frozen=True)
class OptionChoice:
    """One selectable value inside an option group, e.g. "Large" (+500원)."""

    group_id: str
    id: str
    name: str
    price: int = 0

    @property
    def is_none(self) -> bool:
        """True for "no change" choices such as "기본" or "없음"."""
        return self.id == NONE_CHOICE_ID


@dataclass(frozen=True)
class OptionGroup:
    """A set of choices. Single-select groups need exactly one choice; multi groups zero or more."""

    id: str
    name: str
    multi: bool
    choices: tuple[OptionChoice, ...]

    @property
    def default(self) -> OptionChoice | None:
        """The pre-selected choice (first one) for single-select groups."""
        return None if self.multi else self.choices[0]


@dataclass(frozen=True)
class Category:
    id: str
    name: str


@dataclass(frozen=True)
class MenuItem:
    id: str
    name: str
    category: str
    price: int
    option_groups: tuple[OptionGroup, ...] = ()
    emoji: str = ""

    def default_choices(self) -> tuple[OptionChoice, ...]:
        """Choices selected when the option dialog opens."""
        return tuple(g.default for g in self.option_groups if g.default is not None)

    def validate_choices(self, choices: tuple[OptionChoice, ...]) -> None:
        """Raise ValueError if `choices` is not a valid selection for this item."""
        groups = {g.id: g for g in self.option_groups}
        for choice in choices:
            group = groups.get(choice.group_id)
            if group is None or choice not in group.choices:
                raise ValueError(f"{self.name}: invalid option {choice.name!r}")
        if len(set(choices)) != len(choices):
            raise ValueError(f"{self.name}: duplicate option")
        for group in self.option_groups:
            count = sum(1 for c in choices if c.group_id == group.id)
            if not group.multi and count != 1:
                raise ValueError(f"{self.name}: choose exactly one {group.name}")


@dataclass(frozen=True)
class Discount:
    id: str
    name: str
    amount: int


@dataclass(frozen=True)
class Menu:
    """All data loaded from menu.json."""

    categories: tuple[Category, ...]
    items: tuple[MenuItem, ...]
    discounts: tuple[Discount, ...] = ()

    def items_in(self, category_id: str) -> list[MenuItem]:
        return [item for item in self.items if item.category == category_id]


def sort_choices(item: MenuItem, choices: tuple[OptionChoice, ...]) -> tuple[OptionChoice, ...]:
    """Order choices as their groups appear on the item, so equal selections compare equal."""
    group_index = {g.id: i for i, g in enumerate(item.option_groups)}
    choice_index = {c: i for g in item.option_groups for i, c in enumerate(g.choices)}
    return tuple(sorted(choices, key=lambda c: (group_index[c.group_id], choice_index[c])))


def unit_price(item: MenuItem, choices: tuple[OptionChoice, ...]) -> int:
    """Price of one item with the given options."""
    return item.price + sum(c.price for c in choices)


@dataclass
class CartLine:
    item: MenuItem
    choices: tuple[OptionChoice, ...]
    quantity: int

    @property
    def unit_price(self) -> int:
        return unit_price(self.item, self.choices)

    @property
    def total(self) -> int:
        return self.unit_price * self.quantity

    @property
    def option_text(self) -> str:
        """Short option summary, e.g. "ICE, Large, 샷 추가"."""
        return ", ".join(c.name for c in self.choices if not c.is_none)

    @property
    def description(self) -> str:
        """Item name with options, e.g. "아메리카노 (ICE, Large)"."""
        options = self.option_text
        return f"{self.item.name} ({options})" if options else self.item.name


@dataclass
class Order:
    """The customer's current order: cart lines, dine-in choice, discounts and payment method."""

    lines: list[CartLine] = field(default_factory=list)
    dine_in: bool | None = None
    discounts: list[Discount] = field(default_factory=list)
    payment_method: str | None = None

    def add(self, item: MenuItem, choices: tuple[OptionChoice, ...], quantity: int = 1) -> CartLine:
        """Add an item. An identical item+options line is merged by increasing its quantity."""
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        item.validate_choices(choices)
        choices = sort_choices(item, choices)
        for line in self.lines:
            if line.item == item and line.choices == choices:
                line.quantity = min(MAX_QUANTITY, line.quantity + quantity)
                return line
        line = CartLine(item, choices, min(MAX_QUANTITY, quantity))
        self.lines.append(line)
        return line

    def set_quantity(self, index: int, quantity: int) -> None:
        """Set a line's quantity. Zero or less removes the line."""
        if quantity <= 0:
            self.remove(index)
        else:
            self.lines[index].quantity = min(MAX_QUANTITY, quantity)

    def change_quantity(self, index: int, delta: int) -> None:
        self.set_quantity(index, self.lines[index].quantity + delta)

    def remove(self, index: int) -> None:
        del self.lines[index]

    def clear(self) -> None:
        """Empty the cart (and drop discounts, which only make sense with items)."""
        self.lines.clear()
        self.discounts.clear()

    def reset(self) -> None:
        """Start a brand new order."""
        self.clear()
        self.dine_in = None
        self.payment_method = None

    def set_discount(self, discount: Discount, enabled: bool) -> None:
        if enabled and discount not in self.discounts:
            self.discounts.append(discount)
        elif not enabled and discount in self.discounts:
            self.discounts.remove(discount)

    @property
    def is_empty(self) -> bool:
        return not self.lines

    @property
    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.lines)

    @property
    def subtotal(self) -> int:
        """Sum of all lines before discounts."""
        return sum(line.total for line in self.lines)

    @property
    def discount_total(self) -> int:
        """Discount actually applied (never more than the subtotal)."""
        return min(self.subtotal, sum(d.amount for d in self.discounts))

    @property
    def total(self) -> int:
        """Amount to pay."""
        return self.subtotal - self.discount_total


class OrderNumbers:
    """Hands out increasing order numbers."""

    def __init__(self, start: int = 1) -> None:
        self._counter = itertools.count(start)

    def next(self) -> int:
        return next(self._counter)


_PHONE_RE = re.compile(r"01[016789]\d{7,8}")


def is_valid_phone(digits: str) -> bool:
    """True for a Korean mobile number written as digits only, e.g. "01012345678"."""
    return _PHONE_RE.fullmatch(digits) is not None


def format_phone(digits: str) -> str:
    """Format digits as 010-1234-5678 while typing."""
    if len(digits) <= 3:
        return digits
    if len(digits) <= 7:
        return f"{digits[:3]}-{digits[3:]}"
    return f"{digits[:3]}-{digits[3:-4]}-{digits[-4:]}"


def won(amount: int) -> str:
    """Format a price, e.g. 4500 -> "4,500원"."""
    return f"{amount:,}원"
