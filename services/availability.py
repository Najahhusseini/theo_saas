from sqlalchemy.orm import Session
from sqlalchemy import and_
import models
from datetime import date, timedelta
from typing import Dict, List, Optional

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


def get_daily_occupancy(
    db: Session,
    hotel_id: int,
    start_date: date,
    end_date: date
) -> Dict[str, Dict[str, Dict]]:
    """
    Returns a dictionary with dates as keys, each containing room type occupancy data.
    """
    # Get all room types for this hotel
    room_types = db.query(models.RoomType).filter(
        models.RoomType.hotel_id == hotel_id
    ).all()
    if not room_types:
        return {}

    # Get all confirmed bookings that overlap the date range
    bookings = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.arrival_date <= end_date,
        models.ConfirmedBooking.departure_date >= start_date
    ).all()

    # Prepare a list of dates in the range
    delta = (end_date - start_date).days + 1
    dates = [start_date + timedelta(days=i) for i in range(delta)]

    result = {}
    for d in dates:
        day_data = {}
        for rt in room_types:
            # Count bookings that cover this date
            booked_rooms = 0
            total_guests = 0
            for b in bookings:
                if b.room_type == rt.name and b.arrival_date <= d < b.departure_date:
                    booked_rooms += b.number_of_rooms
                    total_guests += b.number_of_guests
            day_data[rt.name] = {
                "booked": booked_rooms,
                "total": rt.total_rooms,
                "available": rt.total_rooms - booked_rooms,
                "guests": total_guests
            }
        result[d.isoformat()] = day_data
    return result


def check_availability(
    db: Session,
    hotel_id: int,
    check_date: date,
    room_type: Optional[str] = None
) -> Dict:
    """
    Returns availability for a single date, optionally filtered by room type.
    """
    occupancy = get_daily_occupancy(db, hotel_id, check_date, check_date)
    day_data = occupancy.get(check_date.isoformat(), {})
    if room_type:
        return {room_type: day_data.get(room_type, {})} if room_type in day_data else {}
    return day_data


def get_booking_summary(
    db: Session,
    hotel_id: int,
    start_date: date,
    end_date: date
) -> List[Dict]:
    """
    Returns a list of bookings within the date range with key details.
    """
    bookings = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.arrival_date <= end_date,
        models.ConfirmedBooking.departure_date >= start_date
    ).order_by(models.ConfirmedBooking.arrival_date).all()

    summary = []
    for b in bookings:
        summary.append({
            "id": b.id,
            "guest": b.guest_name,
            "email": b.email,
            "arrival": b.arrival_date.isoformat(),
            "departure": b.departure_date.isoformat(),
            "room_type": b.room_type,
            "rooms": b.number_of_rooms,
            "guests": b.number_of_guests,
            "special_requests": b.special_requests
        })
    return summary