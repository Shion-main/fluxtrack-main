"""Apply case-sensitive collation to the two opaque token columns ONLY.

`campus_room.qr_token` and `campus_room.manual_code` must be case-SENSITIVE
(`Latin1_General_100_CS_AS`) so case-variant tokens never collide — a real
security bug if they did. The rest of the DB (emails, codes, names) stays at the
CI database default so faculty emails dedupe.

Why hand-written RunSQL instead of a `db_collation` AlterField:
mssql-django 1.7.3 emits NO SQL for an `AlterField` that only changes
`db_collation` (`sqlmigrate` reports "(no-op)"), so the DB columns would stay
CI while Django state falsely claims CS. See RESEARCH Pitfall 3.

Why DROP CONSTRAINT (not DROP INDEX):
Both columns are NOT NULL + unique, so mssql-django backs them with real
UNIQUE CONSTRAINTS (sys.key_constraints, is_unique_constraint=1, unfiltered) —
NOT the filtered unique indexes used for nullable-unique columns. The
auto-generated constraint names carry a random hash suffix (e.g.
`UQ__campus_r__2254D5983F596FDA`), so the name is discovered dynamically and the
constraint recreated under a deterministic name after the collation change.
`ALTER COLUMN` cannot run while the unique constraint references the column, so
the constraint is dropped first and re-added afterward, reinstating uniqueness.
"""
from django.db import migrations, models

COLLATE = "Latin1_General_100_CS_AS"


def cs_sql(table, col, length):
    """Drop the unique constraint on {col}, recollate it CS, re-add uniqueness."""
    return f"""
DECLARE @ct sysname;
SELECT @ct = kc.name
  FROM sys.key_constraints kc
  JOIN sys.index_columns ic
    ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
  JOIN sys.columns c
    ON c.object_id = ic.object_id AND c.column_id = ic.column_id
 WHERE kc.parent_object_id = OBJECT_ID('{table}')
   AND kc.type = 'UQ'
   AND c.name = '{col}';
IF @ct IS NOT NULL EXEC('ALTER TABLE {table} DROP CONSTRAINT ' + @ct);
ALTER TABLE {table} ALTER COLUMN {col} nvarchar({length}) COLLATE {COLLATE} NOT NULL;
ALTER TABLE {table} ADD CONSTRAINT UQ_{table}_{col} UNIQUE ({col});
"""


REVERSE = "-- non-reversible collation change (tokens must stay case-sensitive)"


class Migration(migrations.Migration):

    dependencies = [
        ("campus", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=cs_sql("campus_room", "qr_token", 64),
            reverse_sql=REVERSE,
            state_operations=[
                migrations.AlterField(
                    model_name="room",
                    name="qr_token",
                    field=models.CharField(
                        max_length=64, unique=True, db_collation=COLLATE
                    ),
                ),
            ],
        ),
        migrations.RunSQL(
            sql=cs_sql("campus_room", "manual_code", 6),
            reverse_sql=REVERSE,
            state_operations=[
                migrations.AlterField(
                    model_name="room",
                    name="manual_code",
                    field=models.CharField(
                        max_length=6, unique=True, db_collation=COLLATE
                    ),
                ),
            ],
        ),
    ]
