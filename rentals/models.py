import secrets
from datetime import timedelta

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from . import rules


def private_storage():
    """Хранилище для фото прав: папка private_media, без публичной ссылки."""
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def listing_upload_to(instance, filename):
    return f"listings/{timezone.now():%Y/%m}/{secrets.token_hex(8)}.jpg"


def license_upload_to(instance, filename):
    return f"licenses/{timezone.now():%Y/%m}/{secrets.token_hex(12)}.jpg"


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile", verbose_name="Пользователь"
    )
    phone = models.CharField("Телефон", max_length=12, blank=True, help_text="Только цифры, например 996502142280")
    city = models.CharField("Город", max_length=40, choices=rules.CITY_CHOICES, default="Бишкек")
    role = models.CharField("Я хочу", max_length=10, choices=rules.ROLE_CHOICES, default="both")
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "профиль"
        verbose_name_plural = "профили"

    def __str__(self):
        return self.name

    @property
    def name(self):
        return self.user.get_full_name() or self.user.get_username()

    @property
    def phone_display(self):
        return rules.format_phone(self.phone)


def profile_of(user):
    """Профиль пользователя; создаётся сам, если его ещё нет (например, у суперпользователя)."""
    if not user or not user.is_authenticated:
        return None
    try:
        return user.profile
    except Profile.DoesNotExist:
        return Profile.objects.create(user=user, phone=rules.normalize_phone(user.get_username()))


class ListingQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def available(self, date_from, date_to):
        """Без машин, у которых на эти даты уже есть подтверждённая бронь."""
        busy = Booking.objects.filter(
            status=Booking.OK, date_from__lt=date_to, date_to__gt=date_from
        ).values("listing_id")
        return self.exclude(pk__in=busy)


