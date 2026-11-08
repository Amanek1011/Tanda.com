"""
Правила и расчёты TANDA в одном месте: комиссии, сбор, депозит, города.
Чтобы поменять комиссию или сбор, достаточно исправить числа здесь.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

COMMISSION = {"car": Decimal("0.20"), "van": Decimal("0.15")}  # доля TANDA с аренды
FEE_RATE = Decimal("0.05")  # сервисный сбор с арендатора
DEPOSIT = 5000  # депозит за легковую машину, сом

CITIES = ["Бишкек", "Ош", "Каракол", "Чолпон-Ата", "Нарын", "Джалал-Абад"]
CITY_CHOICES = [(c, c) for c in CITIES]

KIND_CHOICES = [("car", "Легковая"), ("van", "Бусик")]
GEAR_CHOICES = [("автомат", "автомат"), ("механика", "механика"), ("вариатор", "вариатор")]
FUEL_CHOICES = [
    ("бензин", "бензин"),
    ("газ/бензин", "газ/бензин"),
    ("гибрид", "гибрид"),
    ("дизель", "дизель"),
    ("электро", "электро"),
]
ROLE_CHOICES = [("renter", "Арендую"), ("owner", "Сдаю машину"), ("both", "Арендую и сдаю")]

# Цвета для рисунка машины, пока у объявления нет фото
COLORS = ["#E7E5E0", "#C9CCD1", "#2F5D8C", "#C23B3B", "#F28C28", "#6B7480", "#D8D2C4"]

DAYS = ("день", "дня", "дней")
SEATS = ("место", "места", "мест")
TRIPS = ("поездка", "поездки", "поездок")


def plural(n, forms):
    """plural(3, DAYS) -> 'дня'"""
    n = abs(int(n or 0))
    a, b = n % 100, n % 10
    if 10 < a < 20:
        return forms[2]
    if 1 < b < 5:
        return forms[1]
    if b == 1:
        return forms[0]
    return forms[2]


def money(value):
    """12000 -> '12 000' (с неразрывным пробелом)."""
    try:
        return f"{int(round(float(value))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _round(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quote(price, kind, days):
    """Расчёт аренды: сколько платит арендатор, сколько получает владелец и TANDA."""
    days = max(1, int(days))
    subtotal = int(price) * days
    rate = COMMISSION.get(kind, COMMISSION["car"])
    fee = _round(subtotal * FEE_RATE)
    commission = _round(subtotal * rate)
    return {
        "days": days,
        "subtotal": subtotal,
        "fee": fee,
        "total": subtotal + fee,
        "owner_earn": subtotal - commission,
        "commission": commission,
        "tanda_income": commission + fee,
        "commission_percent": int(rate * 100),
        "fee_percent": int(FEE_RATE * 100),
        "deposit": DEPOSIT if kind == "car" else 0,
    }


def normalize_phone(raw):
    """'+996 (502) 14-22-80' -> '996502142280'. Пустая строка, если номер не похож на кыргызский."""
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 10 and digits.startswith("0"):
        digits = "996" + digits[1:]
    elif len(digits) == 9:
        digits = "996" + digits
    if len(digits) == 12 and digits.startswith("996"):
        return digits
    return ""


def format_phone(digits):
    """'996502142280' -> '+996 502 142 280'"""
    d = re.sub(r"\D", "", str(digits or ""))
    if len(d) == 12 and d.startswith("996"):
        return f"+996 {d[3:6]} {d[6:9]} {d[9:]}"
    return str(digits or "")
