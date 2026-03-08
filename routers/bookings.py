from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import models
from services.telegram import send_booking_to_manager
import os
from database import get_db
from auth import get_current_user
from schemas import BookingCreate, BookingResponse
from services.availability import check_room_availability
from services.telegram import send_telegram_message
from services.ai_drafts import generate_reply_draft
from models import BookingRequest, ConfirmedBooking
import logging
import requests

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/booking-requests", tags=["Booking Requests"])

# Get Telegram config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")


@router.patch("/{request_id}/decision")
def manager_decision(
    request_id: int = Path(...),
    decision: str = "Confirm",
    draft_reply: str = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    logger.info("="*60)
    logger.info("🔍🔍🔍 STARTING DECISION FUNCTION 🔍🔍🔍")
    logger.info(f"STEP 1: Function entered with request_id={request_id}")
    logger.info(f"STEP 2: Raw decision value: '{decision}'")
    logger.info(f"STEP 3: Draft reply present: {bool(draft_reply)}")
    logger.info(f"STEP 4: Current user: {current_user.email}")

    try:
        # STEP 5: Query booking
        logger.info(f"STEP 5: Querying booking with id={request_id}")
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == request_id,
            models.BookingRequest.hotel_id == current_user.hotel_id
        ).first()

        if not booking:
            logger.error(f"STEP 5a: Booking {request_id} not found!")
            raise HTTPException(status_code=404, detail="Booking not found")
        
        logger.info(f"STEP 5b: Found booking for guest: {booking.guest_name}")

        # STEP 6: Clean decision
        decision_clean = decision.strip().lower()
        logger.info(f"STEP 6: Cleaned decision: '{decision_clean}'")

        # STEP 7: Decision mapping
        logger.info("STEP 7: Starting decision mapping...")
        if decision_clean in ["confirm", "confirmed"]:
            final_decision = "confirmed"
            status_text = "Confirmed"
            logger.info(f"STEP 7a: Mapped to CONFIRMED")
        elif decision_clean in ["reject", "rejected"]:
            final_decision = "rejected"
            status_text = "Rejected"
            logger.info(f"STEP 7a: Mapped to REJECTED")
        elif decision_clean in ["waitlist"]:
            final_decision = "waitlist"
            status_text = "Waitlist"
            logger.info(f"STEP 7a: Mapped to WAITLIST")
        else:
            logger.error(f"STEP 7a: Invalid decision: '{decision}'")
            raise HTTPException(status_code=400, detail=f"Invalid decision: {decision}")

        logger.info(f"STEP 7b: Final decision: '{final_decision}' -> Status: '{status_text}'")

        # STEP 8: Update booking
        logger.info(f"STEP 8: Updating booking status to {status_text}")
        booking.status = status_text

        # STEP 9: Handle draft
        logger.info(f"STEP 9: Processing draft reply")
        if draft_reply:
            logger.info(f"STEP 9a: Using provided draft (length: {len(draft_reply)})")
            booking.ai_draft_email = draft_reply
        else:
            logger.info(f"STEP 9b: Generating AI draft")
            booking.ai_draft_email = generate_reply_draft(booking, status_text)

        # STEP 10: Create confirmed booking if needed
        if final_decision == "confirmed":
            logger.info(f"STEP 10: Confirmed decision - checking for existing confirmed booking")
            existing = db.query(models.ConfirmedBooking).filter(
                models.ConfirmedBooking.booking_request_id == booking.id
            ).first()

            if not existing:
                logger.info(f"STEP 10a: Creating new confirmed booking")
                confirmed = models.ConfirmedBooking(
                    booking_request_id=booking.id,
                    hotel_id=current_user.hotel_id,
                    guest_name=booking.guest_name,
                    email=booking.email,
                    arrival_date=booking.arrival_date,
                    departure_date=booking.departure_date,
                    room_type=booking.room_type,
                    number_of_rooms=booking.number_of_rooms,
                    number_of_guests=booking.number_of_guests,
                    special_requests=booking.special_requests,
                    ai_draft_email=booking.ai_draft_email
                )
                db.add(confirmed)
            else:
                logger.info(f"STEP 10b: Confirmed booking already exists")
        else:
            logger.info(f"STEP 10: Not a confirmed decision, skipping confirmed booking creation")

        # STEP 11: Commit to database
        logger.info(f"STEP 11: Committing to database")
        db.commit()
        db.refresh(booking)
        logger.info(f"STEP 11a: Commit successful")

        # STEP 12: Send Telegram notification
        logger.info(f"STEP 12: Checking Telegram config")
        if TELEGRAM_BOT_TOKEN and MANAGER_CHAT_ID:
            logger.info(f"STEP 12a: Telegram configured, sending notification")
            try:
                # Prepare emoji based on decision
                emoji_map = {
                    "confirmed": "✅",
                    "rejected": "❌",
                    "waitlist": "⏳"
                }
                emoji = emoji_map.get(final_decision, "🔄")
                logger.info(f"STEP 12b: Using emoji: {emoji}")

                # Get admin name
                admin_name = current_user.name if hasattr(current_user, 'name') and current_user.name else current_user.email

                # Format dates
                arrival = booking.arrival_date.strftime("%d %b %Y") if hasattr(booking.arrival_date, 'strftime') else str(booking.arrival_date)
                departure = booking.departure_date.strftime("%d %b %Y") if hasattr(booking.departure_date, 'strftime') else str(booking.departure_date)

                # Build message
                message = (
                    f"{emoji} *Booking #{booking.id} {status_text}*\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 *Guest:* {booking.guest_name}\n"
                    f"📧 *Guest Email:* {booking.email}\n"
                    f"📅 *Stay:* {arrival} → {departure}\n"
                    f"🛏 *Room:* {booking.room_type} ({booking.number_of_rooms} room{'s' if booking.number_of_rooms > 1 else ''})\n"
                    f"👥 *Guests:* {booking.number_of_guests}\n"
                )

                if booking.special_requests:
                    message += f"📝 *Requests:* {booking.special_requests}\n"

                message += f"━━━━━━━━━━━━━━━━━━━\n"
                message += f"👨‍💼 *Action by:* {admin_name}\n"

                if booking.ai_draft_email:
                    message += f"\n📨 *Final Email Sent:*\n```\n{booking.ai_draft_email}\n```\n"
                else:
                    message += f"\n*No email drafted.*\n"

                # Send to Telegram
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                payload = {
                    "chat_id": MANAGER_CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {"text": "✏️ Edit Draft", "callback_data": f"edit_{booking.id}"},
                                {"text": "📤 Send Email", "callback_data": f"send_{booking.id}"}
                            ]
                        ]
                    }
                }

                logger.info(f"STEP 12c: Sending Telegram message")
                response = requests.post(url, json=payload, timeout=5)
                if response.status_code == 200:
                    logger.info(f"STEP 12d: ✅ Telegram notification sent")
                else:
                    logger.error(f"STEP 12d: ❌ Telegram failed: {response.text}")

            except Exception as e:
                logger.error(f"STEP 12e: ❌ Telegram error: {e}")
        else:
            logger.warning(f"STEP 12a: Telegram not configured - missing tokens")

        logger.info(f"✅ STEP 13: Function completed successfully")
        
        return {
            "message": f"Booking {status_text} successfully",
            "draft": booking.ai_draft_email
        }

    except HTTPException:
        logger.error(f"❌ HTTPException raised")
        raise
    except Exception as e:
        logger.error(f"❌ STEP ERROR: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/debug-endpoint")
