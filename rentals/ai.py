"""
ИИ-функции TANDA на Anthropic API: помощник по подбору машины,
подсказка цены для владельца и осмотр машины по двум фото.

Ключ и модель задаются в .env: ANTHROPIC_API_KEY и ANTHROPIC_MODEL.
"""
import json
import logging
import math
import re

from django.conf import settings
from django.utils import dateformat, timezone

from . import rules

log = logging.getLogger(__name__)

NO_KEY_MESSAGE = "ИИ не подключён: добавьте ANTHROPIC_API_KEY в файл .env и перезапустите сервер."


class AIError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def enabled():
    return bool(settings.ANTHROPIC_API_KEY)


_clients = {}


def get_client():
    if not enabled():
        raise AIError(NO_KEY_MESSAGE, 503)
    import anthropic

    key = settings.ANTHROPIC_API_KEY
    if key not in _clients:
        _clients[key] = anthropic.Anthropic(api_key=key, timeout=60.0, max_retries=2)
    return _clients[key]


def complete(messages, system=None, max_tokens=800):
    """Один запрос к Claude. Возвращает текст ответа или бросает AIError с понятным текстом."""
    import anthropic

    client = get_client()
    params = {"model": settings.ANTHROPIC_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        params["system"] = system
    try:
        response = client.messages.create(**params)
    except anthropic.AuthenticationError:
        raise AIError("Ключ ANTHROPIC_API_KEY не подошёл. Проверьте его в файле .env.", 503)
    except anthropic.PermissionDeniedError:
        raise AIError("У этого ключа нет доступа к модели. Проверьте ANTHROPIC_MODEL в файле .env.", 503)
    except anthropic.NotFoundError:
        raise AIError("Модель не найдена. Проверьте ANTHROPIC_MODEL в файле .env.", 503)
    except anthropic.RateLimitError:
        raise AIError("ИИ сейчас получает слишком много запросов. Подождите минуту и попробуйте снова.", 429)
    except anthropic.APIConnectionError:
        raise AIError("Нет связи с ИИ. Проверьте интернет и попробуйте ещё раз.", 502)
    except anthropic.APIStatusError as error:
        log.warning("Anthropic API error %s: %s", error.status_code, error)
        if error.status_code == 529:
            raise AIError("ИИ сейчас перегружен. Попробуйте через минуту.", 503)
        raise AIError("ИИ не ответил. Попробуйте ещё раз.", 502)
    text = "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text")
    if not text.strip():
        raise AIError("ИИ вернул пустой ответ. Попробуйте ещё раз.", 502)
    return text.strip()


