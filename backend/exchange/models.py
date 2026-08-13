import uuid

from django.db import models


class TraderProfile(models.Model):
    """Persisted configuration for one simulated trading participant."""

    class Strategy(models.TextChoices):
        NOISE = "noise", "Noise"
        MOMENTUM = "momentum", "Momentum"
        MEAN_REVERSION = "mean_reversion", "Mean Reversion"
        LIQUIDITY_PROVIDER = "liquidity_provider", "Liquidity Provider"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    user_id = models.CharField(max_length=128, unique=True)
    strategy = models.CharField(max_length=20, choices=Strategy.choices, default=Strategy.NOISE)
    enabled = models.BooleanField(default=True)
    symbol = models.CharField(max_length=6, default="005930")
    reference_price = models.PositiveBigIntegerField(default=70_000)
    price_step = models.PositiveBigIntegerField(default=100)
    max_offset_steps = models.PositiveIntegerField(default=5)
    quantity_min = models.PositiveIntegerField(default=1)
    quantity_max = models.PositiveIntegerField(default=10)
    order_ttl_ticks = models.PositiveIntegerField(default=5)
    interval_ticks = models.PositiveIntegerField(default=1)
    seed = models.IntegerField(default=42)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self) -> str:
        return self.name


class Symbol(models.Model):
    class Market(models.TextChoices):
        KOSPI = "KOSPI", "KOSPI"

    ticker = models.CharField(primary_key=True, max_length=6)
    name = models.CharField(max_length=120)
    market = models.CharField(max_length=10, choices=Market.choices, default=Market.KOSPI)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("ticker",)

    def __str__(self) -> str:
        return f"{self.ticker} {self.name}"


class MarketDaily(models.Model):
    symbol = models.ForeignKey(Symbol, on_delete=models.CASCADE, related_name="daily_records")
    trade_date = models.DateField()
    close_price = models.PositiveBigIntegerField()
    volume = models.PositiveBigIntegerField()
    trading_value = models.PositiveBigIntegerField()
    trading_value_rank = models.PositiveSmallIntegerField()
    source = models.CharField(max_length=30, default="krx_open_api")
    source_payload = models.JSONField()
    imported_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-trade_date", "trading_value_rank", "symbol_id")
        constraints = [
            models.UniqueConstraint(
                fields=("symbol", "trade_date"),
                name="unique_symbol_market_daily_trade_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=("trade_date", "trading_value_rank"),
                name="market_daily_date_rank_idx",
            ),
        ]


class ReferenceImportRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trade_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    selected_count = models.PositiveSmallIntegerField(default=0)
    source = models.CharField(max_length=30, default="krx_open_api")
    error_message = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-started_at",)
