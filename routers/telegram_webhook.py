from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from database import get_db
import models
from services.ai_drafts import generate_reply_draft
from services.telegram import send_telegram_message, send_draft_for_approval
import logging
import requests
import os
import json

router = APIRouter()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        # Log raw request for debugging
        body = await request.body()
        logger.info(f"Raw webhook received: {body.decode('utf-8')}")
        
        data = await request.json()
        logger.info(f"Parsed webhook: {json.dumps(data, indent=2)}")
        
        # Handle callback queries (button presses)
        if "callback_query" in data:
            logger.info("Processing callback query")
            return await handle_callback_query(data["callback_query"], db)
        
        # Handle text messages
        elif "message" in data:
            logger.info("Processing text message")
            return await handle_text_message(data["message"], db)
        
        logger.info("Ignoring unknown update type")
        return {"status": "ignored_update"}
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

async def handle_callback_query(callback, db: Session):
    """Handle inline keyboard button presses"""
    try:
        callback_data = callback["data"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        callback_id = callback["id"]
        
        logger.info(f"Processing callback - Action: {callback_data}, Chat: {chat_id}")
        
        # Always answer callback query first (removes loading state on button)
        try:
            answer_url = f"{TELEGRAM_API_URL}/answerCallbackQuery"
            requests.post(answer_url, json={"callback_query_id": callback_id}, timeout=5)
            logger.info("Callback answered successfully")
        except Exception as e:
            logger.error(f"Failed to answer callback: {e}")
        
        # Parse callback data (format: action_bookingId)
        parts = callback_data.split("_")
        if len(parts) != 2:
            logger.error(f"Invalid callback data format: {callback_data}")
            await send_telegram_message(chat_id, "❌ Invalid callback data format.")
            return {"status": "error", "message": "Invalid callback data"}
        
        action, booking_id_str = parts
        
        try:
            booking_id = int(booking_id_str)
        except ValueError:
            logger.error(f"Invalid booking ID: {booking_id_str}")
            await send_telegram_message(chat_id, "❌ Invalid booking ID.")
            return {"status": "error", "message": "Invalid booking ID"}
        
        # Get booking from database
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == booking_id
        ).first()
        
        if not booking:
            logger.error(f"Booking {booking_id} not found")
            await send_telegram_message(chat_id, f"❌ Booking #{booking_id} not found.")
            return {"status": "error", "message": "Booking not found"}
        
        logger.info(f"Found booking #{booking_id} with status: {booking.status}")
        
        # Handle different actions
        if action in ["confirm", "reject", "waitlist"]:
            # Update booking status
            new_status = action.capitalize()
            booking.status = new_status
            db.commit()
            logger.info(f"Updated booking #{booking_id} status to: {new_status}")
            
            # Generate draft reply
            draft = generate_reply_draft(booking, new_status)
            booking.ai_draft_email = draft
            db.commit()
            logger.info(f"Generated draft for booking #{booking_id}")
            
            # Send draft for approval
            await send_draft_for_approval(booking, new_status, draft)
            
            # Update original message to show it was processed
            await edit_message_text(
                chat_id, 
                message_id,
                f"✅ Booking #{booking.id} marked as {new_status}\nDraft generated. Please review above."
            )
        
        elif action == "edit":
            logger.info(f"Processing edit action for booking {booking_id}")
            
            # Put booking in editing mode
            booking.status = "Editing"
            db.commit()
            
            # Send clear instructions to the manager
            current_draft = booking.ai_draft_email or "No draft yet."
            
            instruction_message = (
                f"✏️ **EDITING DRAFT for Booking #{booking.id}**\n\n"
                f"**Current Draft:**\n"
                f"```\n{current_draft}\n```\n\n"
                f"**Instructions:**\n"
                f"1. Type your revised message below\n"
                f"2. Send it as a regular text message\n"
                f"3. I'll update the draft and show you the result\n\n"
                f"*Tip: You can copy the current draft above and modify it*"
            )
            
            await send_telegram_message(chat_id, instruction_message)
            
            # Update original message to show it's in editing mode
            await edit_message_text(
                chat_id,
                message_id,
                f"✏️ **Booking #{booking.id} is now in EDIT MODE**\n\nPlease send your revised draft as a new message."
            )
        
        elif action == "send":
            logger.info(f"Processing send action for booking {booking_id}")
            
            # TODO: Implement actual email sending via Gmail API
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
            logger.info(f"Booking #{booking_id} moved to confirmed bookings")
            
            await send_telegram_message(
                chat_id,
                f"✅ Email sent and booking #{booking.id} confirmed!"
            )
            
            # Update original message
            await edit_message_text(
                chat_id,
                message_id,
                f"✅ **Booking #{booking.id} - Email Sent**\n\nThis booking has been confirmed and the email has been sent."
            )
        
        elif action == "cancel":
            logger.info(f"Processing cancel action for booking {booking_id}")
            
            # Reset status if it was in editing
            if booking.status == "Editing":
                booking.status = "Pending"
                db.commit()
            
            await send_telegram_message(
                chat_id,
                f"❌ Action cancelled for booking #{booking.id}"
            )
            
            await edit_message_text(
                chat_id,
                message_id,
                f"❌ Action cancelled for booking #{booking.id}"
            )
        
        else:
            logger.warning(f"Unknown action: {action}")
            await send_telegram_message(chat_id, f"❌ Unknown action: {action}")
        
        return {"status": "success"}
        
    except Exception as e:
        logger.error(f"Error in handle_callback_query: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

async def handle_text_message(message, db: Session):
    """Handle text messages (for editing drafts)"""
    try:
        if "text" not in message:
            logger.info("Ignoring non-text message")
            return {"status": "ignored_non_text"}
        
        chat_id = message["chat"]["id"]
        text = message["text"]
        message_id = message["message_id"]
        
        logger.info(f"Processing text message from chat {chat_id}: {text[:50]}...")
        
        # Ignore commands
        if text.startswith('/'):
            logger.info(f"Ignoring command: {text}")
            return {"status": "ignored_command"}
        
        # Find booking in editing mode
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.status == "Editing"
        ).first()
        
        if booking:
            logger.info(f"Found booking #{booking.id} in editing mode")
            
            # Update draft
            old_draft = booking.ai_draft_email
            booking.ai_draft_email = text
            booking.status = "Draft_Ready"
            db.commit()
            
            logger.info(f"Draft updated for booking #{booking.id}")
            
            # Send confirmation and ask for next action
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📤 Send Email", "callback_data": f"send_{booking.id}"},
                        {"text": "✏️ Edit Again", "callback_data": f"edit_{booking.id}"}
                    ],
                    [
                        {"text": "❌ Cancel", "callback_data": f"cancel_{booking.id}"}
                    ]
                ]
            }
            
            confirmation_message = (
                f"✅ **Draft Updated for Booking #{booking.id}**\n\n"
                f"**New Draft:**\n"
                f"```\n{text}\n```\n\n"
                f"What would you like to do next?"
            )
            
            await send_telegram_message(
                chat_id,
                confirmation_message,
                reply_markup=keyboard
            )
            
            # Try to delete the user's message to keep chat clean (optional)
            try:
                delete_url = f"{TELEGRAM_API_URL}/deleteMessage"
                requests.post(delete_url, json={
                    "chat_id": chat_id,
                    "message_id": message_id
                }, timeout=5)
            except:
                pass  # Ignore if deletion fails
            
        else:
            logger.info("No booking in editing mode found")
            
            # Check if there are any pending drafts
            pending_count = db.query(models.BookingRequest).filter(
                models.BookingRequest.status == "Draft_Ready"
            ).count()
            
            if pending_count > 0:
                await send_telegram_message(
                    chat_id,
                    f"⚠️ No booking is currently being edited, but you have {pending_count} draft(s) ready to send.\n\nUse the buttons on those messages to send or edit them."
                )
            else:
                await send_telegram_message(
                    chat_id,
                    "⚠️ No booking is currently being edited. Please click 'Edit Draft' on a booking to start editing."
                )
        
        return {"status": "message_processed"}
        
    except Exception as e:
        logger.error(f"Error in handle_text_message: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

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
        logger.info(f"Editing message {message_id} in chat {chat_id}")
        response = requests.post(url, json=payload, timeout=10)
        result = response.json()
        logger.info(f"Edit result: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        return None