def parse_json(text):
    """Достаёт JSON-объект из ответа модели, даже если вокруг него есть лишний текст."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise AIError("ИИ ответил не в том формате. Попробуйте ещё раз.", 502)
    try:
        return json.loads(cleaned[start:end + 1])
    except ValueError:
        raise AIError("ИИ ответил не в том формате. Попробуйте ещё раз.", 502)


def _day(d, with_year=False):
    return dateformat.format(d, "j E Y" if with_year else "j E")


# ---------- Помощник по подбору машины ----------

def clean_history(items, limit=12):
    """Приводит историю чата к виду, который принимает API: роли чередуются, первая и последняя — клиент."""
    if not isinstance(items, list):
        return []
    out = []
    for item in items[-limit:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()[:2000]
        if role not in ("user", "assistant") or not content:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    while out and out[-1]["role"] != "user":
        out.pop()
    return out


def assistant_system(listings, date_from, date_to):
    lines = []
    for item in listings:
        unit = "сутки, без водителя" if item.is_car else "день, с водителем"
        rating = f"рейтинг {item.rating}" if item.rating else "новое"
        lines.append(
            f"{item.pk} | {item.get_kind_display()} | {item.title} {item.year or ''} | {item.city} | "
            f"{item.seats_label} | {item.price} сом/{unit} | {rating}"
        )
    days = (date_to - date_from).days
    catalog = "\n".join(lines) or "(на эти даты свободных машин нет)"
    return (
        "Ты — помощник сайта TANDA.com: аренда легковых машин и бусиков у частных владельцев в Кыргызстане. "
        "Это прототип для хакатона.\n"
        "Правила TANDA:\n"
        "- Чтобы бронировать или сдавать машину, нужен аккаунт TANDA: регистрация по номеру телефона и паролю занимает минуту.\n"
        f"- Арендатор платит цену владельца плюс сервисный сбор {int(rules.FEE_RATE * 100)}%.\n"
        "- Легковые машины сдаются без водителя: нужны паспорт и водительские права, фото прав загружается при бронировании; "
        f"депозит {rules.DEPOSIT} сом возвращается после осмотра по фото при возврате.\n"
        "- Бусики сдаются только с водителем, цена указана за день вместе с водителем. Автобусов на TANDA нет.\n"
        "- У всех машин действующее ОСАГО. КАСКО на время аренды пока нет.\n"
        "- При выдаче и возврате машину фотографируют, ИИ сравнивает фото и находит новые повреждения.\n"
        "- Заявку подтверждает владелец в личном кабинете. После подтверждения стороны видят телефоны друг друга.\n"
        f"Сегодня {_day(timezone.localdate(), with_year=True)}. Даты в поиске клиента: "
        f"{_day(date_from)} — {_day(date_to)}, {days} {rules.plural(days, rules.DAYS)}.\n"
        "Каталог машин, свободных на эти даты (рекомендуй только из него, ничего не выдумывай):\n"
        f"{catalog}\n"
        "Как отвечать:\n"
        "- На языке клиента (русский, кыргызский, казахский или английский), просто и коротко: 2–5 предложений, "
        "без длинных списков и без таблиц.\n"
        "- Если клиент описывает поездку, подбери 1–3 варианта по городу, числу людей и бюджету, объясни выбор "
        f"и посчитай примерную сумму: цена × дни + {int(rules.FEE_RATE * 100)}% сбора.\n"
        "- Если подходящего нет, честно скажи об этом и предложи ближайший вариант.\n"
        "- Не обещай того, чего нет в правилах.\n"
        "- Если рекомендуешь варианты из каталога, добавь в самом конце отдельную строку: IDS: id1, id2"
    )


IDS_LINE = re.compile(r"\n?[ \t]*IDS?\s*:\s*([^\n]*)\s*$", re.IGNORECASE)


def split_ids(text, valid_ids):
    """Отделяет служебную строку «IDS: 3, 7» от ответа и оставляет только существующие объявления."""
    match = IDS_LINE.search(text or "")
    if not match:
        return (text or "").strip(), []
    ids = []
    for token in re.split(r"[\s,;]+", match.group(1)):
        token = token.strip().lstrip("#")
        if token.isdigit() and int(token) in valid_ids and int(token) not in ids:
            ids.append(int(token))
    return text[:match.start()].strip(), ids[:3]


def chat(history, listings, date_from, date_to):
    return complete(history, system=assistant_system(listings, date_from, date_to), max_tokens=700)


# ---------- Подсказка цены для владельца ----------

def suggest_price(title, kind, year, city, seats):
    kind_text = "Легковая, без водителя" if kind == "car" else "Бусик, с водителем"
    prompt = (
        "Ты помогаешь владельцу сдать транспорт на сайте TANDA.com в Кыргызстане.\n"
        f"Транспорт: {kind_text}. Модель: {title}. Год: {year or 'не указан'}. Город: {city}. Мест: {seats}.\n"
        "Ориентиры частных объявлений: эконом-седаны и хэтчбеки 2 000–2 500 сом в сутки, седаны бизнес-класса "
        "3 000–3 500, внедорожники и минивэны 4 000–8 000; бусики с водителем 8 000–12 000 сом в день. "
        "В регионах обычно на 10–15% дешевле, летом у Иссык-Куля дороже.\n"
        "Верни ТОЛЬКО JSON без пояснений: {\"price\": число в сомах, кратное 100, \"range\": [минимум, максимум], "
        "\"reason\": \"одно короткое предложение, почему такая цена\", \"description\": \"2–3 предложения для объявления "
        "от лица владельца, без выдуманных фактов о комплектации\"}"
    )
    data = parse_json(complete([{"role": "user", "content": prompt}], max_tokens=500))

    def hundreds(value):
        try:
            return max(0, int(math.floor(float(value) / 100.0 + 0.5)) * 100)
        except (TypeError, ValueError, OverflowError):
            return 0

    price = hundreds(data.get("price"))
    if price < 500:
        raise AIError("ИИ не смог подобрать цену. Попробуйте ещё раз.", 502)
    price_range = data.get("range")
    if isinstance(price_range, list) and len(price_range) == 2:
        low, high = sorted([hundreds(price_range[0]), hundreds(price_range[1])])
        price_range = [low, high] if high else None
    else:
        price_range = None
    return {
        "price": price,
        "range": price_range,
        "reason": str(data.get("reason") or "")[:300],
        "description": str(data.get("description") or "")[:600],
    }


# ---------- Осмотр по фото ----------

INSPECT_PROMPT = (
    "Ты — система осмотра автомобилей сервиса аренды TANDA.\n"
    "Изображение 1 — фото машины ПРИ ВЫДАЧЕ клиенту. Изображение 2 — фото той же машины ПРИ ВОЗВРАТЕ.\n"
    "Задача: найти повреждения, которые ВИДНЫ на изображении 2, но которых НЕТ на изображении 1: царапины, вмятины, "
    "сколы, трещины, разбитые фары или стёкла, оторванные детали, наклеенные или нарисованные следы.\n"
    "Не считай повреждениями разницу в освещении, бликах, отражениях, ракурсе, грязь, пыль и капли воды.\n"
    "Если на фото, скорее всего, разные машины, поставь same_car: false.\n"
    "Ответь ТОЛЬКО JSON без пояснений вокруг:\n"
    "{\"same_car\": true, \"new_damages\": [{\"type\": \"царапина|вмятина|скол|трещина|другое\", "
    "\"location\": \"где на машине, по-русски, коротко\", \"severity\": \"лёгкое|среднее|серьёзное\", "
    "\"description\": \"одно предложение по-русски\", \"box\": [x0, y0, x1, y1]}], "
    "\"summary\": \"1–2 предложения по-русски для арендатора и владельца\"}\n"
    "box — прямоугольник вокруг повреждения на ИЗОБРАЖЕНИИ 2, в долях от 0 до 1 (x слева направо, y сверху вниз), "
    "с небольшим запасом по краям.\n"
    "Если новых повреждений нет, верни new_damages: []."
)


def _clean_box(box):
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in box)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def inspect(image_before, image_after):
    """image_before и image_after — блоки изображений из images.as_claude_image()."""
    content = [
        {"type": "text", "text": "Изображение 1 (при выдаче):"},
        image_before,
        {"type": "text", "text": "Изображение 2 (при возврате):"},
        image_after,
        {"type": "text", "text": INSPECT_PROMPT},
    ]
    data = parse_json(complete([{"role": "user", "content": content}], max_tokens=1500))
    damages = []
    for item in data.get("new_damages") or []:
        if not isinstance(item, dict):
            continue
        damages.append({
            "type": str(item.get("type") or "повреждение")[:40],
            "location": str(item.get("location") or "")[:80],
            "severity": str(item.get("severity") or "")[:20],
            "description": str(item.get("description") or "")[:300],
            "box": _clean_box(item.get("box")),
        })
    return {
        "same_car": data.get("same_car") is not False,
        "new_damages": damages[:10],
        "summary": str(data.get("summary") or "")[:500],
    }
