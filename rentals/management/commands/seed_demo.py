"""
python manage.py seed_demo          — добавить демо-каталог с фотографиями (8 машин и 3 бусика)
python manage.py seed_demo --remove — убрать демо-объявления и демо-владельцев

Команду можно запускать повторно: объявления обновятся, дубликатов не будет.
"""
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from rentals.models import Listing, Profile

DEMO = [
    {"key": "azamat", "owner": "Азамат", "kind": "car", "title": "Toyota Camry 70", "year": 2019, "city": "Бишкек", "seats": 5, "photo": "demo/camry.jpg",
     "gear": "автомат", "fuel": "бензин", "price": 3500, "rating": "4.9", "trips": 34, "color": "#E7E5E0",
     "description": "Бизнес-седан в отличном состоянии: кондиционер, камера заднего вида, CarPlay. Удобен для города и поездок на Иссык-Куль."},
    {"key": "aigerim", "owner": "Айгерим", "kind": "car", "title": "Honda Fit", "year": 2015, "city": "Бишкек", "seats": 5, "photo": "demo/fit.jpg",
     "gear": "вариатор", "fuel": "гибрид", "price": 2000, "rating": "4.8", "trips": 51, "color": "#C23B3B",
     "description": "Экономичный гибрид для города: расход около 4 литров на 100 км, легко парковать."},
    {"key": "nurlan", "owner": "Нурлан", "kind": "car", "title": "Hyundai Sonata", "year": 2020, "city": "Бишкек", "seats": 5, "photo": "demo/sonata.jpg",
     "gear": "автомат", "fuel": "газ/бензин", "price": 3000, "rating": "4.7", "trips": 22, "color": "#C9CCD1",
     "description": "Просторный седан на газе и бензине, выгоден для дальних поездок."},
    {"key": "erlan", "owner": "Эрлан", "kind": "car", "title": "Toyota Land Cruiser Prado", "year": 2016, "city": "Бишкек", "seats": 7, "photo": "demo/prado.jpg",
     "gear": "автомат", "fuel": "дизель", "price": 6500, "rating": "5.0", "trips": 17, "color": "#6B7480",
     "description": "Внедорожник для гор: Сон-Куль, Нарын, Ала-Арча. Полный привод и 7 мест."},
    {"key": "dinara", "owner": "Динара", "kind": "car", "title": "Honda Stepwgn", "year": 2014, "city": "Бишкек", "seats": 7, "photo": "demo/stepwgn.jpg",
     "gear": "вариатор", "fuel": "бензин", "price": 3000, "rating": "4.6", "trips": 29, "color": "#D8D2C4",
     "description": "Минивэн на 7 мест для семьи: раздвижные двери и большой багажник."},
    {"key": "bekzat", "owner": "Бекзат", "kind": "car", "title": "Kia K5", "year": 2021, "city": "Ош", "seats": 5, "photo": "demo/k5.jpg",
     "gear": "автомат", "fuel": "газ/бензин", "price": 3200, "rating": "4.8", "trips": 12, "color": "#2F5D8C",
     "description": "Свежий седан на газе для поездок по югу страны."},
    {"key": "gulnara", "owner": "Гульнара", "kind": "car", "title": "Toyota Corolla", "year": 2017, "city": "Каракол", "seats": 5, "photo": "demo/corolla.jpg",
     "gear": "автомат", "fuel": "бензин", "price": 2800, "rating": "4.7", "trips": 19, "color": "#E7E5E0",
     "description": "Надёжный седан в Караколе: удобно забрать прямо у Иссык-Куля."},
    {"key": "marat", "owner": "Марат", "kind": "car", "title": "Chevrolet Cobalt", "year": 2022, "city": "Чолпон-Ата", "seats": 5, "photo": "demo/cobalt.jpg",
     "gear": "автомат", "fuel": "бензин", "price": 2300, "rating": "4.6", "trips": 26, "color": "#F28C28",
     "description": "Простой и экономичный седан на побережье Иссык-Куля."},
    {"key": "talant", "owner": "Талант", "kind": "van", "title": "Hyundai Starex", "year": 2017, "city": "Бишкек", "seats": 11, "photo": "demo/starex.jpg",
     "price": 8000, "rating": "4.9", "trips": 41, "color": "#E7E5E0",
     "description": "Бусик на 11 мест с водителем: трансферы из аэропорта, туры и свадьбы."},
    {"key": "ulan", "owner": "Улан", "kind": "van", "title": "Mercedes-Benz Sprinter", "year": 2015, "city": "Бишкек", "seats": 18, "photo": "demo/sprinter.jpg",
     "price": 12000, "rating": "4.8", "trips": 37, "color": "#C9CCD1",
     "description": "Бус на 18 мест с опытным водителем для групповых туров по Кыргызстану."},
    {"key": "mirlan", "owner": "Мирлан", "kind": "van", "title": "Toyota Hiace", "year": 2018, "city": "Чолпон-Ата", "seats": 14, "photo": "demo/hiace.jpg",
     "price": 10000, "rating": "4.7", "trips": 23, "color": "#D8D2C4",
     "description": "Бусик на 14 мест с водителем на Иссык-Куле: экскурсии по побережью."},
]


class Command(BaseCommand):
    help = "Добавляет демо-каталог TANDA с фото: 8 легковых машин и 3 бусика с водителем."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Удалить демо-объявления и демо-владельцев")

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        if options["remove"]:
            deleted, _ = User.objects.filter(username__startswith="demo-").delete()
            self.stdout.write(self.style.SUCCESS(f"Демо-данные удалены (записей: {deleted})."))
            return

        created = updated = 0
        for item in DEMO:
            user, is_new_user = User.objects.get_or_create(
                username=f"demo-{item['key']}", defaults={"first_name": item["owner"]}
            )
            if is_new_user:
                user.set_unusable_password()  # под демо-владельцами войти нельзя
                user.save()
            Profile.objects.get_or_create(user=user, defaults={"city": item["city"], "role": "owner"})
            fields = {k: v for k, v in item.items() if k not in ("key", "owner", "photo")}
            fields.setdefault("gear", "")
            fields.setdefault("fuel", "")
            listing, is_new = Listing.objects.update_or_create(
                owner=user, title=item["title"], defaults={**fields, "is_demo": True, "has_osago": True}
            )
            if not listing.photo:
                photo_path = finders.find(f"rentals/img/{item['photo']}")
                if not photo_path:
                    raise CommandError(f"Не найден файл демо-фото: rentals/img/{item['photo']}")
                with open(photo_path, "rb") as photo_file:
                    listing.photo.save(item["photo"].rsplit("/", 1)[-1], File(photo_file), save=True)
            created += is_new
            updated += not is_new
        self.stdout.write(self.style.SUCCESS(
            f"Демо-каталог готов: добавлено {created}, обновлено {updated}. "
            "Заявки на демо-машины подтверждает администратор (python manage.py createsuperuser)."
        ))
