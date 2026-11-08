from datetime import date, timedelta

from django.core.cache import cache
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

MAX_TRIP_DAYS = 60


def _parse_day(value, default):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return default


def trip_dates(params):
    """Даты поездки из параметров ?from=2026-11-09&to=2026-11-12. По умолчанию: с завтра на 3 дня."""
    today = timezone.localdate()
    start = _parse_day(params.get("from"), today + timedelta(days=1))
    if start < today:
        start = today
    end = _parse_day(params.get("to"), start + timedelta(days=3))
    if end <= start:
        end = start + timedelta(days=1)
    if (end - start).days > MAX_TRIP_DAYS:
        end = start + timedelta(days=MAX_TRIP_DAYS)
    return start, end


def safe_next(request, url):
    """Возвращает адрес для перехода, только если он ведёт на наш же сайт."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return ""


def rate_ok(request, bucket, limit, window=600):
    """Простое ограничение частоты запросов к ИИ: не больше limit за window секунд."""
    user = getattr(request, "user", None)
    who = f"u{user.pk}" if user is not None and user.is_authenticated else "ip" + request.META.get("REMOTE_ADDR", "?")
    key = f"tanda-rate:{bucket}:{who}"
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        count = 1
    return count <= limit
