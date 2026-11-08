import random

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordChangeView, redirect_to_login
from django.contrib.staticfiles import finders
from django.db.models import Sum
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from . import rules
from .forms import BookingForm, ListingForm, PhoneLoginForm, ProfileForm, RegisterForm
from .models import Booking, Listing, incoming_bookings, profile_of
from .utils import safe_next, trip_dates

TABS = [("all", "Все"), ("car", "Легковые"), ("van", "Бусики")]
SORTS = [("rating", "По рейтингу"), ("cheap", "Сначала дешевле"), ("expensive", "Сначала дороже")]


def _phone_of(user):
    profile = getattr(user, "profile", None)
    return rules.format_phone(profile.phone) if profile and profile.phone else ""


# ---------- Каталог ----------

def catalog(request):
    date_from, date_to = trip_dates(request.GET)
    days = (date_to - date_from).days
    city = request.GET.get("city", "all")
    city = city if city in rules.CITIES else "all"
    kind = request.GET.get("type", "all")
    kind = kind if kind in ("car", "van") else "all"
    sort = request.GET.get("sort", "rating")
    sort = sort if sort in dict(SORTS) else "rating"

    qs = Listing.objects.active().available(date_from, date_to).select_related("owner")
    if city != "all":
        qs = qs.filter(city=city)
    if kind != "all":
        qs = qs.filter(kind=kind)
    items = list(qs)
    if sort == "cheap":
        items.sort(key=lambda item: item.price)
    elif sort == "expensive":
        items.sort(key=lambda item: -item.price)
    else:
        items.sort(key=lambda item: -(item.rating or 0))
    items.sort(key=lambda item: 0 if item.is_new else 1)  # новые объявления первыми
    for item in items:
        item.total_for_days = item.price * days

    base = {"city": city, "from": date_from.isoformat(), "to": date_to.isoformat(), "sort": sort}
    tabs = [
        {"value": value, "label": label, "url": "?" + urlencode({**base, "type": value}) + "#catalog"}
        for value, label in TABS
    ]
    hero = static("rentals/img/hero.jpg") if finders.find("rentals/img/hero.jpg") else ""
    return render(request, "rentals/catalog.html", {
        "listings": items,
        "found": len(items),
        "days": days,
        "date_from": date_from,
        "date_to": date_to,
        "today": timezone.localdate(),
        "city": city,
        "kind": kind,
        "sort": sort,
        "cities": rules.CITIES,
        "tabs": tabs,
        "sorts": SORTS,
        "trip_query": urlencode({"from": date_from.isoformat(), "to": date_to.isoformat()}),
        "catalog_empty": not Listing.objects.active().exists(),
        "seed_hint": settings.DEBUG,
        "hero_image": hero,
    })


def listing_detail(request, pk):
    listing = get_object_or_404(Listing.objects.select_related("owner"), pk=pk)
    user = request.user
    is_mine = user.is_authenticated and listing.owner_id == user.pk
    if not listing.is_active and not (is_mine or user.is_staff):
        raise Http404("Объявление снято с публикации")

    date_from, date_to = trip_dates(request.GET)
    form = None
    if user.is_authenticated and not is_mine and listing.is_active:
        if request.method == "POST":
            form = BookingForm(request.POST, request.FILES, listing=listing)
            if form.is_valid():
                booking = Booking(
                    listing=listing, renter=user,
                    date_from=form.cleaned_data["date_from"], date_to=form.cleaned_data["date_to"],
                )
                booking.fill_amounts()
                if form.cleaned_data.get("license_photo"):
                    booking.license_photo = form.cleaned_data["license_photo"]
                booking.save()
                messages.success(request, f"Заявка {booking.code} отправлена владельцу")
                return redirect(booking)
            # Если даты в форме верные, считаем по ним
            date_from = form.cleaned_data.get("date_from") or date_from
            date_to = form.cleaned_data.get("date_to") or date_to
            if date_to <= date_from:
                date_from, date_to = trip_dates({})
        else:
            form = BookingForm(listing=listing, initial={"date_from": date_from, "date_to": date_to})
    elif request.method == "POST":
        return redirect(listing)

    days = (date_to - date_from).days
    ask = (
        f"Расскажи про {listing.title} {listing.year or ''} ({listing.city}, {rules.money(listing.price)} сом / "
        f"{listing.unit}): для какой поездки подойдёт и сколько выйдет на 3 дня?"
    )
    return render(request, "rentals/listing_detail.html", {
        "listing": listing,
        "form": form,
        "is_mine": is_mine,
        "quote": listing.quote(days),
        "date_from": date_from,
        "date_to": date_to,
        "deposit": rules.DEPOSIT,
        "ask_text": ask,
        "login_url": reverse("login") + "?" + urlencode({"next": request.get_full_path()}),
    })


