from sqlalchemy.orm import Session
from sqlalchemy import and_
import models


def check_room_availability(
    db: Session,
    hotel_id: int,
    room_type_name: str,
    arrival_date,
    departure_date,
    requested_rooms: int,
):

    # 1️⃣ Get total rooms for that type
    room_type = db.query(models.RoomType).filter(
        models.RoomType.hotel_id == hotel_id,
        models.RoomType.name == room_type_name
    ).first()

    if not room_type:
        return False, "Room type not found"

    total_rooms = room_type.total_rooms

    # 2️⃣ Find overlapping confirmed bookings
    overlapping_bookings = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.room_type == room_type_name,
        models.ConfirmedBooking.arrival_date < departure_date,
        models.ConfirmedBooking.departure_date > arrival_date
    ).all()

    # 3️⃣ Sum rooms already booked
    booked_rooms = sum(b.number_of_rooms for b in overlapping_bookings)

    # 4️⃣ Check availability
    if booked_rooms + requested_rooms <= total_rooms:
        return True, "Available"

    return False, "Not enough rooms available"