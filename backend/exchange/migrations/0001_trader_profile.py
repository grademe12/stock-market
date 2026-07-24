import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="TraderProfile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=100, unique=True)),
                ("user_id", models.CharField(max_length=128, unique=True)),
                ("strategy", models.CharField(choices=[("noise", "Noise")], default="noise", max_length=20)),
                ("enabled", models.BooleanField(default=True)),
                ("symbol", models.CharField(default="005930", max_length=6)),
                ("reference_price", models.PositiveBigIntegerField(default=70000)),
                ("price_step", models.PositiveBigIntegerField(default=100)),
                ("max_offset_steps", models.PositiveIntegerField(default=5)),
                ("quantity_min", models.PositiveIntegerField(default=1)),
                ("quantity_max", models.PositiveIntegerField(default=10)),
                ("order_ttl_ticks", models.PositiveIntegerField(default=5)),
                ("interval_ticks", models.PositiveIntegerField(default=1)),
                ("seed", models.IntegerField(default=42)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("name",)},
        ),
    ]
