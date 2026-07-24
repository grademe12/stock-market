from rest_framework import serializers

from exchange.models import TraderProfile
from exchange.orderbook import BookSnapshot, MatchResult, Order, OrderSide, Trade
from exchange.participants import SimulationConfig

SIMULATION_SYMBOL = "005930"


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


class ParticipantSimulationConfigSerializer(serializers.Serializer):
    strategy = serializers.ChoiceField(choices=["noise"], default="noise")
    participants = serializers.IntegerField(min_value=1, max_value=100, default=20)
    reference_price = serializers.IntegerField(min_value=1, default=70_000)
    price_step = serializers.IntegerField(min_value=1, default=100)
    max_offset_steps = serializers.IntegerField(min_value=0, max_value=100, default=5)
    quantity_min = serializers.IntegerField(min_value=1, default=1)
    quantity_max = serializers.IntegerField(min_value=1, default=10)
    order_ttl_ticks = serializers.IntegerField(min_value=1, max_value=1_000, default=5)
    interval_ms = serializers.IntegerField(min_value=10, max_value=60_000, default=1_000)
    seed = serializers.IntegerField(default=42)
    trader_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=False,
    )

    def validate(self, attrs):
        if attrs["quantity_max"] < attrs["quantity_min"]:
            raise serializers.ValidationError("quantity_max must be at least quantity_min")
        return attrs

    def validate_trader_ids(self, value):
        if len(set(value)) != len(value):
            raise serializers.ValidationError("trader_ids must not contain duplicates")
        return value

    def create_config(self) -> SimulationConfig:
        return SimulationConfig(
            participants=self.validated_data["participants"],
            reference_price=self.validated_data["reference_price"],
            price_step=self.validated_data["price_step"],
            max_offset_steps=self.validated_data["max_offset_steps"],
            quantity_min=self.validated_data["quantity_min"],
            quantity_max=self.validated_data["quantity_max"],
            order_ttl_ticks=self.validated_data["order_ttl_ticks"],
            interval_ms=self.validated_data["interval_ms"],
            seed=self.validated_data["seed"],
        )

    @property
    def selected_trader_ids(self) -> list:
        return self.validated_data.get("trader_ids", [])


class TraderProfileSerializer(serializers.ModelSerializer):
    """Frontend-facing representation of one simulated market participant."""

    class Meta:
        model = TraderProfile
        fields = [
            "id",
            "name",
            "user_id",
            "strategy",
            "enabled",
            "symbol",
            "reference_price",
            "price_step",
            "max_offset_steps",
            "quantity_min",
            "quantity_max",
            "order_ttl_ticks",
            "interval_ticks",
            "seed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {
            "reference_price": {"min_value": 1},
            "price_step": {"min_value": 1},
            "quantity_min": {"min_value": 1},
            "quantity_max": {"min_value": 1},
            "order_ttl_ticks": {"min_value": 1},
            "interval_ticks": {"min_value": 1},
        }

    def validate(self, attrs):
        instance = self.instance
        quantity_min = attrs.get(
            "quantity_min",
            instance.quantity_min if instance is not None else None,
        )
        quantity_max = attrs.get(
            "quantity_max",
            instance.quantity_max if instance is not None else None,
        )
        if quantity_max is not None and quantity_min is not None and quantity_max < quantity_min:
            raise serializers.ValidationError(
                {"quantity_max": "quantity_max must be at least quantity_min"}
            )

        symbol = attrs.get("symbol", instance.symbol if instance is not None else SIMULATION_SYMBOL)
        if symbol != SIMULATION_SYMBOL:
            raise serializers.ValidationError(
                {"symbol": f"only {SIMULATION_SYMBOL} is supported"}
            )
        return attrs


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
