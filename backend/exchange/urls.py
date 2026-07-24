from django.urls import path

from exchange.views import health

urlpatterns = [
    path("health/", health, name="health"),
]
