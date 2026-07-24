from uuid import UUID

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from exchange.orderbook import OrderBook, OrderNotFoundError
from exchange.serializers import OrderRequestSerializer, match_result_payload, snapshot_payload

SIMULATION_SYMBOL = "005930"
order_book = OrderBook(symbol=SIMULATION_SYMBOL)


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

    return Response(
        match_result_payload(order_book.submit(order)),
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
