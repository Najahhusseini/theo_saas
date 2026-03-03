from services.templates import (
    booking_details_template, 
    stats_template, 
    today_template,
    help_template
)
from services.telegram import send_stats_dashboard, send_today_summary
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
from datetime import date, datetime, timedelta

# Add these helper functions after your imports
def get_mode_indicator(chat_id: int, db: Session) -> str:
    """Get the current mode indicator for a chat"""
    # Check if any booking is in editing mode
    editing_booking = db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Editing"
    ).first()
    
    if editing_booking:
        return f"✏️ *EDITING MODE* - Editing Booking #{editing_booking.id}\nReply to this message with your revised draft.\nType /cancel to exit."
    else:
        return "💬 *Normal Mode* - Use commands or buttons to manage bookings."

def is_editing_mode(db: Session) -> bool:
    """Check if any booking is in editing mode"""
    return db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Editing"
    ).first() is not None

def get_editing_booking(db: Session):
    """Get the booking currently in editing mode"""
    return db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Editing"
    ).first()


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
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    # ALWAYS log everything
    print("="*50)
    print("WEBHOOK RECEIVED!")
    print("="*50)
    
    try:
        # Log raw request for debugging
        body = await request.body()
        print(f"RAW BODY: {body.decode('utf-8')}")
        logger.info(f"Raw webhook received: {body.decode('utf-8')}")
        
        data = await request.json()
        print(f"PARSED JSON: {json.dumps(data, indent=2)}")
        logger.info(f"Parsed webhook: {json.dumps(data, indent=2)}")
        
        # Handle callback queries (button presses)
        if "callback_query" in data:
            print("✅ Processing callback query")
            logger.info("Processing callback query")
            return await handle_callback_query(data["callback_query"], db)
        
        # Handle text messages
        elif "message" in data:
            print("✅ Processing text message")
            logger.info("Processing text message")
            return await handle_text_message(data["message"], db)
        
        print("❌ Ignoring unknown update type")
        logger.info("Ignoring unknown update type")
        return {"status": "ignored_update"}
    
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

