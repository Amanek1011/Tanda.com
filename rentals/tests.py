"""Тесты TANDA. Запуск: python manage.py test"""
import io
import json
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import ai, rules
from .models import Booking, Listing, Profile

User = get_user_model()
TMP_MEDIA = tempfile.mkdtemp()


def jpeg(name="photo.jpg", size=(64, 48), color=(200, 30, 30)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


def day(n):
    return (timezone.localdate() + timedelta(days=n)).isoformat()


class RulesTests(TestCase):
    def test_quote_car(self):
        q = rules.quote(3000, "car", 3)
        self.assertEqual(q["subtotal"], 9000)
        self.assertEqual(q["fee"], 450)
        self.assertEqual(q["total"], 9450)
        self.assertEqual(q["owner_earn"], 7200)
        self.assertEqual(q["tanda_income"], 2250)  # 20% комиссии + 5% сбора
        self.assertEqual(q["deposit"], 5000)

    def test_quote_van(self):
        q = rules.quote(8000, "van", 2)
        self.assertEqual(q["owner_earn"], 13600)
        self.assertEqual(q["tanda_income"], 2400 + 800)
        self.assertEqual(q["deposit"], 0)

    def test_phone(self):
        for raw in ["+996 502 142 280", "0502 142 280", "502142280", "996-502-14-22-80"]:
            self.assertEqual(rules.normalize_phone(raw), "996502142280")
        self.assertEqual(rules.normalize_phone("12345"), "")
        self.assertEqual(rules.format_phone("996502142280"), "+996 502 142 280")

    def test_plural(self):
        self.assertEqual(rules.plural(1, rules.DAYS), "день")
        self.assertEqual(rules.plural(3, rules.DAYS), "дня")
        self.assertEqual(rules.plural(11, rules.DAYS), "дней")
        self.assertEqual(rules.plural(21, rules.DAYS), "день")


@override_settings(MEDIA_ROOT=TMP_MEDIA, ANTHROPIC_API_KEY="")
class SiteTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.private_dir = tempfile.mkdtemp()
        field = Booking._meta.get_field("license_photo")
        cls.old_storage = field.storage
        field.storage = FileSystemStorage(location=cls.private_dir)

    @classmethod
    def tearDownClass(cls):
        Booking._meta.get_field("license_photo").storage = cls.old_storage
        shutil.rmtree(cls.private_dir, ignore_errors=True)
        shutil.rmtree(TMP_MEDIA, ignore_errors=True)
        super().tearDownClass()

    def make_user(self, phone, name="Тест Тестов", staff=False):
        user = User.objects.create_user(username=phone, password="Strong-pass-42", first_name=name, is_staff=staff)
        Profile.objects.create(user=user, phone=phone)
        return user

    def make_listing(self, owner, **kw):
        data = {"kind": "car", "title": "Toyota Camry", "year": 2019, "city": "Бишкек", "seats": 5,
                "gear": "автомат", "fuel": "бензин", "price": 3000, "has_osago": True}
        data.update(kw)
        return Listing.objects.create(owner=owner, **data)


class MediaServingTests(TestCase):
    @override_settings(DEBUG=False)
    def test_public_media_is_served_in_production_without_exposing_private_media(self):
        with tempfile.TemporaryDirectory() as media_root, tempfile.TemporaryDirectory() as private_root:
            public_photo = Path(media_root) / "listings" / "car.jpg"
            public_photo.parent.mkdir(parents=True)
            public_photo.write_bytes(b"public image")

            private_photo = Path(private_root) / "licenses" / "license.jpg"
            private_photo.parent.mkdir(parents=True)
            private_photo.write_bytes(b"private image")

            with override_settings(MEDIA_ROOT=media_root, PRIVATE_MEDIA_ROOT=private_root):
                response = self.client.get("/media/listings/car.jpg")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"public image")
                self.assertEqual(self.client.get("/media/licenses/license.jpg").status_code, 404)


