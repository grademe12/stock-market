from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exchange", "0006_traderprofile_interval_seconds"),
    ]

    operations = [
        migrations.CreateModel(
            name="MarketEventInbox",
            fields=[
                (
                    "event_id",
                    models.CharField(
                        max_length=255,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("symbol", models.CharField(max_length=6)),
                ("event_type", models.CharField(max_length=64)),
                (
                    "direction",
                    models.CharField(
                        choices=[
                            ("BUY", "Buy"),
                            ("SELL", "Sell"),
                            ("MIXED", "Mixed"),
                        ],
                        max_length=5,
                    ),
                ),
                ("confidence", models.FloatField()),
                (
                    "impact",
                    models.CharField(
                        choices=[
                            ("low", "Low"),
                            ("medium", "Medium"),
                            ("high", "High"),
                        ],
                        max_length=6,
                    ),
                ),
                ("occurred_at", models.DateTimeField(blank=True, null=True)),
                ("detected_at", models.DateTimeField()),
                ("source", models.CharField(max_length=64)),
                ("source_item_id", models.CharField(blank=True, max_length=255)),
                ("headline", models.TextField(blank=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("dispatched", "Dispatched"),
                            ("stale", "Stale"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ("received_at", "event_id"),
                "indexes": [
                    models.Index(
                        fields=["state", "received_at"],
                        name="event_inbox_state_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("confidence__gte", 0.0),
                            ("confidence__lte", 1.0),
                        ),
                        name="market_event_confidence_range",
                    ),
                ],
            },
        ),
    ]
}
