from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve

admin.site.site_header = "TANDA — администрирование"
admin.site.site_title = "TANDA"
admin.site.index_title = "Объявления, брони и пользователи"


def serve_public_media(request, path):
    return serve(request, path, document_root=settings.MEDIA_ROOT)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("media/<path:path>", serve_public_media),
    path("", include("rentals.urls")),
]
