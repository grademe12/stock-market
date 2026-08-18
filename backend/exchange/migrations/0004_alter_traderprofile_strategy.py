from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exchange", "0003_alter_traderprofile_strategy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="traderprofile",
            name="strategy",
            field=models.CharField(
                choices=[
                    ("noise", "Noise"),
                    ("momentum", "Momentum"),
                    ("mean_reversion", "Mean Reversion"),
                    ("liquidity_provider", "Liquidity Provider"),
                    ("event_reactive", "Event Reactive"),
                ],
                default="noise",
                max_length=20,
            ),
        ),
    ]
