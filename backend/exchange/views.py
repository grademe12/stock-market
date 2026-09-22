import logging
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError, connection
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from exchange.orderbook import OrderNotFoundError, OrderSide
from exchange.orderbook.registry import books
from exchange.models import MarketDaily, TraderProfile
from exchange.sharding import advertised_hostname, prometheus_sd_targets
from exchange.simulation import (
    FALLBACK_SYMBOL,
    is_owned_symbol,
    is_simulated_symbol,
    matcher_shard_for,
)
from exchange.market_session import ALWAYS_OPEN, MarketSession
from exchange.metrics import (
    ORDERBOOK_DEPTH,
    ORDERS_REJECTED,
    ORDERS_SUBMITTED,
    TRADED_QUANTITY,
    TRADES_EXECUTED,
)
from exchange.serializers import (
    OrderRequestSerializer,
    RecentTradeQuerySerializer,
    SymbolQuerySerializer,
    TraderProfileSerializer,
    match_result_payload,
    snapshot_payload,
    trade_payload,
)

SIMULATION_SYMBOL = FALLBACK_SYMBOL
execution_logger = logging.getLogger("exchange.execution")


def _rollover_market_session() -> None:
    if settings.SIMULATION_MARKET_MODE == ALWAYS_OPEN:
        return

    session = MarketSession(settings.SIMULATION_MARKET_MODE)
    session_date = session.session_date()
    cleared_symbols = books.rollover(session_date)
    if not cleared_symbols:
        return

    for symbol in cleared_symbols:
        for side in OrderSide:
            ORDERBOOK_DEPTH.labels(symbol, side.value).set(0)

    logging.info(
        "event=market_session_rollover session_date=%s cleared_symbols=%s",
        session_date.isoformat() if session_date is not None else "-",
        len(cleared_symbols),
    )


def _update_orderbook_depth(symbol: str) -> None:
    book = books.get(symbol)
    if book is None:
        return
    snapshot = book.snapshot()
    for side, levels in (
        (OrderSide.BUY, snapshot.bids),
        (OrderSide.SELL, snapshot.asks),
    ):
        ORDERBOOK_DEPTH.labels(symbol, side.value).set(
            sum(level.quantity for level in levels)
        )


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
            {
                "status": "not_ready",
                "database": "unavailable",
                **_shard_topology(),
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return Response({"status": "ready", "database": "ok", **_shard_topology()})


def _shard_topology() -> dict[str, int]:
    return {
        "shard_index": settings.SIMULATION_SHARD_INDEX,
        "shard_count": settings.SIMULATION_SHARD_COUNT,
        "listen_port": settings.SIMULATION_LISTEN_PORT,
    }


@api_view(["GET"])
def prometheus_service_discovery(request):
    """Advertise host-network matcher scrape targets from this process's shard count."""
    try:
        hostname = advertised_hostname(request.get_host())
    except ValueError:
        return Response({"detail": "host header is required"}, status=status.HTTP_400_BAD_REQUEST)
    return Response(
        prometheus_sd_targets(
            hostname,
            settings.SIMULATION_SHARD_COUNT,
            base_port=settings.SIMULATION_LISTEN_PORT - settings.SIMULATION_SHARD_INDEX,
        )
    )


@api_view(["POST"])
def create_order(request):
    if not MarketSession(settings.SIMULATION_MARKET_MODE).is_open():
        ORDERS_REJECTED.labels("market_closed").inc()
        return Response(
            {"detail": "market is closed"},
            status=status.HTTP_409_CONFLICT,
        )

    _rollover_market_session()

    serializer = OrderRequestSerializer(data=request.data)
    if not serializer.is_valid():
        ORDERS_REJECTED.labels("validation_error").inc()
        raise ValidationError(serializer.errors)
    order = serializer.create_order()

    if not is_simulated_symbol(order.symbol):
        ORDERS_REJECTED.labels("unsupported_symbol").inc()
        raise ValidationError({"symbol": "symbol is not in the current simulation set"})
    if not is_owned_symbol(order.symbol):
        ORDERS_REJECTED.labels("wrong_shard").inc()
        raise ValidationError({"symbol": "symbol is owned by another matcher shard"})

    ORDERS_SUBMITTED.labels(order.symbol, order.side.value).inc()
    result = books.submit(order)
    TRADES_EXECUTED.labels(order.symbol).inc(len(result.trades))
    TRADED_QUANTITY.labels(order.symbol).inc(
        sum(trade.quantity for trade in result.trades)
    )
    _update_orderbook_depth(order.symbol)
    _log_executed_trades(result)
    return Response(
        match_result_payload(result),
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def book_detail(request, symbol: str):
    _rollover_market_session()
    book = books.get(symbol)
    if book is None:
        raise NotFound("symbol was not found")

    return Response(snapshot_payload(book.snapshot()))


@api_view(["GET"])
def recent_trade_list(request):
    _rollover_market_session()
    query = RecentTradeQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    symbol = query.validated_data["symbol"]
    book = books.get(symbol)
    if book is None:
        raise NotFound("symbol was not found")

    trades = book.recent_trades(query.validated_data["limit"])
    return Response(
        {
            "symbol": symbol,
            "trades": [trade_payload(trade) for trade in trades],
        }
    )


@api_view(["GET"])
def symbol_list(request):
    query = SymbolQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)

    latest_trade_date = MarketDaily.objects.aggregate(latest=Max("trade_date"))["latest"]
    if latest_trade_date is None:
        return Response({"trade_date": None, "results": []})

    records = MarketDaily.objects.filter(trade_date=latest_trade_date).select_related("symbol")
    search_term = query.validated_data["q"]
    if search_term:
        records = records.filter(
            Q(symbol__ticker__icontains=search_term) | Q(symbol__name__icontains=search_term)
        )

    records = records.order_by("trading_value_rank", "symbol_id")[
        : query.validated_data["limit"]
    ]
    return Response(
        {
            "trade_date": latest_trade_date.isoformat(),
            "results": [
                {
                    "ticker": record.symbol_id,
                    "name": record.symbol.name,
                    "market": record.symbol.market,
                    "close_price": record.close_price,
                    "volume": record.volume,
                    "trading_value": record.trading_value,
                    "trading_value_rank": record.trading_value_rank,
                    "simulation_enabled": is_simulated_symbol(record.symbol_id),
                    "matcher_shard": matcher_shard_for(record.symbol_id),
                }
                for record in records
            ],
        }
    )


@api_view(["DELETE"])
def cancel_order(request, order_id: UUID):
    _rollover_market_session()
    symbol = (request.query_params.get("symbol") or "").strip()
    if symbol:
        if not is_simulated_symbol(symbol):
            raise ValidationError({"symbol": "symbol is not in the current simulation set"})
        if not is_owned_symbol(symbol):
            raise ValidationError({"symbol": "symbol is owned by another matcher shard"})
    try:
        canceled_order = books.cancel(order_id)
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

    _update_orderbook_depth(canceled_order.order.symbol)
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
