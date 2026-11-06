"""Transactional booking allocation and evidence."""
from campus.models import Room
from ops.availability import room_is_free
from ops.locking import serialized_write
from ops.models import AuditLog, Booking


@serialized_write
def create_booking(*, room, actor, occupant_name, purpose, start, end):
    room = Room.objects.get(pk=room.pk)
    if end <= start or not room_is_free(room, start, end):
        raise ValueError(f"{room.code} is not free for that window.")
    booking = Booking.objects.create(room=room, created_by=actor,
        occupant_name=occupant_name, purpose=purpose, start_datetime=start,
        end_datetime=end, status="active")
    AuditLog.objects.create(actor=actor, event_type="booking.created",
        target_type="booking", target_id=str(booking.pk),
        payload={"room": room.code, "occupant": occupant_name,
                 "start": start.isoformat(), "end": end.isoformat()})
    return booking
