from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ops", "0006_term_ownership"),
    ]

    operations = [
        migrations.CreateModel(
            name="SharedCacheEntry",
            fields=[
                ("cache_key", models.CharField(max_length=255, primary_key=True,
                                               serialize=False)),
                ("value", models.TextField()),
                ("expires", models.DateTimeField(db_index=True)),
            ],
            options={"db_table": "fluxtrack_cache"},
        ),
    ]
