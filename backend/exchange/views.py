from dataclasses import asdict
import logging
from uuid import UUID

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from exchange.orderbook import OrderBook, OrderNotFoundError
from exchange.participants import ParticipantSimulationRuntime, SimulationAlreadyRunningError
from exchange.participants.adapters import InMemoryOrderBookAdapter
from exchange.models import TraderProfile
from exchange.serializers import (
    OrderRequestSerializer,
    ParticipantSimulationConfigSerializer,
    TraderProfileSerializer,
    match_result_payload,
    snapshot_payload,
)
from exchange.trader_profiles import profiles_to_participants

SIMULATION_SYMBOL = "005930"
execution_logger = logging.getLogger("exchange.execution")
order_book = OrderBook(symbol=SIMULATION_SYMBOL)


def build_participant_runtime() -> ParticipantSimulationRuntime:
    return ParticipantSimulationRuntime(
        InMemoryOrderBookAdapter(lambda: order_book)
    )


participant_runtime = build_participant_runtime()


@api_view(["GET"])
def health(request):
    """Return the smallest possible DRF endpoint for local verification."""
    return Response({"status": "ok"})


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
    except OrderNotFoundError as exc:
        raise NotFound("open order was not found") from exc

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


def _participant_config(request):
    serializer = ParticipantSimulationConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    has_profiles = TraderProfile.objects.exists()
    profiles = TraderProfile.objects.filter(enabled=True)
    selected_trader_ids = serializer.selected_trader_ids
    if selected_trader_ids:
        profiles = profiles.filter(id__in=selected_trader_ids)
        if profiles.count() != len(selected_trader_ids):
            raise ValidationError(
                {"trader_ids": "each selected trader must exist and be enabled"}
            )

    participants = profiles_to_participants(profiles) if has_profiles or selected_trader_ids else None
    return serializer.create_config(), participants


def _require_development_mode() -> None:
    if not settings.DEBUG:
        raise PermissionDenied("participant simulation controls are only available in DEBUG mode")


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


@api_view(["POST"])
def start_participant_simulation(request):
    _require_development_mode()

    try:
        config, participants = _participant_config(request)
        participant_runtime.start(config, participants)
    except SimulationAlreadyRunningError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    return Response(participant_runtime.status_payload(), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def tick_participant_simulation(request):
    _require_development_mode()

    try:
        config, participants = _participant_config(request)
        simulation_status = participant_runtime.tick_once(config, participants)
    except SimulationAlreadyRunningError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

    return Response({"simulation": asdict(simulation_status)})


@api_view(["GET", "DELETE"])
def participant_simulation(request):
    if request.method == "DELETE":
        _require_development_mode()
        participant_runtime.stop()

    return Response(participant_runtime.status_payload())
