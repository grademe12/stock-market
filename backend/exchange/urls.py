from django.urls import path

from exchange import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("orders/", views.create_order, name="order-create"),
    path("orders/<uuid:order_id>/", views.cancel_order, name="order-cancel"),
    path("books/<str:symbol>/", views.book_detail, name="book-detail"),
    path("traders/", views.trader_profile_list, name="trader-profile-list"),
    path(
        "traders/<uuid:trader_id>/",
        views.trader_profile_detail,
        name="trader-profile-detail",
    ),
    path(
        "simulations/participants/start/",
        views.start_participant_simulation,
        name="participant-simulation-start",
    ),
    path(
        "simulations/participants/tick/",
        views.tick_participant_simulation,
        name="participant-simulation-tick",
    ),
    path(
        "simulations/participants/",
        views.participant_simulation,
        name="participant-simulation",
    ),
]