class AccountTests(SiteTestCase):
    def test_register_and_login_by_phone(self):
        res = self.client.post(reverse("register"), {
            "name": "Айбек Асанов", "phone": "+996 555 123 456", "city": "Ош", "role": "both",
            "password1": "Strong-pass-42", "password2": "Strong-pass-42", "agree": "on",
        })
        self.assertRedirects(res, reverse("cabinet"))
        user = User.objects.get(username="996555123456")
        self.assertEqual(user.first_name, "Айбек")
        self.assertEqual(user.profile.city, "Ош")
        self.client.post(reverse("logout"))
        res = self.client.post(reverse("login"), {"username": "0555 123 456", "password": "Strong-pass-42"})
        self.assertRedirects(res, reverse("cabinet"))

    def test_duplicate_phone_and_weak_password(self):
        self.make_user("996555123456")
        res = self.client.post(reverse("register"), {
            "name": "Другой", "phone": "0555123456", "city": "Бишкек", "role": "renter",
            "password1": "12345678", "password2": "12345678", "agree": "on",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "уже зарегистрирован")
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_password(self):
        self.make_user("996555123456")
        res = self.client.post(reverse("login"), {"username": "+996555123456", "password": "wrong"})
        self.assertContains(res, "Неверный телефон или пароль")

    def test_profile_edit_changes_login(self):
        user = self.make_user("996555123456")
        self.client.force_login(user)
        res = self.client.post(reverse("profile_edit"), {"name": "Новое Имя", "phone": "0700 111 222", "city": "Нарын", "role": "owner"})
        self.assertRedirects(res, reverse("cabinet"))
        user.refresh_from_db()
        self.assertEqual(user.username, "996700111222")
        self.assertEqual(user.profile.city, "Нарын")

    def test_delete_account(self):
        user = self.make_user("996555123456")
        self.client.force_login(user)
        self.client.post(reverse("account_delete"))
        self.assertFalse(User.objects.filter(pk=user.pk).exists())


class ListingTests(SiteTestCase):
    def test_create_requires_login(self):
        res = self.client.get(reverse("listing_create"))
        self.assertContains(res, "Сначала войдите в аккаунт")
        res = self.client.post(reverse("listing_create"), {})
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("login"), res["Location"])

    def test_create_listing_with_photo(self):
        owner = self.make_user("996555000001", "Азиз Владелец")
        self.client.force_login(owner)
        res = self.client.post(reverse("listing_create"), {
            "kind": "car", "city": "Бишкек", "title": "  Honda   Fit ", "year": 2016, "seats": 5,
            "gear": "вариатор", "fuel": "гибрид", "price": 2200, "description": "Чистая машина",
            "has_osago": "on", "photo": jpeg(size=(3000, 2000)),
        })
        listing = Listing.objects.get()
        self.assertRedirects(res, listing.get_absolute_url())
        self.assertEqual(listing.title, "Honda Fit")
        with Image.open(listing.photo.path) as img:
            self.assertLessEqual(max(img.size), 1600)  # фото уменьшено
        self.assertContains(self.client.get(reverse("catalog")), "Honda Fit")

    def test_osago_required_and_van_seats(self):
        owner = self.make_user("996555000001")
        self.client.force_login(owner)
        res = self.client.post(reverse("listing_create"), {
            "kind": "van", "city": "Бишкек", "title": "Hyundai Starex", "year": 2017, "seats": 5, "price": 8000,
        })
        self.assertContains(res, "только машины с действующим ОСАГО")
        self.assertContains(res, "У бусика от 8 до 20 мест")
        self.assertFalse(Listing.objects.exists())

    def test_toggle_and_edit_only_owner(self):
        owner = self.make_user("996555000001")
        other = self.make_user("996555000002")
        listing = self.make_listing(owner)
        self.client.force_login(other)
        self.assertEqual(self.client.post(reverse("listing_toggle", args=[listing.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("listing_edit", args=[listing.pk])).status_code, 404)
        self.client.force_login(owner)
        self.client.post(reverse("listing_toggle", args=[listing.pk]))
        listing.refresh_from_db()
        self.assertFalse(listing.is_active)
        self.assertNotContains(self.client.get(reverse("catalog")), "Toyota Camry")

    def test_catalog_filters(self):
        owner = self.make_user("996555000001")
        self.make_listing(owner, title="Седан в Оше", city="Ош")
        self.make_listing(owner, title="Бусик Бишкек", kind="van", seats=12, price=9000, gear="", fuel="")
        res = self.client.get(reverse("catalog"), {"city": "Ош"})
        self.assertContains(res, "Седан в Оше")
        self.assertNotContains(res, "Бусик Бишкек")
        res = self.client.get(reverse("catalog"), {"type": "van"})
        self.assertContains(res, "Бусик Бишкек")
        self.assertNotContains(res, "Седан в Оше")


class BookingTests(SiteTestCase):
    def setUp(self):
        self.owner = self.make_user("996555000001", "Владелец Машины")
        self.renter = self.make_user("996555000002", "Арендатор Первый")
        self.listing = self.make_listing(self.owner, price=3000)

    def book(self, user, start=1, end=4, license=True):
        self.client.force_login(user)
        data = {"date_from": day(start), "date_to": day(end), "agree": "on"}
        if license:
            data["license_photo"] = jpeg("license.jpg")
        return self.client.post(reverse("listing_detail", args=[self.listing.pk]), data)

    def test_full_booking_flow(self):
        res = self.book(self.renter)
        booking = Booking.objects.get()
        self.assertRedirects(res, booking.get_absolute_url())
        self.assertEqual((booking.days, booking.subtotal, booking.fee, booking.total), (3, 9000, 450, 9450))
        self.assertEqual((booking.owner_earn, booking.tanda_income), (7200, 2250))
        self.assertTrue(booking.code.startswith("T-"))
        self.assertTrue(booking.license_photo)

        # Телефон владельца скрыт до подтверждения
        self.assertNotContains(self.client.get(booking.get_absolute_url()), "+996 555 000 001")

        self.client.force_login(self.owner)
        cabinet = self.client.get(reverse("cabinet"))
        self.assertContains(cabinet, booking.code)
        self.client.post(reverse("booking_action", args=[booking.pk, "confirm"]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.OK)
        self.assertContains(self.client.get(booking.get_absolute_url()), "+996 555 000 002")

        # Машина пропадает из каталога на эти даты, а на другие видна
        res = self.client.get(reverse("catalog"), {"from": day(2), "to": day(3)})
        self.assertNotContains(res, "Toyota Camry")
        res = self.client.get(reverse("catalog"), {"from": day(10), "to": day(12)})
        self.assertContains(res, "Toyota Camry")

        # Второй арендатор не может взять те же даты
        second = self.make_user("996555000003")
        res = self.book(second, 2, 5)
        self.assertContains(res, "машина уже занята")

    def test_license_required_for_car(self):
        res = self.book(self.renter, license=False)
        self.assertContains(res, "Загрузите фото водительских прав")
        self.assertFalse(Booking.objects.exists())

    def test_cannot_book_own_listing(self):
        self.client.force_login(self.owner)
        res = self.client.get(self.listing.get_absolute_url())
        self.assertContains(res, "Это ваше объявление")
        self.client.post(self.listing.get_absolute_url(), {"date_from": day(1), "date_to": day(3), "agree": "on"})
        self.assertFalse(Booking.objects.exists())

    def test_past_dates_rejected(self):
        res = self.book(self.renter, -2, 1)
        self.assertContains(res, "не может быть в прошлом")

    def test_license_privacy(self):
        self.book(self.renter)
        booking = Booking.objects.get()
        url = reverse("booking_license", args=[booking.pk])
        stranger = self.make_user("996555000009")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(booking.get_absolute_url()).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_renter_cancels_and_cannot_confirm(self):
        self.book(self.renter)
        booking = Booking.objects.get()
        self.client.post(reverse("booking_action", args=[booking.pk, "confirm"]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.NEW)
        self.client.post(reverse("booking_action", args=[booking.pk, "cancel"]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)

    def test_staff_manages_demo_bookings(self):
        call_command("seed_demo", stdout=io.StringIO())
        call_command("seed_demo", stdout=io.StringIO())  # повторный запуск не плодит дубликаты
        self.assertEqual(Listing.objects.filter(is_demo=True).count(), 11)
        self.assertEqual(Listing.objects.filter(is_demo=True, photo="").count(), 0)
        van = Listing.objects.get(title="Hyundai Starex")
        self.client.force_login(self.renter)
        self.client.post(van.get_absolute_url(), {"date_from": day(1), "date_to": day(2), "agree": "on"})
        booking = Booking.objects.get(listing=van)
        admin = self.make_user("996555000777", "Админ", staff=True)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("cabinet")), booking.code)
        self.client.post(reverse("booking_action", args=[booking.pk, "confirm"]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.OK)


class PageTests(SiteTestCase):
    def test_public_pages(self):
        call_command("seed_demo", stdout=io.StringIO())
        for name in ["catalog", "inspect", "register", "login", "listing_create"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        catalog = self.client.get(reverse("catalog"))
        for listing in Listing.objects.filter(is_demo=True):
            self.assertContains(catalog, listing.photo.url)
        listing = Listing.objects.first()
        self.assertContains(self.client.get(listing.get_absolute_url()), "Войти и забронировать")
        self.assertEqual(self.client.get("/car/999999/").status_code, 404)

    def test_cabinet_requires_login(self):
        res = self.client.get(reverse("cabinet"))
        self.assertEqual(res.status_code, 302)


@override_settings(MEDIA_ROOT=TMP_MEDIA)
class AITests(SiteTestCase):
    def post_json(self, name, data):
        return self.client.post(reverse(name), json.dumps(data), content_type="application/json")

    @override_settings(ANTHROPIC_API_KEY="")
    def test_without_key(self):
        res = self.post_json("api_assistant", {"messages": [{"role": "user", "content": "Салам"}]})
        self.assertEqual(res.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", res.json()["error"])

    @override_settings(ANTHROPIC_API_KEY="test-key")
    def test_assistant_returns_cards(self):
        owner = self.make_user("996555000001")
        listing = self.make_listing(owner, title="Hyundai Starex", kind="van", seats=11, price=8000, gear="", fuel="")
        reply = f"Берите Hyundai Starex: 8 000 × 3 + 5% = 25 200 сом.\nIDS: {listing.pk}, 99999"
        with mock.patch("rentals.ai.complete", return_value=reply) as fake:
            res = self.post_json("api_assistant", {
                "messages": [{"role": "assistant", "content": "Привет"}, {"role": "user", "content": "Нас 10 человек"}],
                "from": day(1), "to": day(4),
            })
        data = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["ids"], [listing.pk])
        self.assertNotIn("IDS", data["reply"])
        self.assertIn("Hyundai Starex", data["cards"])
        sent_messages = fake.call_args.args[0]
        self.assertEqual(sent_messages[0]["role"], "user")  # приветствие ассистента отброшено
        self.assertIn(f"{listing.pk} | Бусик | Hyundai Starex", fake.call_args.kwargs["system"])

    @override_settings(ANTHROPIC_API_KEY="test-key")
    def test_suggest_price(self):
        answer = '```json\n{"price": 3170, "range": [2800, 3600], "reason": "Бизнес-седан", "description": "Удобная машина."}\n```'
        with mock.patch("rentals.ai.complete", return_value=answer):
            res = self.post_json("api_suggest_price", {"title": "Toyota Camry", "kind": "car", "year": 2019, "city": "Бишкек", "seats": 5})
        self.assertEqual(res.json()["price"], 3200)
        self.assertEqual(res.json()["range"], [2800, 3600])

    @override_settings(ANTHROPIC_API_KEY="test-key")
    def test_inspect(self):
        answer = json.dumps({"same_car": True, "summary": "Новая царапина.", "new_damages": [
            {"type": "царапина", "location": "дверь", "severity": "лёгкое", "description": "Полоса", "box": [0.7, 0.2, 0.4, 1.4]}]})
        with mock.patch("rentals.ai.complete", return_value=answer) as fake:
            res = self.client.post(reverse("api_inspect"), {"before": jpeg("a.jpg"), "after": jpeg("b.jpg", color=(10, 10, 10))})
        data = res.json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["new_damages"][0]["box"], [0.4, 0.2, 0.7, 1.0])
        content = fake.call_args.args[0][0]["content"]
        self.assertEqual([c["type"] for c in content], ["text", "image", "text", "image", "text"])
        self.assertEqual(content[1]["source"]["media_type"], "image/jpeg")

    @override_settings(ANTHROPIC_API_KEY="test-key")
    def test_inspect_rejects_non_images(self):
        bad = SimpleUploadedFile("a.txt", b"not an image", content_type="text/plain")
        res = self.client.post(reverse("api_inspect"), {"before": bad, "after": jpeg()})
        self.assertEqual(res.status_code, 400)

    def test_history_and_ids_helpers(self):
        history = ai.clean_history([
            {"role": "assistant", "content": "привет"}, {"role": "user", "content": "a"},
            {"role": "user", "content": "b"}, {"role": "assistant", "content": "ответ"}, {"role": "system", "content": "x"},
        ])
        self.assertEqual(history, [{"role": "user", "content": "a\n\nb"}])
        text, ids = ai.split_ids("Ответ\nIDS: 3, #4, 99", {3, 4})
        self.assertEqual((text, ids), ("Ответ", [3, 4]))
        self.assertEqual(ai.parse_json('Вот: {"a": 1} спасибо'), {"a": 1})
