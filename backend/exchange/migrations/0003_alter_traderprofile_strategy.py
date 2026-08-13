from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exchange", "0002_referenceimportrun_symbol_marketdaily"),
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
                ],
                default="noise",
                max_length=20,
            ),
        ),
    ]
