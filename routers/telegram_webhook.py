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
import re
from datetime import date

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
        
        # Handle special actions without booking IDs (stats, today, pending, help)
        if callback_data in ["stats", "today", "pending", "help"]:
            if callback_data == "stats":
                await handle_stats_command(chat_id, db)
            elif callback_data == "today":
                await handle_today_command(chat_id, db)
            elif callback_data == "pending":
                await handle_pending_command(chat_id, db)
            elif callback_data == "help":
                await handle_help_command(chat_id)
            return {"status": "success"}
        
        # Parse callback data with booking ID (format: action_bookingId)
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
            booking.draft_reply = draft
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
            current_draft = booking.draft_reply or "No draft yet."
            
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
            
            # Move to confirmed bookings - MAP draft_reply TO ai_draft_email
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
                ai_draft_email=booking.draft_reply
            )
            db.add(confirmed_booking)
            db.commit()
            logger.info(f"Booking #{booking_id} moved to confirmed bookings with ai_draft_email={booking.draft_reply}")
            
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
        
        elif action == "details":
            logger.info(f"Processing details action for booking {booking_id}")
            
            details_message = (
                f"📋 **Booking #{booking.id} Details**\n\n"
                f"**Guest:** {booking.guest_name}\n"
                f"**Email:** {booking.email}\n"
                f"**Room:** {booking.room_type}\n"
                f"**Arrival:** {booking.arrival_date}\n"
                f"**Departure:** {booking.departure_date}\n"
                f"**Rooms:** {booking.number_of_rooms}\n"
                f"**Guests:** {booking.number_of_guests}\n"
                f"**Status:** {booking.status}\n"
                f"**Created:** {booking.created_at}\n\n"
                f"**Special Requests:**\n{booking.special_requests or 'None'}\n\n"
                f"**Current Draft:**\n```\n{booking.draft_reply or 'No draft yet'}\n```"
            )
            
            await send_telegram_message(chat_id, details_message)
        
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
    """Handle text messages (for editing drafts and answering questions)"""
    try:
        if "text" not in message:
            logger.info("Ignoring non-text message")
            return {"status": "ignored_non_text"}
        
        chat_id = message["chat"]["id"]
        text = message["text"]
        message_id = message["message_id"]
        
        logger.info(f"Processing text message from chat {chat_id}: {text[:50]}...")
        
        # Handle commands (starting with /)
        if text.startswith('/'):
            logger.info(f"Processing command: {text}")
            
            if text == '/stats':
                await handle_stats_command(chat_id, db)
                return {"status": "command_processed"}
            
            elif text == '/today':
                await handle_today_command(chat_id, db)
                return {"status": "command_processed"}
            
            elif text == '/pending':
                await handle_pending_command(chat_id, db)
                return {"status": "command_processed"}
            
            elif text == '/help':
                await handle_help_command(chat_id)
                return {"status": "command_processed"}
            
            else:
                await send_telegram_message(
                    chat_id, 
                    f"❌ Unknown command: {text}\n\nType /help for available commands."
                )
                return {"status": "command_processed"}
        
        # Check if this is a reply to a specific message (for editing)
        reply_to_message = message.get("reply_to_message")
        
        # Try to find a booking in editing mode
        booking = None
        
        if reply_to_message:
            # If it's a reply, try to extract booking ID from the replied message
            reply_text = reply_to_message.get("text", "")
            match = re.search(r'Booking #(\d+)', reply_text)
            if match:
                booking_id = int(match.group(1))
                booking = db.query(models.BookingRequest).filter(
                    models.BookingRequest.id == booking_id,
                    models.BookingRequest.status == "Editing"
                ).first()
                if booking:
                    logger.info(f"Found booking #{booking_id} from reply context")
        
        if not booking:
            # Fallback: find any booking in editing mode
            booking = db.query(models.BookingRequest).filter(
                models.BookingRequest.status == "Editing"
            ).first()
            if booking:
                logger.warning(f"Found booking #{booking.id} in editing mode (no reply context)")
        
        if booking:
            # We have a booking to edit
            logger.info(f"Processing edit for booking #{booking.id}")
            
            # Update the draft
            old_draft = booking.draft_reply
            booking.draft_reply = text
            booking.status = "Draft_Ready"
            db.commit()
            
            logger.info(f"Draft updated for booking #{booking.id}")
            
            # Send confirmation with action buttons
            keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "📤 Send Email", "callback_data": f"send_{booking.id}"},
                        {"text": "✏️ Edit Again", "callback_data": f"edit_{booking.id}"}
                    ],
                    [
                        {"text": "❌ Cancel", "callback_data": f"cancel_{booking.id}"},
                        {"text": "📋 Details", "callback_data": f"details_{booking.id}"}
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
            
            # Try to delete the user's message to keep chat clean
            try:
                delete_url = f"{TELEGRAM_API_URL}/deleteMessage"
                requests.post(delete_url, json={
                    "chat_id": chat_id,
                    "message_id": message_id
                }, timeout=5)
            except:
                pass  # Ignore if deletion fails
        
        else:
            # No booking in editing mode - treat as a question
            logger.info("No booking in editing mode, handling as question")
            await handle_manager_question(chat_id, text, db)
        
        return {"status": "message_processed"}
        
    except Exception as e:
        logger.error(f"Error in handle_text_message: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

async def handle_manager_question(chat_id: int, question: str, db: Session):
    """Handle manager questions with predefined answers"""
    
    # Predefined Q&A database
    qa_pairs = [
        {
            "keywords": ["availability", "available", "free room", "vacancy"],
            "answer": "To check availability, please:\n1. Go to the dashboard\n2. Check room types and dates\n3. Or use the availability feature in the admin panel"
        },
        {
            "keywords": ["price", "cost", "rate", "how much"],
            "answer": "Room rates vary by season and room type. Please check the rate card in the dashboard or contact revenue management."
        },
        {
            "keywords": ["cancel", "cancellation", "refund"],
            "answer": "Cancellation policy:\n- Free cancellation up to 24 hours before arrival\n- Late cancellation: 1 night charge\n- No-show: Full stay charge"
        },
        {
            "keywords": ["check in", "check-in", "checkin", "arrival"],
            "answer": "Check-in time: 3:00 PM\nEarly check-in subject to availability.\nYou can request early check-in in special requests."
        },
        {
            "keywords": ["check out", "check-out", "checkout", "departure"],
            "answer": "Check-out time: 11:00 AM\nLate check-out subject to availability (additional charges may apply)."
        },
        {
            "keywords": ["parking", "car", "vehicle"],
            "answer": "Parking: Free for hotel guests. Limited spaces available on first-come basis."
        },
        {
            "keywords": ["breakfast", "food", "restaurant", "meal"],
            "answer": "Breakfast: Served 7:00 AM - 10:30 AM\nIncluded in most room rates. Additional charge: $15/person"
        },
        {
            "keywords": ["wifi", "internet", "network"],
            "answer": "Free high-speed WiFi available throughout the hotel. Password: welcome123"
        },
        {
            "keywords": ["pool", "gym", "facilities"],
            "answer": "Hotel facilities:\n- Swimming pool (6 AM - 10 PM)\n- Fitness center (24/7)\n- Spa (9 AM - 8 PM, by appointment)"
        },
        {
            "keywords": ["pet", "dog", "animal"],
            "answer": "Pet policy: Small pets allowed (under 15kg) with additional cleaning fee of $25/night."
        },
        {
            "keywords": ["help", "support", "contact"],
            "answer": "Need help? Contact:\n- Front Desk: 1234\n- Manager: manager@hotel.com\n- Emergency: +1 234 567 890"
        }
    ]
    
    # Convert question to lowercase for matching
    question_lower = question.lower()
    
    # Check for matches
    matched_answers = []
    for qa in qa_pairs:
        for keyword in qa["keywords"]:
            if keyword in question_lower:
                matched_answers.append(qa["answer"])
                break
    
    if matched_answers:
        # Remove duplicates and send
        unique_answers = list(dict.fromkeys(matched_answers))
        response = "📚 **Quick Answer:**\n\n" + "\n\n---\n\n".join(unique_answers)
        
        # Add suggestion to check bookings
        response += "\n\n💡 **Tip:** Use buttons on booking messages to manage specific reservations."
    else:
        # No match found
        response = (
            "🤔 I'm not sure about that. Here's what I can help with:\n\n"
            "• Booking status and management\n"
            "• Hotel policies (cancellation, check-in/out)\n"
            "• Facilities (parking, breakfast, wifi)\n"
            "• General hotel information\n\n"
            "Try asking about specific topics or use the buttons on booking messages."
        )
    
    # Add helpful keyboard
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 Stats", "callback_data": "stats"},
                {"text": "📅 Today", "callback_data": "today"}
            ],
            [
                {"text": "⏳ Pending", "callback_data": "pending"},
                {"text": "❓ Help", "callback_data": "help"}
            ]
        ]
    }
    
    await send_telegram_message(chat_id, response, reply_markup=keyboard)

