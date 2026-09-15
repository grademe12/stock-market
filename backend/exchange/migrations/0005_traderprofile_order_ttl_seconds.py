from django.db import migrations, models


def convert_ttl_ticks_to_seconds(apps, schema_editor) -> None:
    TraderProfile = apps.get_model("exchange", "TraderProfile")
    for profile in TraderProfile.objects.all().iterator():
        profile.order_ttl_seconds = profile.order_ttl_seconds * 8
        profile.save(update_fields=["order_ttl_seconds"])


class Migration(migrations.Migration):
    dependencies = [
        ("exchange", "0004_alter_traderprofile_strategy"),
    ]

    operations = [
        migrations.RenameField(
            model_name="traderprofile",
            old_name="order_ttl_ticks",
            new_name="order_ttl_seconds",
        ),
        migrations.AlterField(
            model_name="traderprofile",
            name="order_ttl_seconds",
            field=models.PositiveIntegerField(default=16),
        ),
        migrations.RunPython(convert_ttl_ticks_to_seconds, migrations.RunPython.noop),
    ]
