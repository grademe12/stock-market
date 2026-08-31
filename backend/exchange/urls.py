from django.urls import path

from exchange import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ready/", views.readiness, name="readiness"),
    path("orders/", views.create_order, name="order-create"),
    path("orders/<uuid:order_id>/", views.cancel_order, name="order-cancel"),
    path("books/<str:symbol>/", views.book_detail, name="book-detail"),
    path("trades/", views.recent_trade_list, name="recent-trade-list"),
    path("symbols/", views.symbol_list, name="symbol-list"),
    path("traders/", views.trader_profile_list, name="trader-profile-list"),
    path(
        "traders/<uuid:trader_id>/",
        views.trader_profile_detail,
        name="trader-profile-detail",
    ),
]
