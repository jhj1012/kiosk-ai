"""Tests for the Qt-free order/cart logic."""

import pytest

from kiosk_app.order import (
    MAX_QUANTITY,
    Discount,
    MenuItem,
    OptionChoice,
    OptionGroup,
    Order,
    OrderNumbers,
    format_phone,
    is_valid_phone,
    won,
)

HOT = OptionChoice("temperature", "hot", "HOT")
ICE = OptionChoice("temperature", "ice", "ICE")
REGULAR = OptionChoice("size", "regular", "Regular")
LARGE = OptionChoice("size", "large", "Large", 500)
WHIP = OptionChoice("topping", "whipped_cream", "휘핑 추가", 500)

TEMPERATURE = OptionGroup("temperature", "온도", False, (HOT, ICE))
SIZE = OptionGroup("size", "사이즈", False, (REGULAR, LARGE))
TOPPING = OptionGroup("topping", "토핑", True, (WHIP,))

AMERICANO = MenuItem("americano", "아메리카노", "coffee", 4000, (TEMPERATURE, SIZE, TOPPING))
COOKIE = MenuItem("cookie", "초코 쿠키", "dessert", 2500)


@pytest.fixture
def order() -> Order:
    return Order()


def test_new_order_is_empty(order: Order) -> None:
    assert order.is_empty
    assert order.total_quantity == 0
    assert order.total == 0


def test_add_item(order: Order) -> None:
    order.add(AMERICANO, (ICE, REGULAR), 2)
    assert len(order.lines) == 1
    assert order.total_quantity == 2
    assert order.total == 8000


def test_add_identical_item_merges_line(order: Order) -> None:
    order.add(AMERICANO, (ICE, REGULAR))
    order.add(AMERICANO, (REGULAR, ICE))  # same options, different order
    assert len(order.lines) == 1
    assert order.lines[0].quantity == 2


def test_add_different_options_makes_new_line(order: Order) -> None:
    order.add(AMERICANO, (ICE, REGULAR))
    order.add(AMERICANO, (HOT, REGULAR))
    assert len(order.lines) == 2


def test_options_affect_price(order: Order) -> None:
    line = order.add(AMERICANO, (ICE, LARGE, WHIP))
    assert line.unit_price == 4000 + 500 + 500
    order.change_quantity(0, 1)
    assert order.total == 2 * 5000


def test_description_lists_options(order: Order) -> None:
    line = order.add(AMERICANO, (LARGE, ICE))
    assert line.description == "아메리카노 (ICE, Large)"
    assert order.add(COOKIE, ()).description == "초코 쿠키"


@pytest.mark.parametrize(
    "choices",
    [
        (ICE,),  # missing size
        (ICE, HOT, REGULAR),  # two temperatures
        (ICE, REGULAR, WHIP, WHIP),  # duplicate
        (ICE, REGULAR, OptionChoice("syrup", "vanilla", "바닐라 시럽", 500)),  # not offered
    ],
)
def test_invalid_options_rejected(order: Order, choices: tuple[OptionChoice, ...]) -> None:
    with pytest.raises(ValueError):
        order.add(AMERICANO, choices)


def test_quantity_must_be_positive(order: Order) -> None:
    with pytest.raises(ValueError):
        order.add(COOKIE, (), 0)


def test_change_quantity(order: Order) -> None:
    order.add(COOKIE, ())
    order.change_quantity(0, 2)
    assert order.lines[0].quantity == 3
    order.set_quantity(0, 1)
    assert order.total == 2500


def test_quantity_capped(order: Order) -> None:
    order.add(COOKIE, (), MAX_QUANTITY)
    order.add(COOKIE, ())
    order.change_quantity(0, 5)
    assert order.lines[0].quantity == MAX_QUANTITY


def test_quantity_zero_removes_line(order: Order) -> None:
    order.add(COOKIE, ())
    order.change_quantity(0, -1)
    assert order.is_empty


def test_remove(order: Order) -> None:
    order.add(COOKIE, ())
    order.add(AMERICANO, (HOT, REGULAR))
    order.remove(0)
    assert [line.item for line in order.lines] == [AMERICANO]
    assert order.total == 4000


def test_clear(order: Order) -> None:
    order.add(COOKIE, ())
    order.set_discount(Discount("coupon", "쿠폰", 1000), True)
    order.clear()
    assert order.is_empty
    assert order.discounts == []
    assert order.total == 0


def test_total_with_multiple_lines(order: Order) -> None:
    order.add(AMERICANO, (ICE, LARGE), 2)  # 2 x 4500
    order.add(COOKIE, (), 3)  # 3 x 2500
    assert order.total_quantity == 5
    assert order.subtotal == 9000 + 7500
    assert order.total == 16500


def test_discounts(order: Order) -> None:
    coupon = Discount("coupon", "쿠폰", 2000)
    telecom = Discount("telecom", "통신사 할인", 1000)
    order.add(AMERICANO, (ICE, REGULAR))
    order.set_discount(coupon, True)
    order.set_discount(coupon, True)  # no double apply
    order.set_discount(telecom, True)
    assert order.discount_total == 3000
    assert order.total == 1000
    order.set_discount(telecom, False)
    assert order.total == 2000


def test_discount_never_exceeds_subtotal(order: Order) -> None:
    order.add(COOKIE, ())
    order.set_discount(Discount("big", "큰 할인", 10000), True)
    assert order.total == 0


def test_reset(order: Order) -> None:
    order.add(COOKIE, ())
    order.dine_in = True
    order.payment_method = "카드"
    order.reset()
    assert order.is_empty
    assert order.dine_in is None
    assert order.payment_method is None


def test_order_numbers_increase() -> None:
    numbers = OrderNumbers(start=101)
    assert [numbers.next(), numbers.next()] == [101, 102]


@pytest.mark.parametrize(
    ("digits", "valid"),
    [("01012345678", True), ("0111234567", True), ("0101234", False), ("02012345678", False)],
)
def test_is_valid_phone(digits: str, valid: bool) -> None:
    assert is_valid_phone(digits) is valid


def test_format_phone_and_won() -> None:
    assert format_phone("010") == "010"
    assert format_phone("0101234") == "010-1234"
    assert format_phone("01012345678") == "010-1234-5678"
    assert won(16500) == "16,500원"