# ---------- Сдать машину ----------

def _listing_form_page(request, form, listing=None):
    comm_car = int(rules.COMMISSION["car"] * 100)
    comm_van = int(rules.COMMISSION["van"] * 100)
    # Пример заработка для калькулятора справа: цена из формы, 12 дней аренды в месяц
    kind, price = "car", 3000
    if form is not None:
        kind = form["kind"].value() if form["kind"].value() in ("car", "van") else "car"
        try:
            price = max(0, int(form["price"].value() or 0))
        except (TypeError, ValueError):
            price = 0
    return render(request, "rentals/listing_form.html", {
        "form": form,
        "listing": listing,
        "comm_car": comm_car,
        "comm_van": comm_van,
        "share_car": 100 - comm_car,
        "share_van": 100 - comm_van,
        "earn": rules.quote(price, kind, 12),
        "earn_price": price,
        "login_url": reverse("login") + "?" + urlencode({"next": reverse("listing_create")}),
        "register_url": reverse("register") + "?" + urlencode({"next": reverse("listing_create")}),
    })


def listing_create(request):
    if not request.user.is_authenticated:
        if request.method == "POST":
            return redirect_to_login(reverse("listing_create"))
        return _listing_form_page(request, None)
    profile = profile_of(request.user)
    form = ListingForm(request.POST or None, request.FILES or None, initial={"city": profile.city})
    if request.method == "POST" and form.is_valid():
        listing = form.save(commit=False)
        listing.owner = request.user
        listing.color = random.choice(rules.COLORS)
        listing.save()
        messages.success(request, "Объявление опубликовано в каталоге")
        return redirect(listing)
    return _listing_form_page(request, form)


@login_required
def listing_edit(request, pk):
    listing = get_object_or_404(Listing, pk=pk, owner=request.user)
    old_photo = listing.photo.name if listing.photo else ""
    form = ListingForm(request.POST or None, request.FILES or None, instance=listing)
    if request.method == "POST" and form.is_valid():
        listing = form.save()
        if old_photo and "photo" in form.changed_data and listing.photo.name != old_photo:
            listing.photo.storage.delete(old_photo)
        messages.success(request, "Объявление сохранено")
        return redirect(listing)
    return _listing_form_page(request, form, listing)


@login_required
@require_POST
def listing_toggle(request, pk):
    listing = get_object_or_404(Listing, pk=pk, owner=request.user)
    listing.is_active = not listing.is_active
    listing.save(update_fields=["is_active"])
    if listing.is_active:
        messages.success(request, "Объявление снова в каталоге")
    else:
        messages.success(request, "Объявление снято с публикации")
    return redirect(reverse("cabinet") + "#listings")


# ---------- Личный кабинет и брони ----------

@login_required
def cabinet(request):
    user = request.user
    incoming = list(incoming_bookings(user).select_related("listing__owner", "renter").order_by("-created_at"))
    trips = list(Booking.objects.filter(renter=user).select_related("listing__owner").order_by("-created_at"))
    mine = list(Listing.objects.filter(owner=user).order_by("-created_at"))
    earned = incoming_bookings(user).filter(status=Booking.OK).aggregate(total=Sum("owner_earn"))["total"] or 0
    return render(request, "rentals/cabinet.html", {
        "profile": profile_of(user),
        "incoming": incoming,
        "trips": trips,
        "mine": mine,
        "earned": earned,
        "new_count": sum(1 for b in incoming if b.status == Booking.NEW),
        "today": timezone.localdate(),
    })