# ==================== MODIFICATION ACTIONS ====================
# Define this BEFORE handle_callback_query
async def handle_modification_actions(action: str, modification_id: int, chat_id: int, message_id: int, db: Session):
    """Handle modification-related callback actions"""
    
    if action == "mod_approve":
        logger.info(f"Processing modification approve for modification {modification_id}")
        
        # Get modification
        modification = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.id == modification_id
        ).first()
        
        if not modification:
            await send_telegram_message(chat_id, f"❌ Modification #{modification_id} not found.")
            return {"status": "error"}
        
        if modification.status != "Pending":
            await send_telegram_message(chat_id, f"❌ Modification already {modification.status}")
            return {"status": "error"}
        
        # Get original booking
        original = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.id == modification.original_booking_id
        ).first()
        
        if not original:
            await send_telegram_message(chat_id, f"❌ Original booking not found.")
            return {"status": "error"}
        
        # Track changes
        changes = []
        
        # Apply changes
        if modification.guest_name != original.guest_name:
            changes.append(("Guest Name", original.guest_name, modification.guest_name))
            original.guest_name = modification.guest_name
        
        if modification.email != original.email:
            changes.append(("Email", original.email, modification.email))
            original.email = modification.email
        
        if modification.arrival_date != original.arrival_date:
            changes.append(("Check-in", str(original.arrival_date), str(modification.arrival_date)))
            original.arrival_date = modification.arrival_date
        
        if modification.departure_date != original.departure_date:
            changes.append(("Check-out", str(original.departure_date), str(modification.departure_date)))
            original.departure_date = modification.departure_date
        
        if modification.room_type != original.room_type:
            changes.append(("Room Type", original.room_type, modification.room_type))
            original.room_type = modification.room_type
        
        if modification.number_of_rooms != original.number_of_rooms:
            changes.append(("Rooms", str(original.number_of_rooms), str(modification.number_of_rooms)))
            original.number_of_rooms = modification.number_of_rooms
        
        if modification.number_of_guests != original.number_of_guests:
            changes.append(("Guests", str(original.number_of_guests), str(modification.number_of_guests)))
            original.number_of_guests = modification.number_of_guests
        
        if modification.special_requests != original.special_requests:
            changes.append(("Special Requests", original.special_requests or "None", modification.special_requests or "None"))
            original.special_requests = modification.special_requests
        
        # Update modification status
        modification.status = "Approved"
        modification.processed_at = datetime.utcnow()
        
        # Clear pending flag
        original.has_pending_modification = False
        original.last_modified_at = datetime.utcnow()
        
        db.commit()
        
        # Log changes to history
        for field, old, new in changes:
            history = models.ModificationHistory(
                booking_id=original.id,
                booking_type="confirmed",
                field_name=field,
                old_value=str(old) if old else None,
                new_value=str(new) if new else None,
                modified_at=datetime.utcnow(),
                modification_reason="guest_request"
            )
            db.add(history)
        
        db.commit()
        
        # Send confirmation
        if changes:
            changes_text = "\n".join([f"• {c[0]}: {c[1]} → {c[2]}" for c in changes])
            
            await send_telegram_message(
                chat_id,
                f"✅ *Modification Approved*\n\n"
                f"Booking #{original.id} has been updated.\n\n"
                f"*Changes applied:*\n{changes_text}"
            )
        else:
            await send_telegram_message(
                chat_id,
                f"✅ *Modification Approved*\n\nModification #{modification_id} for Booking #{original.id} was approved with no changes."
            )
        
        # Update the original message
        await edit_message_text(
            chat_id,
            message_id,
            f"✅ *Modification #{modification.id} APPROVED*\n\n{len(changes)} changes applied to Booking #{original.id}"
        )
    
    elif action == "mod_reject":
        logger.info(f"Processing modification reject for modification {modification_id}")
        
        # Get modification
        modification = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.id == modification_id
        ).first()
        
        if not modification:
            await send_telegram_message(chat_id, f"❌ Modification #{modification_id} not found.")
            return {"status": "error"}
        
        # Ask for rejection reason
        await send_telegram_message(
            chat_id,
            f"❓ *Reason for Rejection*\n\nPlease reply with the reason for rejecting modification #{modification.id}",
            reply_markup={
                "force_reply": True,
                "input_field_placeholder": "Enter rejection reason..."
            }
        )
        
        # Store modification ID in a way we can retrieve later
        if not hasattr(handle_modification_actions, "pending_rejections"):
            handle_modification_actions.pending_rejections = {}
        handle_modification_actions.pending_rejections[chat_id] = modification_id
    
    elif action == "mod_details":
        logger.info(f"Processing modification details for modification {modification_id}")
        
        # Get modification
        modification = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.id == modification_id
        ).first()
        
        if not modification:
            await send_telegram_message(chat_id, f"❌ Modification #{modification_id} not found.")
            return {"status": "error"}
        
        # Get original booking
        original = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.id == modification.original_booking_id
        ).first()
        
        # Create comparison
        comparison = f"""
📋 *MODIFICATION DETAILS* #{modification.id}

━━━━━━━━━━━━━━━━━━━

*Field* │ *Original* │ *Requested*
────────┼───────────┼──────────────
👤 Name │ {original.guest_name if original else 'N/A'} │ {modification.guest_name}
📅 In   │ {str(original.arrival_date) if original and original.arrival_date else 'N/A'} │ {str(modification.arrival_date) if modification.arrival_date else 'N/A'}
📅 Out  │ {str(original.departure_date) if original and original.departure_date else 'N/A'} │ {str(modification.departure_date) if modification.departure_date else 'N/A'}
🛏 Room │ {original.room_type if original else 'N/A'} │ {modification.room_type}
🔢 Rooms│ {original.number_of_rooms if original else 'N/A'} │ {modification.number_of_rooms}
👥 Guests│ {original.number_of_guests if original else 'N/A'} │ {modification.number_of_guests}

━━━━━━━━━━━━━━━━━━━

*Special Requests:*\n{modification.special_requests or 'None'}

*Status:* {modification.status}
*Created:* {modification.created_at}
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✅ APPROVE", "callback_data": f"mod_approve_{modification.id}"},
                    {"text": "❌ REJECT", "callback_data": f"mod_reject_{modification.id}"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, comparison, reply_markup=keyboard)
    
    return {"status": "success"}

# ==================== CALLBACK QUERY HANDLER ====================
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
        
        # Handle availability date selection
        if callback_data.startswith("avail_date_"):
            date_str = callback_data.replace("avail_date_", "")
            logger.info(f"📅 Date selected: {date_str}")
            try:
                selected_date = date.fromisoformat(date_str)
                logger.info(f"✅ Parsed date successfully: {selected_date}")
                await show_availability(chat_id, selected_date, db)
            except ValueError as e:
                logger.error(f"❌ Date parsing error: {e}")
                await send_telegram_message(chat_id, f"❌ Invalid date format: {date_str}")
            except Exception as e:
                logger.error(f"❌ Unexpected error in date selection: {e}", exc_info=True)
                await send_telegram_message(chat_id, "❌ Error checking availability.")
            return {"status": "success"}

        elif callback_data == "avail_another":
            logger.info("📅 Checking another date")
            await handle_availability_command(chat_id, "", db)
            return {"status": "success"}

        elif callback_data == "avail_cancel":
            logger.info("❌ Availability check cancelled")
            await send_telegram_message(chat_id, "❌ Availability check cancelled.")
            return {"status": "success"}
        
                # Handle cancellation confirmation
        if callback_data.startswith("cancel_confirm_"):
            booking_id = int(callback_data.replace("cancel_confirm_", ""))
            booking = db.query(models.ConfirmedBooking).filter(models.ConfirmedBooking.id == booking_id).first()
            
            if booking:
                # Delete or mark as cancelled
                # You may need to add a "Cancelled" status to your model
                booking.status = "Cancelled"
                db.commit()
                
                await send_telegram_message(chat_id, f"✅ Booking #{booking_id} has been cancelled.")
                await edit_message_text(chat_id, message_id, f"✅ Booking #{booking_id} CANCELLED")
            else:
                await send_telegram_message(chat_id, f"❌ Booking #{booking_id} not found.")
            return {"status": "success"}

        elif callback_data.startswith("cancel_abort_"):
            booking_id = int(callback_data.replace("cancel_abort_", ""))
            await send_telegram_message(chat_id, f"✅ Cancellation aborted. Booking #{booking_id} remains unchanged.")
            await edit_message_text(chat_id, message_id, f"❌ Cancellation aborted for Booking #{booking_id}")
            return {"status": "success"}
        
        # Handle special actions without booking IDs (stats, today, pending, help)
        if callback_data in ["stats", "today", "pending", "help"]:
            if callback_data == "stats":
                logger.info("Processing stats command from callback")
                
                # Gather comprehensive statistics
                total = db.query(models.BookingRequest).count()
                pending = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Pending").count()
                confirmed = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Confirmed").count()
                waitlist = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Waitlist").count()
                rejected = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Rejected").count()
                draft_ready = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Draft_Ready").count()
                email_sent = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Email_Sent").count()
                
                today = date.today()
                today_arrivals = db.query(models.BookingRequest).filter(
                    models.BookingRequest.arrival_date == today
                ).count()
                today_departures = db.query(models.BookingRequest).filter(
                    models.BookingRequest.departure_date == today
                ).count()
                
                # Calculate response rate
                responded = confirmed + rejected + waitlist
                response_rate = f"{(responded/total*100):.1f}%" if total > 0 else "0%"
                
                stats = {
                    'total': total,
                    'pending': pending,
                    'confirmed': confirmed,
                    'waitlist': waitlist,
                    'rejected': rejected,
                    'draft_ready': draft_ready,
                    'email_sent': email_sent,
                    'today_arrivals': today_arrivals,
                    'today_departures': today_departures,
                    'response_rate': response_rate
                }
                
                # Use the new professional stats dashboard
                await send_stats_dashboard(chat_id, stats)
                
            elif callback_data == "today":
                logger.info("Processing today command from callback")
                
                today = date.today()
                
                arrivals = db.query(models.BookingRequest).filter(
                    models.BookingRequest.arrival_date == today
                ).all()
                
                departures = db.query(models.BookingRequest).filter(
                    models.BookingRequest.departure_date == today
                ).all()
                
                # Use the new professional today summary
                await send_today_summary(chat_id, arrivals, departures)
                
            elif callback_data == "pending":
                logger.info("Processing pending command from callback")
                await handle_pending_command(chat_id, db)
                
            elif callback_data == "help":
                logger.info("Processing help command from callback")
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
        
        # Handle modification actions first (they use modification IDs, not booking IDs)
        if action in ["mod_approve", "mod_reject", "mod_details"]:
            return await handle_modification_actions(action, booking_id, chat_id, message_id, db)
        
        # Get booking from database for regular booking actions
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
            
            # First, check if another booking is already in editing mode
            existing_edit = db.query(models.BookingRequest).filter(
                models.BookingRequest.status == "Editing",
                models.BookingRequest.id != booking_id
            ).first()
            
            if existing_edit:
                # Warn about conflicting edit
                warning_message = (
                    f"⚠️ *Cannot Enter Edit Mode*\n\n"
                    f"Booking #{existing_edit.id} is already being edited.\n\n"
                    f"Please finish editing that booking first or wait for it to timeout."
                )
                await send_telegram_message(chat_id, warning_message)
                return {"status": "error", "message": "Another booking is in editing mode"}
            
            # Put this booking in editing mode
            booking.status = "Editing"
            db.commit()
            
            # Send clear instructions with mode indicator
            current_draft = booking.draft_reply or "No draft yet."
            
            # Create a distinctive editing mode message
            instruction_message = (
                f"✏️ *EDITING MODE ACTIVATED*\n"
                f"{'━' * 25}\n\n"
                f"*Booking #{booking.id} - {booking.guest_name}*\n\n"
                f"*Current Draft:*\n"
                f"```\n{current_draft}\n```\n\n"
                f"*Instructions:*\n"
                f"1️⃣ Reply directly to THIS message\n"
                f"2️⃣ Send your revised draft\n"
                f"3️⃣ I'll update and confirm\n\n"
                f"*Commands in editing mode:*\n"
                f"• /cancel - Exit edit mode\n"
                f"• /help - Show help\n\n"
                f"{'━' * 25}\n"
                f"⏱️ *Edit mode will timeout in 30 minutes*"
            )
            
            # Send with a distinctive reply markup to indicate it's the edit session
            edit_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "❌ CANCEL EDIT", "callback_data": f"cancel_{booking.id}"}
                    ]
                ]
            }
            
            await send_telegram_message(chat_id, instruction_message, reply_markup=edit_keyboard)
            
            # Update original message to show it's in editing mode
            await edit_message_text(
                chat_id,
                message_id,
                f"✏️ **Booking #{booking.id} is now in EDIT MODE**\n\nPlease reply to the edit instruction message above with your revised draft."
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

async def handle_natural_language(chat_id: int, text: str, db: Session):
    """Handle natural language queries"""
    from services.nlp_processor import nlp
    
    logger.info(f"🔍 Processing natural language: {text}")
    
    # Parse the query
    parsed = nlp.parse_query(text)
    logger.info(f"📊 Parsed result: {parsed}")
    
    if parsed['intent'] == 'availability':
        # Handle availability questions
        if parsed['dates']:
            check_date = parsed['dates'][0]
            room_type = parsed.get('room_type')
            
            if room_type:
                await handle_availability_command(chat_id, f"{check_date} {room_type}", db)
            else:
                await show_availability(chat_id, check_date, db)
        else:
            # Default to tomorrow if no date specified
            tomorrow = datetime.now().date() + timedelta(days=1)
            await show_availability(chat_id, tomorrow, db)
    
    elif parsed['intent'] == 'list_bookings':
        # Handle booking listing requests
        if len(parsed['dates']) >= 2:
            start, end = parsed['dates'][0], parsed['dates'][1]
            await handle_bookings_command(chat_id, f"{start} {end}", db)
        elif len(parsed['dates']) == 1:
            # Single date - show bookings for that day
            date = parsed['dates'][0]
            await handle_bookings_command(chat_id, f"{date} {date}", db)
        else:
            # Default to next 7 days
            today = datetime.now().date()
            next_week = today + timedelta(days=7)
            await handle_bookings_command(chat_id, f"{today} {next_week}", db)
    
    elif parsed['intent'] == 'modify_booking':
        # Handle modification requests
        if parsed['booking_id']:
            # Create modification request
            await handle_modify_command(chat_id, str(parsed['booking_id']), db)
        else:
            await send_telegram_message(chat_id, 
                "I can help you modify a booking. Please provide the booking number.\n"
                "Example: `/modify 123` or 'Change booking #123'")
    
    elif parsed['intent'] == 'cancel_booking':
        # Handle cancellation requests
        if parsed['booking_id']:
            # Find the booking
            booking = db.query(models.ConfirmedBooking).filter(
                models.ConfirmedBooking.id == parsed['booking_id']
            ).first()
            
            if booking:
                # Create cancellation message with confirmation buttons
                keyboard = {
                    "inline_keyboard": [
                        [
                            {"text": "✅ Confirm Cancellation", "callback_data": f"cancel_confirm_{booking.id}"},
                            {"text": "❌ No, Keep It", "callback_data": f"cancel_abort_{booking.id}"}
                        ]
                    ]
                }
                
                await send_telegram_message(
                    chat_id,
                    f"⚠️ *Confirm Cancellation*\n\n"
                    f"Are you sure you want to cancel booking #{booking.id} for {booking.guest_name}?\n\n"
                    f"Dates: {booking.arrival_date} to {booking.departure_date}\n"
                    f"Room: {booking.room_type}",
                    reply_markup=keyboard
                )
            else:
                await send_telegram_message(chat_id, f"❌ Booking #{parsed['booking_id']} not found.")
        else:
            await send_telegram_message(chat_id, 
                "To cancel a booking, please provide the booking number.\n"
                "Example: 'Cancel booking #123'")
    
    elif parsed['intent'] == 'guest_count':
        # Handle guest count questions
        if parsed['dates']:
            check_date = parsed['dates'][0]
            
            # Get bookings for that date
            bookings = db.query(models.ConfirmedBooking).filter(
                models.ConfirmedBooking.arrival_date <= check_date,
                models.ConfirmedBooking.departure_date > check_date
            ).all()
            
            total_guests = sum(b.number_of_guests for b in bookings)
            
            await send_telegram_message(
                chat_id,
                f"👥 *Guest Count for {check_date}*\n\n"
                f"Total guests: {total_guests}\n"
                f"Total bookings: {len(bookings)}"
            )
        else:
            # Default to today
            today = datetime.now().date()
            bookings = db.query(models.ConfirmedBooking).filter(
                models.ConfirmedBooking.arrival_date <= today,
                models.ConfirmedBooking.departure_date > today
            ).all()
            
            total_guests = sum(b.number_of_guests for b in bookings)
            
            await send_telegram_message(
                chat_id,
                f"👥 *Guest Count for Today ({today})*\n\n"
                f"Total guests: {total_guests}\n"
                f"Total bookings: {len(bookings)}"
            )
    
    elif parsed['intent'] == 'policy':
        # Handle policy questions
        if 'check-in' in text or 'arrival' in text:
            await send_telegram_message(chat_id,
                "🕒 *Check-in Time*\n\n"
                "Standard check-in: 3:00 PM\n"
                "Early check-in available upon request (subject to availability).")
        elif 'check-out' in text or 'departure' in text:
            await send_telegram_message(chat_id,
                "🕚 *Check-out Time*\n\n"
                "Standard check-out: 11:00 AM\n"
                "Late check-out available for an additional fee.")
        elif 'cancel' in text:
            await send_telegram_message(chat_id,
                "❌ *Cancellation Policy*\n\n"
                "• Free cancellation up to 24 hours before arrival\n"
                "• Late cancellation: 1 night charge\n"
                "• No-show: Full stay charge")
        elif 'parking' in text:
            await send_telegram_message(chat_id,
                "🅿️ *Parking Information*\n\n"
                "Free self-parking for all guests\n"
                "Valet service available for $30/night")
        elif 'breakfast' in text:
            await send_telegram_message(chat_id,
                "🍳 *Breakfast*\n\n"
                "Served 7:00 AM - 10:30 AM\n"
                "Included in most room rates\n"
                "Additional charge: $15/person")
        elif 'wifi' in text:
            await send_telegram_message(chat_id,
                "📶 *WiFi*\n\n"
                "Free high-speed WiFi throughout the hotel\n"
                "Password: welcome123")
        elif 'pet' in text:
            await send_telegram_message(chat_id,
                "🐕 *Pet Policy*\n\n"
                "Small pets allowed (under 15kg)\n"
                "Fee: $25/night\n"
                "Service animals always welcome")
        else:
            await handle_help_command(chat_id)
    
    elif parsed['intent'] == 'question':
        # Handle general questions
        await handle_manager_question(chat_id, text, db)
    
    else:
        # No intent matched
        await send_telegram_message(chat_id,
            "🤔 I'm not sure I understood. Here's what I can help with:\n\n"
            "• Check availability: 'What rooms are free tomorrow?'\n"
            "• List bookings: 'Show bookings for next week'\n"
            "• Modify booking: 'Change booking #123'\n"
            "• Cancel booking: 'Cancel #456'\n"
            "• Guest counts: 'How many guests on Friday?'\n"
            "• Policies: 'Check-in time?' or 'Pet policy?'\n\n"
            "Or type /help to see all commands.")

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
        
        # Handle availability date selection
        if callback_data.startswith("avail_date_"):
            date_str = callback_data.replace("avail_date_", "")
            logger.info(f"📅 Date selected: {date_str}")
            try:
                selected_date = date.fromisoformat(date_str)
                logger.info(f"✅ Parsed date successfully: {selected_date}")
                await show_availability(chat_id, selected_date, db)
            except ValueError as e:
                logger.error(f"❌ Date parsing error: {e}")
                await send_telegram_message(chat_id, f"❌ Invalid date format: {date_str}")
            except Exception as e:
                logger.error(f"❌ Unexpected error in date selection: {e}", exc_info=True)
                await send_telegram_message(chat_id, "❌ Error checking availability.")
            return {"status": "success"}

        elif callback_data == "avail_another":
            logger.info("📅 Checking another date")
            await handle_availability_command(chat_id, "", db)
            return {"status": "success"}

        elif callback_data == "avail_cancel":
            logger.info("❌ Availability check cancelled")
            await send_telegram_message(chat_id, "❌ Availability check cancelled.")
            return {"status": "success"}
        
        # Handle special actions without booking IDs (stats, today, pending, help)
        if callback_data in ["stats", "today", "pending", "help"]:
            if callback_data == "stats":
                logger.info("Processing stats command from callback")
                
                # Gather comprehensive statistics
                total = db.query(models.BookingRequest).count()
                pending = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Pending").count()
                confirmed = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Confirmed").count()
                waitlist = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Waitlist").count()
                rejected = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Rejected").count()
                draft_ready = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Draft_Ready").count()
                email_sent = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Email_Sent").count()
                
                today = date.today()
                today_arrivals = db.query(models.BookingRequest).filter(
                    models.BookingRequest.arrival_date == today
                ).count()
                today_departures = db.query(models.BookingRequest).filter(
                    models.BookingRequest.departure_date == today
                ).count()
                
                # Calculate response rate
                responded = confirmed + rejected + waitlist
                response_rate = f"{(responded/total*100):.1f}%" if total > 0 else "0%"
                
                stats = {
                    'total': total,
                    'pending': pending,
                    'confirmed': confirmed,
                    'waitlist': waitlist,
                    'rejected': rejected,
                    'draft_ready': draft_ready,
                    'email_sent': email_sent,
                    'today_arrivals': today_arrivals,
                    'today_departures': today_departures,
                    'response_rate': response_rate
                }
                
                # Use the new professional stats dashboard
                await send_stats_dashboard(chat_id, stats)
                
            elif callback_data == "today":
                logger.info("Processing today command from callback")
                
                today = date.today()
                
                arrivals = db.query(models.BookingRequest).filter(
                    models.BookingRequest.arrival_date == today
                ).all()
                
                departures = db.query(models.BookingRequest).filter(
                    models.BookingRequest.departure_date == today
                ).all()
                
                # Use the new professional today summary
                await send_today_summary(chat_id, arrivals, departures)
                
            elif callback_data == "pending":
                logger.info("Processing pending command from callback")
                await handle_pending_command(chat_id, db)
                
            elif callback_data == "help":
                logger.info("Processing help command from callback")
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
        
        # Handle modification actions first (they use modification IDs, not booking IDs)
        if action in ["mod_approve", "mod_reject", "mod_details"]:
            return await handle_modification_actions(action, booking_id, chat_id, message_id, db)
        
        # Get booking from database for regular booking actions
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
            
            # First, check if another booking is already in editing mode
            existing_edit = db.query(models.BookingRequest).filter(
                models.BookingRequest.status == "Editing",
                models.BookingRequest.id != booking_id
            ).first()
            
            if existing_edit:
                # Warn about conflicting edit
                warning_message = (
                    f"⚠️ *Cannot Enter Edit Mode*\n\n"
                    f"Booking #{existing_edit.id} is already being edited.\n\n"
                    f"Please finish editing that booking first or wait for it to timeout."
                )
                await send_telegram_message(chat_id, warning_message)
                return {"status": "error", "message": "Another booking is in editing mode"}
            
            # Put this booking in editing mode
            booking.status = "Editing"
            db.commit()
            
            # Send clear instructions with mode indicator
            current_draft = booking.draft_reply or "No draft yet."
            
            # Create a distinctive editing mode message
            instruction_message = (
                f"✏️ *EDITING MODE ACTIVATED*\n"
                f"{'━' * 25}\n\n"
                f"*Booking #{booking.id} - {booking.guest_name}*\n\n"
                f"*Current Draft:*\n"
                f"```\n{current_draft}\n```\n\n"
                f"*Instructions:*\n"
                f"1️⃣ Reply directly to THIS message\n"
                f"2️⃣ Send your revised draft\n"
                f"3️⃣ I'll update and confirm\n\n"
                f"*Commands in editing mode:*\n"
                f"• /cancel - Exit edit mode\n"
                f"• /help - Show help\n\n"
                f"{'━' * 25}\n"
                f"⏱️ *Edit mode will timeout in 30 minutes*"
            )
            
            # Send with a distinctive reply markup to indicate it's the edit session
            edit_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "❌ CANCEL EDIT", "callback_data": f"cancel_{booking.id}"}
                    ]
                ]
            }
            
            await send_telegram_message(chat_id, instruction_message, reply_markup=edit_keyboard)
            
            # Update original message to show it's in editing mode
            await edit_message_text(
                chat_id,
                message_id,
                f"✏️ **Booking #{booking.id} is now in EDIT MODE**\n\nPlease reply to the edit instruction message above with your revised draft."
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
        
        # Check if this is a rejection reason for a modification
        if hasattr(handle_modification_actions, "pending_rejections") and chat_id in handle_modification_actions.pending_rejections:
            modification_id = handle_modification_actions.pending_rejections.pop(chat_id)
            
            # Get modification
            modification = db.query(models.ModificationRequest).filter(
                models.ModificationRequest.id == modification_id
            ).first()
            
            if modification:
                # Update modification status
                modification.status = "Rejected"
                modification.processed_at = datetime.utcnow()
                modification.modification_notes = text
                
                # Clear pending flag on original booking
                original = db.query(models.ConfirmedBooking).filter(
                    models.ConfirmedBooking.id == modification.original_booking_id
                ).first()
                
                if original:
                    original.has_pending_modification = False
                
                db.commit()
                
                await send_telegram_message(
                    chat_id,
                    f"❌ *Modification Rejected*\n\nModification #{modification_id} has been rejected.\nReason: {text}"
                )
                return {"status": "modification_rejected"}
        
        # Check if we're in editing mode
        editing_booking = get_editing_booking(db)
        in_editing_mode = editing_booking is not None
        
        # Handle commands (starting with /)
        if text.startswith('/'):
            logger.info(f"Processing command: {text}")
            
            # Commands available in both modes
            if text == '/help':
                if in_editing_mode:
                    help_msg = (
                        f"✏️ *Help (Editing Mode)*\n\n"
                        f"Currently editing Booking #{editing_booking.id}\n\n"
                        f"*Available commands:*\n"
                        f"• /cancel - Exit edit mode\n"
                        f"• /help - Show this message\n\n"
                        f"*To edit:* Reply with your revised draft"
                    )
                    await send_telegram_message(chat_id, help_msg)
                else:
                    await handle_help_command(chat_id)
                return {"status": "command_processed"}
            
            elif text == '/cancel':
                if in_editing_mode:
                    # Exit edit mode
                    booking = editing_booking
                    booking.status = "Pending"  # Revert to pending
                    db.commit()
                    
                    await send_telegram_message(
                        chat_id,
                        f"✅ *Edit Mode Cancelled*\n\nBooking #{booking.id} has been returned to Pending status.\n\n💬 You are now in normal mode."
                    )
                    logger.info(f"Edit mode cancelled for booking #{booking.id}")
                else:
                    await send_telegram_message(
                        chat_id,
                        "ℹ️ You are not in edit mode. Click 'Edit Draft' on a booking to start editing."
                    )
                return {"status": "command_processed"}
            
            # Commands only available in normal mode
            if in_editing_mode:
                await send_telegram_message(
                    chat_id,
                    f"❌ Command not available in edit mode.\n\nYou are currently editing Booking #{editing_booking.id}.\n\nType /cancel to exit edit mode or /help for available commands."
                )
                return {"status": "command_blocked"}
            
            # Normal mode commands
            if text == '/stats':
                await handle_stats_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/today':
                await handle_today_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/pending':
                await handle_pending_command(chat_id, db)
                return {"status": "command_processed"}
            # NEW COMMANDS - Add these
            elif text.startswith('/availability'):
                await handle_availability_command(chat_id, text[13:], db)
                return {"status": "command_processed"}
            elif text.startswith('/bookings'):
                await handle_bookings_command(chat_id, text[10:], db)
                return {"status": "command_processed"}
            elif text.startswith('/modify'):
                await handle_modify_command(chat_id, text[8:], db)
                return {"status": "command_processed"}
            else:
                await send_telegram_message(
                    chat_id, 
                    f"❌ Unknown command: {text}\n\nType /help for available commands."
                )
                return {"status": "command_processed"}
        
        # Not a command - check if we're in editing mode
        if in_editing_mode:
            # We're in editing mode - process as draft update
            booking = editing_booking
            
            # Check if this is a reply to the edit instruction (optional but recommended)
            reply_to_message = message.get("reply_to_message")
            is_reply_to_edit = False
            
            if reply_to_message:
                reply_text = reply_to_message.get("text", "")
                if "EDITING MODE ACTIVATED" in reply_text or f"Booking #{booking.id}" in reply_text:
                    is_reply_to_edit = True
            
            if not is_reply_to_edit:
                # Warn that they should reply to the edit message
                warning = (
                    f"⚠️ *You're in edit mode*\n\n"
                    f"You are currently editing Booking #{booking.id}.\n\n"
                    f"Please reply to the edit instruction message with your revised draft.\n\n"
                    f"Type /cancel to exit edit mode."
                )
                await send_telegram_message(chat_id, warning)
                return {"status": "warning"}
            
            # Update the draft
            logger.info(f"Processing edit for booking #{booking.id}")
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
                f"✅ *Draft Updated Successfully*\n"
                f"{'━' * 25}\n\n"
                f"*Booking #{booking.id} - {booking.guest_name}*\n\n"
                f"*New Draft:*\n"
                f"```\n{text}\n```\n\n"
                f"💬 *You are now in normal mode*\n\n"
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
                pass
        
            else:
            # Not in editing mode - try natural language processing first
               logger.info("No booking in editing mode, trying natural language")
            
            # Check if it's a natural language query
            from services.nlp_processor import nlp
            parsed = nlp.parse_query(text)
            
            if parsed['intent'] and parsed.get('confidence', 0) > 0.5:
                # High confidence match - use NLP
                await handle_natural_language(chat_id, text, db)
            else:
                # Low confidence - fall back to Q&A
                logger.info(f"Low confidence NLP match ({parsed.get('confidence', 0)}), falling back to Q&A")
                await handle_manager_question(chat_id, text, db)
        
        return {"status": "message_processed"}
        
    except Exception as e:
        logger.error(f"Error in handle_text_message: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

async def handle_availability_command(chat_id: int, args: str, db: Session):
    """Usage: /availability [YYYY-MM-DD] [room_type]"""
    logger.info(f"=== AVAILABILITY COMMAND STARTED ===")
    logger.info(f"Raw args: '{args}'")
    logger.info(f"Chat ID: {chat_id}")
    
    parts = args.strip().split()
    logger.info(f"Parsed parts: {parts}")
    
    # If no date provided, show interactive date selection
    if not parts:
        logger.info("No parts provided, showing date picker")
        
        # Create buttons for next 7 days
        today = datetime.now().date()
        keyboard = {
            "inline_keyboard": []
        }
        
        # Add rows of 3 dates each
        row = []
        for i in range(7):
            date = today + timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            display = date.strftime("%d %b")  # Shows "05 Mar"
            
            row.append({
                "text": display,
                "callback_data": f"avail_date_{date_str}"
            })
            
            # Create new row every 3 buttons
            if len(row) == 3 or i == 6:
                keyboard["inline_keyboard"].append(row)
                row = []
        
        # Add cancel button
        keyboard["inline_keyboard"].append([
            {"text": "❌ Cancel", "callback_data": "avail_cancel"}
        ])
        
        await send_telegram_message(
            chat_id,
            "📅 *Select a date to check availability:*",
            reply_markup=keyboard
        )
        return
    
    # If date provided, check availability
    try:
        check_date = date.fromisoformat(parts[0])
        logger.info(f"Parsed date: {check_date}")
    except ValueError as e:
        logger.error(f"Date parsing error: {e}")
        await send_telegram_message(chat_id, "❌ Invalid date format. Use YYYY-MM-DD (e.g., 2026-03-05)")
        return
    
    room_type = parts[1] if len(parts) > 1 else None
    logger.info(f"Room type filter: {room_type}")
    
    # Get hotel_id from context (using 1 as default for now)
    hotel_id = 1
    logger.info(f"Using hotel_id: {hotel_id}")
    
    try:
        # Import here to avoid circular imports
        from services.availability import check_availability
        logger.info("Successfully imported check_availability")
        
        # First, check if any room types exist
        room_types_count = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).count()
        logger.info(f"Room types found for hotel {hotel_id}: {room_types_count}")
        
        if room_types_count == 0:
            logger.warning("No room types found!")
            await send_telegram_message(chat_id, 
                "❌ No room types found for this hotel. Please create room types first using the API.")
            return
        
        # Log all room types
        all_room_types = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).all()
        logger.info(f"Room types: {[{'name': rt.name, 'total': rt.total_rooms} for rt in all_room_types]}")
        
        # Check availability
        logger.info(f"Calling check_availability with date={check_date}, room_type={room_type}")
        avail = check_availability(db, hotel_id, check_date, room_type)
        logger.info(f"Availability result type: {type(avail)}")
        logger.info(f"Availability result: {avail}")
        
    except ImportError as e:
        logger.error(f"Import error: {e}", exc_info=True)
        await send_telegram_message(chat_id, f"❌ System error: availability module not found")
        return
    except Exception as e:
        logger.error(f"Availability check error: {str(e)}", exc_info=True)
        await send_telegram_message(chat_id, f"❌ Error checking availability: {str(e)}")
        return

    if room_type:
        if room_type in avail:
            data = avail[room_type]
            msg = (
                f"📅 *Availability for {check_date}*\n\n"
                f"🏨 *Room Type:* {room_type}\n"
                f"📊 Booked: {data['booked']} rooms\n"
                f"✅ Available: {data['available']} rooms\n"
                f"🏢 Total: {data['total']} rooms\n"
                f"👥 Guests: {data['guests']} checking in"
            )
        else:
            # List available room types
            if avail:
                available_types = list(avail.keys())
                msg = f"❌ Room type '{room_type}' not found. Available types: {', '.join(available_types)}"
            else:
                msg = f"❌ No room types found for {check_date}."
    else:
        if not avail:
            msg = f"📅 No availability data found for {check_date}."
        else:
            msg = f"📅 *Availability Summary for {check_date}*\n\n"
            for rt, data in avail.items():
                msg += f"🏨 *{rt}*: {data['available']}/{data['total']} available ({data['guests']} guests)\n"
        
        # Add button to check another date
        keyboard = {
            "inline_keyboard": [
                [{"text": "📅 Check Another Date", "callback_data": "avail_another"}]
            ]
        }
    
        logger.info(f"Sending response message of length: {len(msg)}")
    logger.info(f"Response preview: {msg[:100]}...")
    logger.info(f"Type of send_telegram_message: {type(send_telegram_message)}")
    logger.info(f"send_telegram_message value: {send_telegram_message}")
    
    if room_type:
        try:
            result = await send_telegram_message(chat_id, msg)
            logger.info(f"✅ Send result: {result}")
        except Exception as e:
            logger.error(f"❌ Error sending message: {e}", exc_info=True)
    else:
        try:
            result = await send_telegram_message(chat_id, msg, reply_markup=keyboard)
            logger.info(f"✅ Send result with keyboard: {result}")
        except Exception as e:
            logger.error(f"❌ Error sending message with keyboard: {e}", exc_info=True)
    
    logger.info("=== AVAILABILITY COMMAND COMPLETED ===")

async def show_availability(chat_id: int, check_date: date, db: Session):
    """Helper function to show availability for a specific date"""
    logger.info(f"📊 show_availability called for date: {check_date}")
    logger.info(f"Type of send_telegram_message: {type(send_telegram_message)}")
    logger.info(f"send_telegram_message value: {send_telegram_message}")
    
    hotel_id = 1
    
    try:
        from services.availability import check_availability
        logger.info("✅ Imported check_availability")
        
        # Check if room types exist
        room_types_count = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).count()
        logger.info(f"🏨 Room types found: {room_types_count}")
        
        if room_types_count == 0:
            logger.warning("❌ No room types found")
            await send_telegram_message(chat_id, "❌ No room types found. Please create room types first.")
            return
        
        logger.info(f"🔍 Calling check_availability with date={check_date}")
        avail = check_availability(db, hotel_id, check_date, None)
        logger.info(f"📊 Availability result: {avail}")
        
        if not avail:
            msg = f"📅 No availability data found for {check_date}."
            logger.info("❌ No availability data")
        else:
            msg = f"📅 *Availability Summary for {check_date}*\n\n"
            for rt, data in avail.items():
                msg += f"🏨 *{rt}*: {data['available']}/{data['total']} available ({data['guests']} guests)\n"
            logger.info(f"✅ Generated message with {len(avail)} room types")
        
        # Add button to check another date
        keyboard = {
            "inline_keyboard": [
                [{"text": "📅 Check Another Date", "callback_data": "avail_another"}]
            ]
        }
        
        logger.info(f"About to send message with keyboard. Msg length: {len(msg)}")
        result = await send_telegram_message(chat_id, msg, reply_markup=keyboard)
        logger.info(f"✅ Send result: {result}")
        
    except Exception as e:
        logger.error(f"❌ Availability error: {e}", exc_info=True)
        logger.info(f"Trying to send error message...")
        try:
            result = await send_telegram_message(chat_id, "❌ Error checking availability.")
            logger.info(f"✅ Error message sent: {result}")
        except Exception as e2:
            logger.error(f"❌ Even error message failed: {e2}", exc_info=True)
async def handle_bookings_command(chat_id: int, args: str, db: Session):
    """Usage: /bookings YYYY-MM-DD YYYY-MM-DD"""
    parts = args.strip().split()
    if len(parts) < 2:
        await send_telegram_message(chat_id,
            "📋 *Bookings Command*\n\n"
            "Usage: `/bookings YYYY-MM-DD YYYY-MM-DD`\n"
            "Example: `/bookings 2026-03-01 2026-03-05`"
        )
        return
    
    try:
        start = date.fromisoformat(parts[0])
        end = date.fromisoformat(parts[1])
    except ValueError:
        await send_telegram_message(chat_id, "❌ Invalid date format. Use YYYY-MM-DD")
        return

    if start > end:
        await send_telegram_message(chat_id, "❌ Start date must be before end date.")
        return

    hotel_id = 1
    
    try:
        from services.availability import get_daily_occupancy, get_booking_summary
        occupancy = get_daily_occupancy(db, hotel_id, start, end)
        bookings = get_booking_summary(db, hotel_id, start, end)
    except Exception as e:
        logger.error(f"Bookings query error: {e}")
        await send_telegram_message(chat_id, "❌ Error retrieving bookings. Please try again.")
        return

    if not bookings:
        await send_telegram_message(chat_id, f"📋 No bookings found from {start} to {end}.")
        return

    # Send summary first
    summary_msg = f"📋 *Booking Summary*\n{start} → {end}\n\n"
    summary_msg += f"📊 Total Bookings: {len(bookings)}\n"
    
    # Count by room type
    room_counts = {}
    guest_counts = {}
    for b in bookings:
        room_counts[b['room_type']] = room_counts.get(b['room_type'], 0) + b['rooms']
        guest_counts[b['room_type']] = guest_counts.get(b['room_type'], 0) + b['guests']
    
    for rt, count in room_counts.items():
        summary_msg += f"🏨 {rt}: {count} rooms ({guest_counts[rt]} guests)\n"
    
    await send_telegram_message(chat_id, summary_msg)

    # Send detailed daily breakdown if there are multiple days
    if (end - start).days > 0:
        detail_msg = f"📅 *Daily Breakdown*\n\n"
        for d, rooms in occupancy.items():
            date_str = d
            daily_bookings = [b for b in bookings if b['arrival'] <= date_str < b['departure']]
            if daily_bookings:
                detail_msg += f"*{date_str}*:\n"
                for b in daily_bookings[:3]:  # Limit to 3 per day to avoid long messages
                    detail_msg += f"  • #{b['id']}: {b['guest']} - {b['room_type']} ({b['guests']} guests)\n"
                if len(daily_bookings) > 3:
                    detail_msg += f"  ... and {len(daily_bookings)-3} more\n"
        
        await send_telegram_message(chat_id, detail_msg)

async def handle_modify_command(chat_id: int, args: str, db: Session):
    """Usage: /modify <confirmed_booking_id>"""
    args = args.strip()
    if not args:
        await send_telegram_message(chat_id,
            "✏️ *Modify Booking Command*\n\n"
            "Usage: `/modify <booking_id>`\n"
            "Example: `/modify 123`"
        )
        return
    
    try:
        booking_id = int(args)
    except ValueError:
        await send_telegram_message(chat_id, "❌ Invalid booking ID. Must be a number.")
        return

    booking = db.query(models.ConfirmedBooking).filter(models.ConfirmedBooking.id == booking_id).first()
    if not booking:
        await send_telegram_message(chat_id, f"❌ Confirmed booking #{booking_id} not found.")
        return

    # Check if there's already a pending modification
    existing_mod = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.original_booking_id == booking_id,
        models.ModificationRequest.status == "Pending"
    ).first()
    
    if existing_mod:
        await send_telegram_message(
            chat_id,
            f"⚠️ Modification #{existing_mod.id} already pending for this booking.\n"
            f"Please approve/reject it first or wait for it to be processed."
        )
        return

    # Create a modification request
    modification = models.ModificationRequest(
        original_booking_id=booking.id,
        guest_name=booking.guest_name,
        email=booking.email,
        arrival_date=booking.arrival_date,
        departure_date=booking.departure_date,
        room_type=booking.room_type,
        number_of_rooms=booking.number_of_rooms,
        number_of_guests=booking.number_of_guests,
        special_requests=booking.special_requests,
        status="Pending"
    )
    db.add(modification)
    db.commit()
    db.refresh(modification)

    # Mark original booking as having pending modification
    booking.has_pending_modification = True
    db.commit()

    # Send modification notification
    try:
        from services.telegram import send_modification_notification
        await send_modification_notification(modification, booking)
    except Exception as e:
        logger.error(f"Failed to send modification notification: {e}")

    await send_telegram_message(
        chat_id,
        f"✅ Modification request #{modification.id} created for booking #{booking_id}.\n"
        f"Please review it in the message above."
    )

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
    rejected = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Rejected").count()
    draft_ready = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Draft_Ready").count()
    email_sent = db.query(models.BookingRequest).filter(models.BookingRequest.status == "Email_Sent").count()
    
    message = (
        f"📊 **Booking Statistics**\n\n"
        f"Total: {total}\n"
        f"✅ Confirmed: {confirmed}\n"
        f"⏳ Pending: {pending}\n"
        f"⏱ Waitlist: {waitlist}\n"
        f"❌ Rejected: {rejected}\n"
        f"📝 Draft Ready: {draft_ready}\n"
        f"📧 Email Sent: {email_sent}"
    )
    
    await send_telegram_message(chat_id, message)

async def handle_today_command(chat_id: int, db: Session):
    """Handle /today command"""
    today = date.today()
    
    arrivals = db.query(models.BookingRequest).filter(
        models.BookingRequest.arrival_date == today
    ).all()
    
    departures = db.query(models.BookingRequest).filter(
        models.BookingRequest.departure_date == today
    ).all()
    
    message = f"📅 **Today's Overview ({today})**\n\n"
    
    if arrivals:
        message += f"*🛬 Arrivals ({len(arrivals)}):*\n"
        for b in arrivals[:5]:
            message += f"• #{b.id}: {b.guest_name} - {b.room_type}\n"
        if len(arrivals) > 5:
            message += f"  ... and {len(arrivals) - 5} more\n"
    else:
        message += "*🛬 Arrivals:* None\n"
    
    if departures:
        message += f"\n*🛫 Departures ({len(departures)}):*\n"
        for b in departures[:5]:
            message += f"• #{b.id}: {b.guest_name}\n"
        if len(departures) > 5:
            message += f"  ... and {len(departures) - 5} more\n"
    else:
        message += "\n*🛫 Departures:* None\n"
    
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
        "🤖 **THeO Bot Commands**\n\n"
        "**Booking Management:**\n"
        "/stats - View booking statistics\n"
        "/today - See today's arrivals/departures\n"
        "/pending - List pending bookings\n"
        "/modify <id> - Start modification for a confirmed booking\n\n"
        "**Availability & Reports:**\n"
        "/availability [date] - Check room availability (interactive)\n"
        "/bookings YYYY-MM-DD YYYY-MM-DD - List bookings in date range\n\n"
        "**General:**\n"
        "/help - Show this message\n\n"
        "**Sample Questions:**\n"
        "• \"What's the check-in time?\"\n"
        "• \"Do you have parking?\"\n"
        "• \"Cancellation policy?\"\n"
        "• \"Breakfast included?\"\n"
        "• \"Pet policy?\""
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