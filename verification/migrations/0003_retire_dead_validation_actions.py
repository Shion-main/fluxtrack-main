# CHK-03: retire the dead ValidationAction members confirmed_absent and
# confirmed_empty. VERIFIED_EMPTY stays canonical (research Open Q1); Absent is
# final via the JOB-02 sweep (CHK-06). Choices are app-level in this codebase, so
# this is a state-only AlterField - no DDL on MSSQL. A forward RunPython asserts
# no stray rows use the retired values before the choices are removed; the
# reverse is a no-op.

from django.db import migrations, models


def _assert_no_retired_actions(apps, schema_editor):
    CheckerValidation = apps.get_model("verification", "CheckerValidation")
    retired = ["confirmed_absent", "confirmed_empty"]
    stray = CheckerValidation.objects.filter(action__in=retired).count()
    assert stray == 0, (
        "%d CheckerValidation row(s) still use a retired action (%s); "
        "migrate them before removing the choices" % (stray, ", ".join(retired))
    )


def _noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('verification', '0002_assignment_scope'),
    ]

    operations = [
        migrations.RunPython(_assert_no_retired_actions, _noop_reverse),
        migrations.AlterField(
            model_name='checkervalidation',
            name='action',
            field=models.CharField(
                choices=[
                    ('verified', 'Verified'),
                    ('flag_identity_mismatch', 'Flag: identity mismatch'),
                    ('flag_not_present', 'Flag: not present'),
                    ('verified_empty', 'Verified empty'),
                ],
                max_length=25,
            ),
        ),
    ]
