from django.conf import settings

from .models import Booking, incoming_bookings


def tanda(request):
    """Данные, нужные на каждой странице: счётчик новых заявок, контакты, включён ли ИИ."""
    user = getattr(request, "user", None)
    new_count = 0
    if user is not None and user.is_authenticated:
        new_count = incoming_bookings(user).filter(status=Booking.NEW).count()
    return {
        "nav_new_count": new_count,
        "ai_enabled": bool(settings.ANTHROPIC_API_KEY),
        "contact": settings.TANDA_CONTACT,
    }
