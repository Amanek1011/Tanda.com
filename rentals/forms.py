from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from . import rules
from .images import BadImage, shrink
from .models import Listing, Profile

User = get_user_model()


class TelInput(forms.TextInput):
    input_type = "tel"


class DayInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


def split_name(full):
    parts = " ".join(str(full or "").split()).split(" ", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


class PhoneField(forms.CharField):
    """Принимает номер в любом виде и возвращает только цифры: 996XXXXXXXXX."""

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Телефон")
        kwargs.setdefault("max_length", 30)
        kwargs.setdefault(
            "widget",
            TelInput(attrs={"placeholder": "+996 555 123 456", "autocomplete": "tel", "inputmode": "tel"}),
        )
        super().__init__(**kwargs)

    def clean(self, value):
        value = super().clean(value)
        digits = rules.normalize_phone(value)
        if not digits:
            raise ValidationError("Введите номер в формате +996 555 123 456.")
        return digits


ROLE_FORM_CHOICES = [("renter", "Арендовать"), ("owner", "Сдавать свою машину"), ("both", "И то, и другое")]


class RegisterForm(forms.Form):
    name = forms.CharField(
        label="Имя и фамилия", max_length=60,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": "Например, Айбек Асанов"}),
    )
    phone = PhoneField()
    city = forms.ChoiceField(label="Город", choices=rules.CITY_CHOICES, initial="Бишкек")
    role = forms.ChoiceField(label="Я хочу", choices=ROLE_FORM_CHOICES, initial="both", widget=forms.RadioSelect)
    password1 = forms.CharField(
        label="Пароль", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Не короче 8 символов и не только цифры.",
    )
    password2 = forms.CharField(
        label="Пароль ещё раз", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    agree = forms.BooleanField(
        label="Согласен с правилами TANDA и обработкой моих данных",
        error_messages={"required": "Отметьте согласие с правилами TANDA."},
    )

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if len(name) < 2:
            raise ValidationError("Введите имя и фамилию.")
        return name

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if User.objects.filter(username=phone).exists():
            raise ValidationError("Этот номер уже зарегистрирован. Войдите с паролем.")
        return phone

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Пароли не совпадают.")
        elif p1:
            first, last = split_name(cleaned.get("name", ""))
            probe = User(username=cleaned.get("phone") or "", first_name=first, last_name=last)
            try:
                password_validation.validate_password(p1, probe)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned

    def save(self):
        data = self.cleaned_data
        first, last = split_name(data["name"])
        user = User.objects.create_user(
            username=data["phone"], password=data["password1"], first_name=first, last_name=last
        )
        Profile.objects.create(user=user, phone=data["phone"], city=data["city"], role=data["role"])
        return user


class PhoneLoginForm(AuthenticationForm):
    """Вход по телефону и паролю. Администратор может войти и по своему логину."""

    username = forms.CharField(
        label="Телефон", max_length=150,
        widget=TelInput(attrs={"autofocus": True, "autocomplete": "username", "placeholder": "+996 555 123 456"}),
    )
    password = forms.CharField(
        label="Пароль", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Неверный телефон или пароль.",
    }

    def clean_username(self):
        raw = self.cleaned_data.get("username", "")
        return rules.normalize_phone(raw) or raw.strip()


class ProfileForm(forms.Form):
    name = forms.CharField(label="Имя и фамилия", max_length=60, widget=forms.TextInput(attrs={"autocomplete": "name"}))
    phone = PhoneField()
    city = forms.ChoiceField(label="Город", choices=rules.CITY_CHOICES)
    role = forms.ChoiceField(label="Я хочу", choices=ROLE_FORM_CHOICES, widget=forms.RadioSelect)

    def __init__(self, *args, user, **kwargs):
        self.user = user
        self.profile = Profile.objects.get_or_create(user=user)[0]
        kwargs.setdefault("initial", {
            "name": user.get_full_name(),
            "phone": rules.format_phone(self.profile.phone),
            "city": self.profile.city,
            "role": self.profile.role,
        })
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if len(name) < 2:
            raise ValidationError("Введите имя и фамилию.")
        return name

    def clean_phone(self):
        phone = self.cleaned_data["phone"]
        if User.objects.filter(username=phone).exclude(pk=self.user.pk).exists():
            raise ValidationError("Этот номер уже занят другим аккаунтом.")
        return phone

    def save(self):
        data = self.cleaned_data
        user, profile = self.user, self.profile
        user.first_name, user.last_name = split_name(data["name"])
        # Обычные аккаунты входят по телефону, поэтому логин меняется вместе с номером
        if rules.normalize_phone(user.username):
            user.username = data["phone"]
        user.save()
        profile.phone, profile.city, profile.role = data["phone"], data["city"], data["role"]
        profile.save()
        return user


class ListingForm(forms.ModelForm):
    has_osago = forms.BooleanField(
        label="У машины есть действующее ОСАГО",
        error_messages={"required": "TANDA принимает только машины с действующим ОСАГО. Отметьте пункт, если полис есть."},
    )

    class Meta:
        model = Listing
        fields = ["kind", "city", "title", "year", "seats", "gear", "fuel", "price", "description", "photo", "has_osago"]
        labels = {"price": "Цена, сом в сутки"}
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Например, Toyota Camry 70", "maxlength": 60}),
            "year": forms.NumberInput(attrs={"min": 1990}),
            "seats": forms.NumberInput(attrs={"min": 1, "max": 20}),
            "price": forms.NumberInput(attrs={"min": 500, "step": 100}),
            "description": forms.Textarea(attrs={"placeholder": "Состояние, комплектация, условия", "maxlength": 600, "rows": 4}),
            "photo": forms.FileInput(attrs={"accept": "image/*", "class": "sr"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.this_year = timezone.localdate().year
        self.fields["kind"].choices = [("car", "Легковая, без водителя"), ("van", "Бусик, с водителем")]
        self.fields["year"].widget.attrs["max"] = self.this_year + 1
        self.fields["gear"].choices = rules.GEAR_CHOICES
        self.fields["fuel"].choices = rules.FUEL_CHOICES
        # По этим меткам скрипт страницы пересчитывает заработок владельца
        self.fields["kind"].widget.attrs["data-earn-kind"] = ""
        self.fields["price"].widget.attrs["data-earn-price"] = ""
        if not self.instance.pk:
            self.fields["year"].initial = 2018
            self.fields["seats"].initial = 5
            self.fields["price"].initial = 2500
            self.fields["gear"].initial = "автомат"
            self.fields["fuel"].initial = "бензин"

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())

    def clean_year(self):
        year = self.cleaned_data.get("year")
        if year and year > self.this_year + 1:
            raise ValidationError(f"Год выпуска не может быть позже {self.this_year + 1}.")
        return year

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if isinstance(photo, UploadedFile):
            try:
                return shrink(photo, max_side=1600)
            except BadImage as error:
                raise ValidationError(str(error))
        return photo

    def clean(self):
        cleaned = super().clean()
        kind, seats = cleaned.get("kind"), cleaned.get("seats")
        if kind == "car":
            if seats and seats > 9:
                self.add_error("seats", "У легковой машины не больше 9 мест. Если мест больше, выберите «Бусик».")
            cleaned["gear"] = cleaned.get("gear") or "автомат"
            cleaned["fuel"] = cleaned.get("fuel") or "бензин"
        elif kind == "van":
            if seats and not 8 <= seats <= 20:
                self.add_error("seats", "У бусика от 8 до 20 мест.")
            cleaned["gear"] = ""
            cleaned["fuel"] = ""
        return cleaned


class BookingForm(forms.Form):
    date_from = forms.DateField(label="С", widget=DayInput())
    date_to = forms.DateField(label="По", widget=DayInput())
    license_photo = forms.ImageField(
        label="Фото водительских прав", required=False,
        widget=forms.FileInput(attrs={"accept": "image/*", "class": "sr"}),
    )
    agree = forms.BooleanField(
        label="Согласен с правилами аренды и осмотром машины по фото",
        error_messages={"required": "Отметьте согласие с правилами аренды."},
    )

    def __init__(self, *args, listing, **kwargs):
        self.listing = listing
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields["date_from"].widget.attrs.update({"min": today.isoformat(), "data-date-from": ""})
        self.fields["date_to"].widget.attrs.update({"min": (today + timedelta(days=1)).isoformat(), "data-date-to": ""})
        if not listing.is_car:
            del self.fields["license_photo"]

    def clean_license_photo(self):
        photo = self.cleaned_data.get("license_photo")
        if isinstance(photo, UploadedFile):
            try:
                return shrink(photo, max_side=1600)
            except BadImage as error:
                raise ValidationError(str(error))
        return photo

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()
        start, end = cleaned.get("date_from"), cleaned.get("date_to")
        if start and start < today:
            self.add_error("date_from", "Дата начала не может быть в прошлом.")
        elif start and end:
            if end <= start:
                self.add_error("date_to", "Дата возврата должна быть позже даты начала.")
            elif (end - start).days > 60:
                self.add_error("date_to", "Забронировать можно не больше чем на 60 дней.")
            elif not self.listing.is_free(start, end):
                raise ValidationError("На эти даты машина уже занята. Выберите другие даты.")
        if self.listing.is_car and not cleaned.get("license_photo") and not self.has_error("license_photo"):
            self.add_error("license_photo", "Загрузите фото водительских прав: без них владелец не сможет подтвердить заявку.")
        return cleaned
