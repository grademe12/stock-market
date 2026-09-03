from django.contrib import admin
from django.urls import include, path

from exchange.metrics import metrics_view

urlpatterns = [
    path("metrics/", metrics_view, name="metrics"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("exchange.urls")),
]
