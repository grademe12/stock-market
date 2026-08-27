import logging
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError, connection
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from exchange.orderbook import OrderBook, OrderNotFoundError
from exchange.models import TraderProfile
from exchange.serializers import (
    OrderRequestSerializer,
    TraderProfileSerializer,
    match_result_payload,
    snapshot_payload,
)

SIMULATION_SYMBOL = "005930"
execution_logger = logging.getLogger("exchange.execution")
order_book = OrderBook(symbol=SIMULATION_SYMBOL)


@api_view(["GET"])
def health(request):
    """Return the smallest possible DRF endpoint for local verification."""
    return Response({"status": "ok"})


@api_view(["GET"])
def readiness(request):
    """Report whether the process can reach its configured database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return Response(
            {"status": "not_ready", "database": "unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ready", "database": "ok"})


@api_view(["POST"])
def create_order(request):
    serializer = OrderRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    order = serializer.create_order()

    if order.symbol != SIMULATION_SYMBOL:
        raise ValidationError({"symbol": f"only {SIMULATION_SYMBOL} is supported"})

    result = order_book.submit(order)
    _log_executed_trades(result)
    return Response(
        match_result_payload(result),
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def book_detail(request, symbol: str):
    if symbol != SIMULATION_SYMBOL:
        raise NotFound("symbol was not found")

    return Response(snapshot_payload(order_book.snapshot()))


@api_view(["DELETE"])
def cancel_order(request, order_id: UUID):
    try:
        canceled_order = order_book.cancel(order_id)
    except OrderNotFoundError:
        # A TTL-based client can race a fill. Cancellation is intentionally
        # idempotent even though this early in-memory engine has no history.
        return Response(
            {
                "order_id": str(order_id),
                "status": "ALREADY_CLOSED",
                "canceled_qty": 0,
            }
        )

    return Response(
        {
            "order_id": str(canceled_order.order.order_id),
            "status": "CANCELED",
            "canceled_qty": canceled_order.remaining_quantity,
        }
    )


def _log_executed_trades(result) -> None:
    """Emit one compact, machine-readable line per matched trade when enabled."""
    if not settings.TRADE_EXECUTION_LOG_ENABLED:
        return
    for trade in result.trades:
        execution_logger.info(
            "event=trade_executed symbol=%s price=%s qty=%s buy_order_id=%s sell_order_id=%s",
            trade.symbol,
            trade.price,
            trade.quantity,
            trade.buy_order_id,
            trade.sell_order_id,
        )


def _require_development_mode() -> None:
    if not settings.DEBUG:
        raise PermissionDenied("trader profile changes are only available in DEBUG mode")


@api_view(["GET", "POST"])
def trader_profile_list(request):
    if request.method == "GET":
        profiles = TraderProfile.objects.all()
        return Response(TraderProfileSerializer(profiles, many=True).data)

    _require_development_mode()
    serializer = TraderProfileSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    profile = serializer.save()
    return Response(TraderProfileSerializer(profile).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
def trader_profile_detail(request, trader_id: UUID):
    profile = get_object_or_404(TraderProfile, id=trader_id)

    if request.method == "GET":
        return Response(TraderProfileSerializer(profile).data)

    _require_development_mode()
    if request.method == "PATCH":
        serializer = TraderProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(TraderProfileSerializer(serializer.save()).data)

    profile.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
