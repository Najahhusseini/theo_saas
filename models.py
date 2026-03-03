from sqlalchemy import Column, Integer, String, Date, ForeignKey, Text, TIMESTAMP, Boolean
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
    
# Add to models.py

class ModificationRequest(Base):
    """Track modification requests for confirmed bookings"""
    __tablename__ = "modification_requests"

    id = Column(Integer, primary_key=True, index=True)
    
    # Link to original confirmed booking
    original_booking_id = Column(Integer, ForeignKey("confirmed_bookings.id"))
    original_booking = relationship("ConfirmedBooking", back_populates="modifications")
    
    # New requested changes
    guest_name = Column(String)
    email = Column(String)
    arrival_date = Column(Date)
    departure_date = Column(Date)
    room_type = Column(String)
    number_of_rooms = Column(Integer)
    number_of_guests = Column(Integer)
    special_requests = Column(Text)
    
    # Metadata
    status = Column(String, default="Pending")  # Pending, Approved, Rejected
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    raw_email = Column(Text)
    
    # Who processed it
    processed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at = Column(TIMESTAMP, nullable=True)
    
    # Notes
    modification_notes = Column(Text)

class ModificationHistory(Base):
    """Track all changes made to bookings"""
    __tablename__ = "modification_history"
    
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer)  # Can be booking_request_id or confirmed_booking_id
    booking_type = Column(String)  # "request" or "confirmed"
    
    field_name = Column(String)
    old_value = Column(Text)
    new_value = Column(Text)
    
    modified_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    modified_at = Column(TIMESTAMP, default=datetime.utcnow)
    modification_reason = Column(String)  # "guest_request", "manager_update", etc.

# Update ConfirmedBooking to include relationship
class ConfirmedBooking(Base):
    __tablename__ = "confirmed_bookings"
    
    # ... existing fields ...
    
    # Add relationship to modifications
    modifications = relationship("ModificationRequest", back_populates="original_booking")
    
    # Track modification status
    has_pending_modification = Column(Boolean, default=False)
    last_modified_at = Column(TIMESTAMP, nullable=True)