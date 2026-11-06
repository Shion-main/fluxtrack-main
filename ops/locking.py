"""One transaction-scoped SQL Server lock for competing attendance allocations.

All protected writers acquire this lock before reading domain rows, so an empty
room or unmaterialized occurrence can be reserved safely. A database application
lock works even when no session/booking row yet exists and survives neither a
rollback nor a disconnected process. Reads/reporting remain concurrent.
"""
from contextlib import contextmanager
from functools import wraps

from django.db import connection, transaction, OperationalError


@contextmanager
def operational_write():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("""
                DECLARE @result int;
                EXEC @result = sp_getapplock
                    @Resource = %s, @LockMode = 'Exclusive',
                    @LockOwner = 'Transaction', @LockTimeout = 10000;
                SELECT @result;
            """, ["fluxtrack:operational-write"])
            result = cursor.fetchone()[0]
            if result < 0:
                raise OperationalError("Could not acquire operational write lock")
        yield


def serialized_write(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with operational_write():
            return fn(*args, **kwargs)
    return wrapped
