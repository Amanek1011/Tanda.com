"""JSON-адреса для ИИ: помощник, подсказка цены, осмотр по фото. Вызываются из static/rentals/js/tanda.js."""
import json

from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from . import ai, rules
from .images import BadImage, as_claude_image
from .models import Listing
from .utils import rate_ok, trip_dates


def _error(message, status):
    return JsonResponse({"error": message}, status=status)


def _body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _int(value, default, low, high):
    try:
        return min(high, max(low, int(value)))
    except (TypeError, ValueError):
        return default


@require_POST
def assistant(request):
    if not ai.enabled():
        return _error(ai.NO_KEY_MESSAGE, 503)
    if not rate_ok(request, "chat", limit=30):
        return _error("Слишком много сообщений подряд. Подождите пару минут.", 429)
    data = _body(request)
    if data is None:
        return _error("Неверный запрос.", 400)
    history = ai.clean_history(data.get("messages"))
    if not history:
        return _error("Напишите сообщение.", 400)

    date_from, date_to = trip_dates(data)
    listings = list(Listing.objects.active().available(date_from, date_to).select_related("owner"))
    try:
        text = ai.chat(history, listings, date_from, date_to)
    except ai.AIError as error:
        return _error(str(error), error.status)

    reply, ids = ai.split_ids(text, {item.pk for item in listings})
    by_id = {item.pk: item for item in listings}
    cards = ""
    if ids:
        cards = render_to_string("rentals/_recs.html", {
            "items": [by_id[i] for i in ids],
            "trip_from": date_from.isoformat(),
            "trip_to": date_to.isoformat(),
        }, request=request)
    return JsonResponse({"reply": reply or "Готово.", "ids": ids, "cards": cards})


@require_POST
def suggest_price(request):
    if not ai.enabled():
        return _error(ai.NO_KEY_MESSAGE, 503)
    if not rate_ok(request, "price", limit=15):
        return _error("Слишком много запросов подряд. Подождите пару минут.", 429)
    data = _body(request)
    if data is None:
        return _error("Неверный запрос.", 400)
    title = " ".join(str(data.get("title") or "").split())[:60]
    if not title:
        return _error("Сначала впишите марку и модель.", 400)
    kind = "van" if data.get("kind") == "van" else "car"
    city = data.get("city") if data.get("city") in rules.CITIES else "Бишкек"
    year = _int(data.get("year"), None, 1990, 2100)
    seats = _int(data.get("seats"), 5, 1, 20)
    try:
        return JsonResponse(ai.suggest_price(title, kind, year, city, seats))
    except ai.AIError as error:
        return _error(str(error), error.status)


@require_POST
def inspect(request):
    if not ai.enabled():
        return _error(ai.NO_KEY_MESSAGE, 503)
    if not rate_ok(request, "inspect", limit=10):
        return _error("Слишком много проверок подряд. Подождите пару минут.", 429)
    before, after = request.FILES.get("before"), request.FILES.get("after")
    if not before or not after:
        return _error("Загрузите оба фото: при выдаче и при возврате.", 400)
    try:
        blocks = [as_claude_image(before), as_claude_image(after)]
    except BadImage as error:
        return _error(str(error), 400)
    try:
        return JsonResponse(ai.inspect(*blocks))
    except ai.AIError as error:
        return _error(str(error), error.status)
