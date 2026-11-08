from django.contrib.auth.views import LogoutView
from django.urls import path

from . import api, views

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("car/<int:pk>/", views.listing_detail, name="listing_detail"),
    path("car/<int:pk>/edit/", views.listing_edit, name="listing_edit"),
    path("car/<int:pk>/toggle/", views.listing_toggle, name="listing_toggle"),
    path("sdat/", views.listing_create, name="listing_create"),
    path("kabinet/", views.cabinet, name="cabinet"),
    path("booking/<int:pk>/", views.booking_detail, name="booking_detail"),
    path("booking/<int:pk>/license/", views.booking_license, name="booking_license"),
    path("booking/<int:pk>/<slug:action>/", views.booking_action, name="booking_action"),
    path("osmotr/", views.inspect_page, name="inspect"),
    path("register/", views.register, name="register"),
    path("login/", views.TandaLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("profile/", views.profile_edit, name="profile_edit"),
    path("profile/password/", views.TandaPasswordChangeView.as_view(), name="password_change"),
    path("profile/delete/", views.account_delete, name="account_delete"),
    path("api/assistant/", api.assistant, name="api_assistant"),
    path("api/suggest-price/", api.suggest_price, name="api_suggest_price"),
    path("api/inspect/", api.inspect, name="api_inspect"),
]