async def handle_stats_command(chat_id: int, db: Session):
    """Handle /stats command"""
    total = db.query(models.BookingRequest).count()
    pending = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Pending").count()
    confirmed = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Confirmed").count()
    waitlist = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Waitlist").count()
    draft_ready = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Draft_Ready").count()
    
    message = (
        f"📊 **Booking Statistics**\n\n"
        f"Total: {total}\n"
        f"⏳ Pending: {pending}\n"
        f"✅ Confirmed: {confirmed}\n"
        f"⏱ Waitlist: {waitlist}\n"
        f"📝 Draft Ready: {draft_ready}"
    )
    
    await send_telegram_message(chat_id, message)

async def handle_today_command(chat_id: int, db: Session):
    """Handle /today command"""
    today = date.today()
    
    arrivals = db.query(models.BookingRequest).filter(
        models.BookingRequest.arrival_date == today
    ).all()
    
    if arrivals:
        message = f"📅 **Today's Arrivals ({today})**\n\n"
        for b in arrivals:
            message += f"• #{b.id}: {b.guest_name} - {b.room_type} ({b.number_of_guests} guests)\n"
    else:
        message = f"📅 No arrivals scheduled for today ({today})"
    
    await send_telegram_message(chat_id, message)

async def handle_pending_command(chat_id: int, db: Session):
    """Handle /pending command"""
    pending = db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Pending"
    ).all()
    
    if pending:
        message = "⏳ **Pending Bookings**\n\n"
        for b in pending[:10]:  # Show first 10
            message += f"• #{b.id}: {b.guest_name} - {b.room_type} ({b.arrival_date})\n"
        if len(pending) > 10:
            message += f"\n... and {len(pending) - 10} more"
    else:
        message = "✅ No pending bookings!"
    
    await send_telegram_message(chat_id, message)

async def handle_help_command(chat_id: int):
    """Handle /help command"""
    message = (
        "🤖 **THeO Bot Help**\n\n"
        "**Commands:**\n"
        "/stats - View booking statistics\n"
        "/today - See today's arrivals\n"
        "/pending - List pending bookings\n"
        "/help - Show this message\n\n"
        "**Booking Management:**\n"
        "• Click buttons on booking messages\n"
        "• Reply to a draft to edit it\n"
        "• Ask questions about hotel policies\n\n"
        "**Sample Questions:**\n"
        "• \"What's the check-in time?\"\n"
        "• \"Do you have parking?\"\n"
        "• \"Cancellation policy?\"\n"
        "• \"Breakfast included?\""
    )
    
    await send_telegram_message(chat_id, message)

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