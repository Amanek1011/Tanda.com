from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import Booking, Listing, Profile

User = get_user_model()


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = "Профиль TANDA"


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = [ProfileInline]
    list_display = ("username", "first_name", "last_name", "is_staff", "date_joined")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "city", "role", "created_at")
    list_filter = ("city", "role")
    search_fields = ("phone", "user__first_name", "user__last_name", "user__username")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "city", "price", "owner", "rating", "is_demo", "is_active", "created_at")
    list_filter = ("kind", "city", "is_demo", "is_active")
    list_editable = ("is_active",)
    search_fields = ("title", "owner__username", "owner__first_name", "owner__last_name")
    raw_id_fields = ("owner",)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("code", "listing", "renter", "date_from", "date_to", "total", "status", "created_at")
    list_filter = ("status", "listing__kind", "listing__is_demo")
    search_fields = ("code", "listing__title", "renter__username", "renter__first_name", "renter__last_name")
    raw_id_fields = ("listing", "renter")
    exclude = ("license_photo",)
    readonly_fields = (
        "code", "days", "price", "subtotal", "fee", "total", "owner_earn", "tanda_income",
        "license_link", "created_at", "decided_at",
    )
    actions = ["confirm_selected", "decline_selected"]

    def has_add_permission(self, request):
        return False  # брони создаются на сайте, там же считаются суммы

    @admin.display(description="Фото прав")
    def license_link(self, obj):
        if not obj.license_photo:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Открыть фото</a>', reverse("booking_license", args=[obj.pk]))

    @admin.action(description="Подтвердить выбранные заявки")
    def confirm_selected(self, request, queryset):
        done = 0
        for booking in queryset.filter(status=Booking.NEW):
            if not booking.clashes().exists():
                booking.status = Booking.OK
                booking.decided_at = timezone.now()
                booking.save(update_fields=["status", "decided_at"])
                done += 1
        self.message_user(request, f"Подтверждено заявок: {done}")

    @admin.action(description="Отклонить выбранные заявки")
    def decline_selected(self, request, queryset):
        done = queryset.filter(status=Booking.NEW).update(status=Booking.NO, decided_at=timezone.now())
        self.message_user(request, f"Отклонено заявок: {done}")
