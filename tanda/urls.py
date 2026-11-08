from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "TANDA — администрирование"
admin.site.site_title = "TANDA"
admin.site.index_title = "Объявления, брони и пользователи"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("rentals.urls")),
]

# Фото машин в режиме разработки. На сервере папку media раздаёт веб-сервер (nginx и т. п.)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