def debug_endpoint():
    """Debug endpoint to see what code is running"""
    import inspect
    import os
    
    # Get the source code of the manager_decision function
    from routers.bookings import manager_decision
    source = inspect.getsource(manager_decision)
    
    return {
        "message": "Debug info",
        "file_path": __file__,
        "function_source": source[:500] + "...",  # First 500 chars
        "environment": dict(os.environ),
    }


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
        room_type_name=booking.room_type,
        arrival_date=booking.arrival_date,
        departure_date=booking.departure_date,
        requested_rooms=booking.number_of_rooms
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
        send_booking_to_manager(new_request)

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


@router.put("/{booking_id}/edit-draft")
def edit_draft(
    booking_id: int,
    draft_reply: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    booking = db.query(BookingRequest).filter(
        BookingRequest.id == booking_id,
        BookingRequest.hotel_id == current_user.hotel_id
    ).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.ai_draft_email = draft_reply
    db.commit()
    db.refresh(booking)

    return {
        "message": "Draft updated successfully",
        "draft": booking.ai_draft_email
    }


@router.post("/{booking_id}/generate-draft")
def generate_draft(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Generate an AI draft reply for a booking"""
    try:
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == booking_id,
            models.BookingRequest.hotel_id == current_user.hotel_id
        ).first()

        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        # Generate draft using your existing AI function
        from services.ai_drafts import generate_reply_draft
        draft = generate_reply_draft(booking, "Confirm")

        # Optionally save it
        booking.ai_draft_email = draft
        db.commit()

        return {"draft": draft}

    except Exception as e:
        logger.error(f"Error generating draft: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{booking_id}/generate-rejection-draft")
def generate_rejection_draft(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Generate an AI rejection draft for a booking"""
    try:
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == booking_id,
            models.BookingRequest.hotel_id == current_user.hotel_id
        ).first()

        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        from services.ai_drafts import generate_reply_draft
        # Generate rejection-specific draft
        draft = generate_reply_draft(booking, "Reject")

        return {"draft": draft}

    except Exception as e:
        logger.error(f"Error generating rejection draft: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    

@router.get("/test-version")
def test_version():
    """Test endpoint to verify the file version"""
    return {
        "status": "This is the FIXED version with correct decision mapping",
        "version": "2.0.1",
        "date": "2026-03-08"
    }


@router.post("/{booking_id}/generate-waitlist-draft")
def generate_waitlist_draft(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Generate an AI waitlist draft for a booking"""
    try:
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == booking_id,
            models.BookingRequest.hotel_id == current_user.hotel_id
        ).first()

        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        from services.ai_drafts import generate_reply_draft
        # Generate waitlist-specific draft
        draft = generate_reply_draft(booking, "Waitlist")

        return {"draft": draft}


    except Exception as e:
        logger.error(f"Error generating waitlist draft: {e}")
        raise HTTPException(status_code=500, detail=str(e))