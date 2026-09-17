from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exchange", "0005_traderprofile_order_ttl_seconds"),
    ]

    operations = [
        migrations.RenameField(
            model_name="traderprofile",
            old_name="interval_ticks",
            new_name="interval_seconds",
        ),
        migrations.AlterField(
            model_name="traderprofile",
            name="interval_seconds",
            field=models.PositiveIntegerField(default=1),
        ),
    ]
