from pydantic import BaseModel
from datetime import date
from typing import Optional


# ------------------------
# BOOKING REQUEST CREATE
# ------------------------
class BookingCreate(BaseModel):
    guest_name: str
    email: str
    arrival_date: date
    departure_date: date
    room_type: str
    number_of_rooms: int
    number_of_guests: Optional[int] = None
    special_requests: Optional[str] = None
    raw_email: Optional[str] = None


# ------------------------
# BOOKING RESPONSE
# ------------------------
class BookingResponse(BookingCreate):
    id: int
    hotel_id: int
    status: str

    class Config:
        from_attributes = True  # 🔥 Pydantic v2 replacement for orm_mode