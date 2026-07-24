from django.urls import path

from exchange import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("orders/", views.create_order, name="order-create"),
    path("orders/<uuid:order_id>/", views.cancel_order, name="order-cancel"),
    path("books/<str:symbol>/", views.book_detail, name="book-detail"),
]
