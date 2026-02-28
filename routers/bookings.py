from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import models
from services.telegram import send_booking_to_manager
import os
from database import get_db
from auth import get_current_user
from schemas import BookingCreate, BookingResponse
from services.availability import check_room_availability
from fastapi import Path
from services.telegram import send_telegram_message
from services.ai_drafts import generate_reply_draft
from models import BookingRequest, ConfirmedBooking
from fastapi import HTTPException
router = APIRouter(prefix="/booking-requests", tags=["Booking Requests"])


@router.patch("/{request_id}/decision")
def manager_decision(
    request_id: int = Path(...),
    decision: str = "Confirm",  # Confirm / Reject / Waitlist
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):

    booking = db.query(models.BookingRequest).filter(
        models.BookingRequest.id == request_id,
        models.BookingRequest.hotel_id == current_user.hotel_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.status = decision

    # 🔥 Generate AI draft reply
    draft = generate_reply_draft(booking, decision)

    # 🔥 Save draft inside booking
    booking.ai_draft_email = draft

    # If Confirm → create ConfirmedBooking
    if decision == "Confirm":

        existing = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.booking_request_id == booking.id
        ).first()

        if existing:
            return {"message": "Booking already confirmed"}

        confirmed = models.ConfirmedBooking(
            booking_request_id=booking.id,
            hotel_id=current_user.hotel_id,
            arrival_date=booking.arrival_date,
            departure_date=booking.departure_date,
            room_type=booking.room_type,
            number_of_rooms=booking.number_of_rooms
        )

        db.add(confirmed)

    db.commit()
    db.refresh(booking)

    # 🔥 Send draft to Telegram WITH buttons
    send_telegram_message(
        chat_id=os.getenv("MANAGER_CHAT_ID"),
        message=(
            f"📧 Draft Reply:\n\n{booking.ai_draft_email}\n\n"
            "Choose next action:"
        ),
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "✏️ Edit Draft", "callback_data": f"edit_{booking.id}"},
                    {"text": "📤 Send Email", "callback_data": f"send_{booking.id}"}
                ]
            ]
        }
    )

    return {"message": "Decision saved and draft sent to Telegram"}


@router.post("/create", response_model=BookingResponse)
def create_booking_request(
    booking: BookingCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):

    # 🔍 Step 1: Check Availability
    available, message = check_room_availability(
        db=db,
        hotel_id=current_user.hotel_id,
        room_type_name=booking.room_type,  # ✅ correct param name
        arrival_date=booking.arrival_date,
        departure_date=booking.departure_date,
        requested_rooms=booking.number_of_rooms  # ✅ correct param name
    )

    status = "Pending"
    if not available:
        status = "Waitlist"

    # 🧠 Step 2: Create Booking Request
    new_request = models.BookingRequest(
        hotel_id=current_user.hotel_id,
        guest_name=booking.guest_name,
        email=booking.email,
        arrival_date=booking.arrival_date,
        departure_date=booking.departure_date,
        room_type=booking.room_type,
        number_of_rooms=booking.number_of_rooms,
        number_of_guests=booking.number_of_guests,
        special_requests=booking.special_requests,
        raw_email=booking.raw_email,
        status=status
    )

    try:
        db.add(new_request)
        db.commit()
        db.refresh(new_request)

        # 🔥 SEND TO TELEGRAM AFTER COMMIT
        send_booking_to_manager(
            chat_id=os.getenv("MANAGER_CHAT_ID"),
            booking=new_request
        )

        return new_request

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Error creating booking request."
        )
    @router.get("/confirmed-bookings")
    def get_confirmed_bookings(db: Session = Depends(get_db)):
       return db.query(ConfirmedBooking).all()
    
@router.put("/booking-requests/{booking_id}/edit-draft")
def edit_draft(booking_id: int, new_draft: str, db: Session = Depends(get_db)):
    
    booking = db.query(BookingRequest).filter(BookingRequest.id == booking_id).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.ai_draft_email = new_draft
    db.commit()
    db.refresh(booking)

    return {
        "message": "Draft updated successfully",
        "updated_draft": booking.ai_draft_email
    }
