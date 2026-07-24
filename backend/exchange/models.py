import uuid

from django.db import models


class TraderProfile(models.Model):
    """Persisted configuration for one simulated trading participant."""
    class Strategy(models.TextChoices):
        NOISE = "noise", "Noise"

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
