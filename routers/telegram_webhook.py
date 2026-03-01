from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
from services.ai_drafts import generate_reply_draft
from services.telegram import send_telegram_message, send_draft_for_approval
import logging
import requests
import os

router = APIRouter()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        logger.info(f"Received webhook: {data}")
        
        # Handle callback queries (button presses)
        if "callback_query" in data:
            return await handle_callback_query(data["callback_query"], db)
        
        # Handle text messages
        elif "message" in data:
            return await handle_text_message(data["message"], db)
        
        return {"status": "ignored_update"}
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return {"status": "error", "message": str(e)}

async def handle_callback_query(callback, db: Session):
    """Handle inline keyboard button presses"""
    callback_data = callback["data"]
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"]["message_id"]
    callback_id = callback["id"]
    
    # Always answer callback query first (prevents loading state on button)
    try:
        requests.post(
            f"{TELEGRAM_API_URL}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
            timeout=5
        )
    except Exception as e:
        logger.error(f"Failed to answer callback: {e}")
    
    # Parse callback data (format: action_bookingId)
    parts = callback_data.split("_")
    if len(parts) != 2:
        logger.error(f"Invalid callback data: {callback_data}")
        return {"status": "error", "message": "Invalid callback data"}
    
    action, booking_id_str = parts
    
    try:
        booking_id = int(booking_id_str)
    except ValueError:
        logger.error(f"Invalid booking ID: {booking_id_str}")
        return {"status": "error", "message": "Invalid booking ID"}
    
    # Get booking from database
    booking = db.query(models.BookingRequest).filter(
        models.BookingRequest.id == booking_id
    ).first()
    
    if not booking:
        await send_telegram_message(chat_id, "❌ Booking not found.")
        return {"status": "error", "message": "Booking not found"}
    
    # Handle different actions
    if action in ["confirm", "reject", "waitlist"]:
        # Update booking status
        booking.status = action.capitalize()
        db.commit()
        
        # Generate draft reply
        draft = generate_reply_draft(booking, action.capitalize())
        booking.ai_draft_email = draft
        db.commit()
        
        # Send draft for approval
        await send_draft_for_approval(booking, action.capitalize(), draft)
        
        # Update original message to show it was processed
        await edit_message_text(
            chat_id, 
            message_id,
            f"✅ Booking #{booking.id} marked as {action.capitalize()}\nDraft generated. Please review above."
        )
    
    elif action == "edit":
        # Put booking in editing mode
        booking.status = "Editing"
        db.commit()
        
        await send_telegram_message(
            chat_id,
            f"✏️ Send the updated draft message for booking #{booking.id} now.\nCurrent draft:\n\n{booking.ai_draft_email}"
        )
    
    elif action == "send":
        # TODO: Implement email sending via Gmail API
        booking.status = "Email_Sent"
        db.commit()
        
        # Move to confirmed bookings
        confirmed_booking = models.ConfirmedBooking(
            booking_request_id=booking.id,
            hotel_id=booking.hotel_id,
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
        db.add(confirmed_booking)
        db.commit()
        
        await send_telegram_message(
            chat_id,
            f"✅ Email sent and booking #{booking.id} confirmed!"
        )
    
    elif action == "cancel":
        await send_telegram_message(
            chat_id,
            f"❌ Action cancelled for booking #{booking.id}"
        )
    
    return {"status": "success"}

async def handle_text_message(message, db: Session):
    """Handle text messages (for editing drafts)"""
    if "text" not in message:
        return {"status": "ignored_non_text"}
    
    chat_id = message["chat"]["id"]
    text = message["text"]
    
    # Check if this is a reply to a message (for editing drafts)
    reply_to = message.get("reply_to_message")
    
    # Find booking in editing mode
    booking = db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Editing"
    ).first()
    
    if booking:
        # Update draft
        booking.ai_draft_email = text
        booking.status = "Draft_Ready"  # New status
        db.commit()
        
        # Send confirmation and ask for next action
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📤 Send Email", "callback_data": f"send_{booking.id}"},
                    {"text": "✏️ Edit Again", "callback_data": f"edit_{booking.id}"}
                ]
            ]
        }
        
        await send_telegram_message(
            chat_id,
            f"✅ Draft updated for booking #{booking.id}\n\nNew draft:\n{text}",
            reply_markup=keyboard
        )
    else:
        await send_telegram_message(
            chat_id, 
            "⚠️ No booking is currently being edited. Use the buttons to manage bookings."
        )
    
    return {"status": "message_processed"}

async def edit_message_text(chat_id: int, message_id: int, text: str):
    """Helper to edit a Telegram message"""
    url = f"{TELEGRAM_API_URL}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        return None