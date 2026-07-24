from rest_framework import serializers

from exchange.orderbook import BookSnapshot, MatchResult, Order, OrderSide, Trade


class OrderRequestSerializer(serializers.Serializer):
    user_id = serializers.CharField(max_length=128, trim_whitespace=True)
    symbol = serializers.CharField(max_length=6, trim_whitespace=True)
    side = serializers.ChoiceField(choices=[(side.value, side.value) for side in OrderSide])
    price = serializers.IntegerField(min_value=1)
    qty = serializers.IntegerField(min_value=1)

    def create_order(self) -> Order:
        return Order(
            user_id=self.validated_data["user_id"],
            symbol=self.validated_data["symbol"],
            side=OrderSide(self.validated_data["side"]),
            price=self.validated_data["price"],
            quantity=self.validated_data["qty"],
        )


def trade_payload(trade: Trade) -> dict[str, object]:
    return {
        "trade_id": str(trade.trade_id),
        "symbol": trade.symbol,
        "price": trade.price,
        "qty": trade.quantity,
        "buy_order_id": str(trade.buy_order_id),
        "sell_order_id": str(trade.sell_order_id),
    }


def match_result_payload(result: MatchResult) -> dict[str, object]:
    return {
        "order_id": str(result.order_id),
        "trades": [trade_payload(trade) for trade in result.trades],
        "remaining_qty": result.remaining_quantity,
    }


def snapshot_payload(snapshot: BookSnapshot) -> dict[str, object]:
    return {
        "symbol": snapshot.symbol,
        "bids": [{"price": level.price, "qty": level.quantity} for level in snapshot.bids],
        "asks": [{"price": level.price, "qty": level.quantity} for level in snapshot.asks],
    }