@login_required
def booking_detail(request, pk):
    booking = get_object_or_404(
        Booking.objects.select_related("listing__owner__profile", "renter__profile"), pk=pk
    )
    user = request.user
    if not booking.can_view(user):
        raise Http404
    can_manage = booking.can_manage(user)
    is_renter = booking.renter_id == user.pk
    owner_phone = ""
    renter_phone = ""
    if booking.status == Booking.OK:
        # Телефоны открываются только после подтверждения. У демо-машин — телефон команды TANDA.
        owner_phone = _phone_of(booking.listing.owner)
        if not owner_phone and booking.listing.is_demo:
            owner_phone = settings.TANDA_CONTACT.get("phone", "")
        renter_phone = _phone_of(booking.renter)
    return render(request, "rentals/booking_detail.html", {
        "booking": booking,
        "listing": booking.listing,
        "can_manage": can_manage,
        "is_renter": is_renter,
        "can_cancel": is_renter and _can_cancel(booking),
        "owner_phone": owner_phone,
        "renter_phone": renter_phone,
    })


def _can_cancel(booking):
    if booking.status == Booking.NEW:
        return True
    return booking.status == Booking.OK and booking.date_from > timezone.localdate()


@login_required
@require_POST
def booking_action(request, pk, action):
    booking = get_object_or_404(Booking.objects.select_related("listing"), pk=pk)
    user = request.user
    if action in ("confirm", "decline"):
        if not booking.can_manage(user):
            raise Http404
        if booking.status != Booking.NEW:
            messages.info(request, "Эта заявка уже обработана.")
        elif action == "confirm":
            if booking.clashes().exists():
                messages.error(request, "На эти даты у машины уже есть подтверждённая бронь. Эту заявку можно отклонить.")
            else:
                booking.status = Booking.OK
                booking.decided_at = timezone.now()
                booking.save(update_fields=["status", "decided_at"])
                messages.success(request, f"Заявка {booking.code} подтверждена. Арендатор увидит это в кабинете.")
        else:
            booking.status = Booking.NO
            booking.decided_at = timezone.now()
            booking.save(update_fields=["status", "decided_at"])
            messages.success(request, f"Заявка {booking.code} отклонена")
    elif action == "cancel":
        if booking.renter_id != user.pk:
            raise Http404
        if _can_cancel(booking):
            booking.status = Booking.CANCELLED
            booking.save(update_fields=["status"])
            messages.success(request, f"Бронь {booking.code} отменена")
        else:
            messages.info(request, "Эту бронь уже нельзя отменить.")
    else:
        raise Http404
    return redirect(safe_next(request, request.POST.get("next")) or booking.get_absolute_url())


@login_required
def booking_license(request, pk):
    """Фото прав видят только арендатор, владелец машины и администратор."""
    booking = get_object_or_404(Booking.objects.select_related("listing"), pk=pk)
    user = request.user
    allowed = booking.renter_id == user.pk or booking.can_manage(user) or user.is_staff
    if not allowed or not booking.license_photo:
        raise Http404
    response = FileResponse(booking.license_photo.open("rb"), content_type="image/jpeg")
    response["Cache-Control"] = "private, no-store"
    return response


# ---------- Осмотр по фото ----------

def inspect_page(request):
    return render(request, "rentals/inspect.html")


# ---------- Аккаунт ----------

def register(request):
    if request.user.is_authenticated:
        return redirect("cabinet")
    next_url = safe_next(request, request.POST.get("next") or request.GET.get("next"))
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Аккаунт создан. Добро пожаловать в TANDA")
        return redirect(next_url or "cabinet")
    return render(request, "rentals/auth/register.html", {"form": form, "next": next_url})


class TandaLoginView(LoginView):
    template_name = "rentals/auth/login.html"
    authentication_form = PhoneLoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        name = form.get_user().first_name
        messages.success(self.request, f"Салам, {name}!" if name else "С возвращением в TANDA!")
        return response


class TandaPasswordChangeView(PasswordChangeView):
    template_name = "rentals/auth/password.html"
    success_url = reverse_lazy("cabinet")

    def form_valid(self, form):
        messages.success(self.request, "Пароль изменён")
        return super().form_valid(form)


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль сохранён")
        return redirect("cabinet")
    return render(request, "rentals/auth/profile.html", {"form": form})


@login_required
@require_POST
def account_delete(request):
    user = request.user
    logout(request)
    user.delete()
    messages.success(request, "Аккаунт удалён")
    return redirect("catalog")
