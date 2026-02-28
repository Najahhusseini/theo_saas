from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text, TIMESTAMP
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Hotel(Base):
    __tablename__ = "hotels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    subscription_plan = Column(String)

    users = relationship("User", back_populates="hotel")
    room_types = relationship("RoomType", back_populates="hotel")
    booking_requests = relationship("BookingRequest", back_populates="hotel")
    ai_draft_email = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String)

    hotel_id = Column(Integer, ForeignKey("hotels.id"))
    hotel = relationship("Hotel", back_populates="users")


class RoomType(Base):
    __tablename__ = "room_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    total_rooms = Column(Integer, nullable=False)

    hotel_id = Column(Integer, ForeignKey("hotels.id"))
    hotel = relationship("Hotel", back_populates="room_types")


class BookingRequest(Base):
    __tablename__ = "booking_requests"

    id = Column(Integer, primary_key=True, index=True)

    guest_name = Column(String)
    email = Column(String)

    arrival_date = Column(Date, nullable=False)
    departure_date = Column(Date, nullable=False)

    room_type = Column(String, nullable=False)
    number_of_rooms = Column(Integer, default=1)
    number_of_guests = Column(Integer)
    special_requests = Column(Text)

    status = Column(String, default="Pending")
    raw_email = Column(Text)

    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    hotel_id = Column(Integer, ForeignKey("hotels.id"))
    hotel = relationship("Hotel", back_populates="booking_requests")
    draft_reply = Column(Text)

class ConfirmedBooking(Base):
    __tablename__ = "confirmed_bookings"

    id = Column(Integer, primary_key=True, index=True)

    booking_request_id = Column(Integer)
    hotel_id = Column(Integer)

    guest_name = Column(String)
    email = Column(String)
    arrival_date = Column(Date)
    departure_date = Column(Date)
    room_type = Column(String)

    number_of_rooms = Column(Integer)
    number_of_guests = Column(Integer)

    special_requests = Column(String)
    # 🔥 AI Draft Email Storage
    ai_draft_email = Column(Text, nullable=True)
    
