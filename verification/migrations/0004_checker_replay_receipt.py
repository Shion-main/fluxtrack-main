import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("verification", "0003_retire_dead_validation_actions"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CheckerReplayReceipt",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("client_uuid", models.UUIDField(unique=True)),
                ("status", models.CharField(max_length=10)),
                ("reason", models.CharField(blank=True, max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("checker", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="checker_replay_receipts",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(
                    fields=["checker", "-created_at"],
                    name="verificatio_checker_13881e_idx")],
            },
        ),
    ]
