# IFO-06: additive scope field on Assignment (FLOOR default / ONLINE).
# Nullable/defaulted AddField - proven additive MSSQL pattern (Phase-1 azure_oid).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('verification', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='assignment',
            name='scope',
            field=models.CharField(
                choices=[('floor', 'Floor'), ('online', 'Online')],
                default='floor', max_length=10,
            ),
        ),
    ]