class Listing(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="listings", verbose_name="Владелец"
    )
    kind = models.CharField("Транспорт", max_length=3, choices=rules.KIND_CHOICES, default="car")
    title = models.CharField("Марка и модель", max_length=60)
    year = models.PositiveSmallIntegerField(
        "Год выпуска", null=True, blank=True, validators=[MinValueValidator(1990), MaxValueValidator(2100)]
    )
    city = models.CharField("Город", max_length=40, choices=rules.CITY_CHOICES, default="Бишкек")
    seats = models.PositiveSmallIntegerField("Мест", default=5, validators=[MinValueValidator(1), MaxValueValidator(20)])
    gear = models.CharField("Коробка", max_length=12, choices=rules.GEAR_CHOICES, blank=True)
    fuel = models.CharField("Топливо", max_length=12, choices=rules.FUEL_CHOICES, blank=True)
    price = models.PositiveIntegerField(
        "Цена, сом",
        validators=[MinValueValidator(500), MaxValueValidator(100000)],
        help_text="За сутки у легковой машины, за день с водителем у бусика",
    )
    description = models.TextField("Описание", max_length=600, blank=True)
    photo = models.ImageField("Фото", upload_to=listing_upload_to, blank=True)
    color = models.CharField("Цвет рисунка", max_length=7, default="#E7E5E0", help_text="Пока нет фото, машина рисуется этим цветом")
    rating = models.DecimalField(
        "Рейтинг", max_digits=2, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    trips = models.PositiveIntegerField("Поездок", default=0)
    has_osago = models.BooleanField("Есть ОСАГО", default=False)
    is_demo = models.BooleanField("Демо-объявление", default=False)
    is_active = models.BooleanField("Опубликовано", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    objects = ListingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "объявление"
        verbose_name_plural = "объявления"

    def __str__(self):
        return f"{self.title} · {self.get_kind_display()} · {self.city}"

    def get_absolute_url(self):
        return reverse("listing_detail", args=[self.pk])

    @property
    def is_car(self):
        return self.kind == "car"

    @property
    def unit(self):
        return "сутки" if self.is_car else "день"

    @property
    def commission_percent(self):
        return int(rules.COMMISSION[self.kind] * 100)

    @property
    def is_new(self):
        return not self.is_demo and self.created_at and timezone.now() - self.created_at < timedelta(days=7)

    @property
    def owner_name(self):
        return self.owner.get_full_name() or "Владелец"

    @property
    def owner_display(self):
        return f"{self.owner_name} (демо)" if self.is_demo else self.owner_name

    @property
    def seats_label(self):
        return f"{self.seats} {rules.plural(self.seats, rules.SEATS)}"

    @property
    def meta_line(self):
        if self.is_car:
            parts = [self.year, self.gear, self.fuel, self.seats_label]
        else:
            parts = [self.year, self.seats_label, "с водителем"]
        return " · ".join(str(p) for p in parts if p)

    @property
    def trips_label(self):
        return f"{self.trips} {rules.plural(self.trips, rules.TRIPS)}"

    def quote(self, days):
        return rules.quote(self.price, self.kind, days)

    def is_free(self, date_from, date_to):
        return not self.bookings.filter(
            status=Booking.OK, date_from__lt=date_to, date_to__gt=date_from
        ).exists()


class Booking(models.Model):
    NEW, OK, NO, CANCELLED = "new", "ok", "no", "cancelled"
    STATUS_CHOICES = [
        (NEW, "Ждёт владельца"),
        (OK, "Подтверждена"),
        (NO, "Отклонена"),
        (CANCELLED, "Отменена"),
    ]
    CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    code = models.CharField("Номер", max_length=8, unique=True, editable=False)
    listing = models.ForeignKey(Listing, on_delete=models.CASCADE, related_name="bookings", verbose_name="Объявление")
    renter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="trips", verbose_name="Арендатор"
    )
    date_from = models.DateField("С")
    date_to = models.DateField("По")
    days = models.PositiveSmallIntegerField("Дней")
    price = models.PositiveIntegerField("Цена за сутки или день")
    subtotal = models.PositiveIntegerField("Аренда")
    fee = models.PositiveIntegerField("Сервисный сбор")
    total = models.PositiveIntegerField("Итого к оплате")
    owner_earn = models.PositiveIntegerField("Владельцу")
    tanda_income = models.PositiveIntegerField("Доход TANDA")
    status = models.CharField("Статус", max_length=10, choices=STATUS_CHOICES, default=NEW)
    license_photo = models.ImageField("Фото прав", upload_to=license_upload_to, storage=private_storage, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    decided_at = models.DateTimeField("Решение владельца", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "бронь"
        verbose_name_plural = "брони"

    def __str__(self):
        return f"{self.code} · {self.listing.title}"

    def get_absolute_url(self):
        return reverse("booking_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if self.code:
            return super().save(*args, **kwargs)
        for _ in range(10):
            self.code = "T-" + "".join(secrets.choice(self.CODE_ALPHABET) for _ in range(5))
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                if Booking.objects.filter(code=self.code).exists():
                    continue
                raise
        raise IntegrityError("Не удалось подобрать номер брони")

    def fill_amounts(self):
        """Считает суммы по цене объявления на момент брони."""
        self.days = max(1, (self.date_to - self.date_from).days)
        q = self.listing.quote(self.days)
        self.price = self.listing.price
        self.subtotal = q["subtotal"]
        self.fee = q["fee"]
        self.total = q["total"]
        self.owner_earn = q["owner_earn"]
        self.tanda_income = q["tanda_income"]

    @property
    def days_label(self):
        return f"{self.days} {rules.plural(self.days, rules.DAYS)}"

    @property
    def deposit(self):
        return rules.DEPOSIT if self.listing.is_car else 0

    def can_manage(self, user):
        """Подтверждать и отклонять может владелец машины, а заявки на демо-машины — администратор."""
        if not user or not user.is_authenticated:
            return False
        return self.listing.owner_id == user.pk or (user.is_staff and self.listing.is_demo)

    def can_view(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.renter_id == user.pk or self.can_manage(user) or user.is_staff

    def clashes(self):
        """Подтверждённые брони этой машины, которые пересекаются по датам."""
        return Booking.objects.filter(
            listing=self.listing, status=Booking.OK, date_from__lt=self.date_to, date_to__gt=self.date_from
        ).exclude(pk=self.pk)


def incoming_bookings(user):
    """Заявки на машины пользователя. Администратору приходят и заявки на демо-машины."""
    if not user or not user.is_authenticated:
        return Booking.objects.none()
    q = models.Q(listing__owner=user)
    if user.is_staff:
        q |= models.Q(listing__is_demo=True)
    return Booking.objects.filter(q)


@receiver(post_delete, sender=Listing)
def _delete_listing_photo(sender, instance, **kwargs):
    """Удаляем файл фото вместе с объявлением."""
    if instance.photo:
        instance.photo.delete(save=False)


@receiver(post_delete, sender=Booking)
def _delete_license_photo(sender, instance, **kwargs):
    """Фото прав не храним дольше брони."""
    if instance.license_photo:
        instance.license_photo.delete(save=False)
