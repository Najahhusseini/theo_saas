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

# ==================== HELPER FUNCTIONS ====================
def get_mode_indicator(chat_id: int, db: Session) -> str:
    """Get the current mode indicator for a chat"""
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

# ==================== ROUTER SETUP ====================
router = APIRouter()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ==================== TELEGRAM WEBHOOK ====================
@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        body = await request.body()
        logger.info(f"Raw webhook received: {body.decode('utf-8')}")
        
        data = await request.json()
        logger.info(f"Parsed webhook: {json.dumps(data, indent=2)}")
        
        if "callback_query" in data:
            logger.info("Processing callback query")
            return await handle_callback_query(data["callback_query"], db)
        
        elif "message" in data:
            logger.info("Processing text message")
            return await handle_text_message(data["message"], db)
        
        logger.info("Ignoring unknown update type")
        return {"status": "ignored_update"}
    
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

# ==================== MODIFICATION ACTIONS ====================
async def handle_modification_actions(action: str, modification_id: int, chat_id: int, message_id: int, db: Session):
    """Handle modification-related callback actions"""
    
    if action == "mod_approve":
        logger.info(f"Processing modification approve for modification {modification_id}")
        
        modification = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.id == modification_id
        ).first()
        
        if not modification:
            await send_telegram_message(chat_id, f"❌ Modification #{modification_id} not found.")
            return {"status": "error"}
        
        if modification.status != "Pending":
            await send_telegram_message(chat_id, f"❌ Modification already {modification.status}")
            return {"status": "error"}
        
        original = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.id == modification.original_booking_id
        ).first()
        
        if not original:
            await send_telegram_message(chat_id, f"❌ Original booking not found.")
            return {"status": "error"}
        
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
        
        modification.status = "Approved"
        modification.processed_at = datetime.utcnow()
        
        original.has_pending_modification = False
        original.last_modified_at = datetime.utcnow()
        
        db.commit()
        
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
        
        if changes:
            changes_text = "\n".join([f"• {c[0]}: {c[1]} → {c[2]}" for c in changes])
            await send_telegram_message(
                chat_id,
                f"✅ *Modification Approved*\n\nBooking #{original.id} has been updated.\n\n*Changes applied:*\n{changes_text}"
            )
        else:
            await send_telegram_message(
                chat_id,
                f"✅ *Modification Approved*\n\nModification #{modification_id} for Booking #{original.id} was approved with no changes."
            )
        
        await edit_message_text(
            chat_id,
            message_id,
            f"✅ *Modification #{modification.id} APPROVED*\n\n{len(changes)} changes applied to Booking #{original.id}"
        )
    
    elif action == "mod_reject":
        logger.info(f"Processing modification reject for modification {modification_id}")
        
        modification = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.id == modification_id
        ).first()
        
        if not modification:
            await send_telegram_message(chat_id, f"❌ Modification #{modification_id} not found.")
            return {"status": "error"}
        
        await send_telegram_message(
            chat_id,
            f"❓ *Reason for Rejection*\n\nPlease reply with the reason for rejecting modification #{modification.id}",
            reply_markup={
                "force_reply": True,
                "input_field_placeholder": "Enter rejection reason..."
            }
        )
        
        if not hasattr(handle_modification_actions, "pending_rejections"):
            handle_modification_actions.pending_rejections = {}
        handle_modification_actions.pending_rejections[chat_id] = modification_id
    
    elif action == "mod_details":
        logger.info(f"Processing modification details for modification {modification_id}")
        
        modification = db.query(models.ModificationRequest).filter(
            models.ModificationRequest.id == modification_id
        ).first()
        
        if not modification:
            await send_telegram_message(chat_id, f"❌ Modification #{modification_id} not found.")
            return {"status": "error"}
        
        original = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.id == modification.original_booking_id
        ).first()
        
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
    from datetime import datetime
    """Handle inline keyboard button presses"""
    try:
        callback_data = callback["data"]
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        callback_id = callback["id"]
        
        logger.info(f"Processing callback - Action: {callback_data}, Chat: {chat_id}")
        
        try:
            answer_url = f"{TELEGRAM_API_URL}/answerCallbackQuery"
            requests.post(answer_url, json={"callback_query_id": callback_id}, timeout=5)
            logger.info("Callback answered successfully")
        except Exception as e:
            logger.error(f"Failed to answer callback: {e}")
        
        # ===== AVAILABILITY HANDLERS =====
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
            logger.info(f"📅 Checking another date (message_id: {message_id})")
            try:
                await send_telegram_message(chat_id, "🔄 Loading date picker...")
            except:
                pass
            await handle_availability_command(chat_id, "", db)
            try:
                delete_url = f"{TELEGRAM_API_URL}/deleteMessage"
                requests.post(delete_url, json={
                    "chat_id": chat_id,
                    "message_id": message_id
                }, timeout=5)
                logger.info(f"✅ Deleted original message {message_id}")
            except Exception as e:
                logger.error(f"Failed to delete message: {e}")
            return {"status": "success"}

        elif callback_data == "avail_cancel":
            logger.info("❌ Availability check cancelled")
            await send_telegram_message(chat_id, "❌ Availability check cancelled.")
            return {"status": "success"}
        
        # ===== OCCUPANCY HANDLERS =====
        if callback_data.startswith("occupancy_date_"):
            date_str = callback_data.replace("occupancy_date_", "")
            logger.info(f"📊 Occupancy date selected: {date_str}")
            try:
                selected_date = date.fromisoformat(date_str)
                await show_occupancy_for_date(chat_id, selected_date, db)
            except ValueError as e:
                logger.error(f"❌ Date parsing error: {e}")
                await send_telegram_message(chat_id, f"❌ Invalid date format: {date_str}")
            return {"status": "success"}

        elif callback_data == "occupancy_today":
            logger.info("📊 Occupancy for today requested")
            today = datetime.now().date()
            await show_occupancy_for_date(chat_id, today, db)
            return {"status": "success"}

        elif callback_data == "occupancy_week":
            logger.info("📊 Occupancy for this week requested")
            today = datetime.now().date()
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            await show_occupancy_for_range(chat_id, start_of_week, end_of_week, db)
            return {"status": "success"}

        elif callback_data == "occupancy_month":
            logger.info("📊 Occupancy for this month requested")
            today = datetime.now().date()
            start_of_month = today.replace(day=1)
            if today.month == 12:
                end_of_month = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
            else:
                end_of_month = today.replace(month=today.month+1, day=1) - timedelta(days=1)
            await show_occupancy_for_range(chat_id, start_of_month, end_of_month, db)
            return {"status": "success"}

        elif callback_data == "occupancy_cancel":
            logger.info("❌ Occupancy check cancelled")
            await send_telegram_message(chat_id, "❌ Occupancy check cancelled.")
            return {"status": "success"}

        elif callback_data.startswith("occupancy_prev_"):
            date_str = callback_data.replace("occupancy_prev_", "")
            try:
                current_date = date.fromisoformat(date_str)
                prev_date = current_date - timedelta(days=1)
                await show_occupancy_for_date(chat_id, prev_date, db)
            except:
                await send_telegram_message(chat_id, "❌ Error loading previous day")
            return {"status": "success"}

        elif callback_data.startswith("occupancy_next_"):
            date_str = callback_data.replace("occupancy_next_", "")
            try:
                current_date = date.fromisoformat(date_str)
                next_date = current_date + timedelta(days=1)
                await show_occupancy_for_date(chat_id, next_date, db)
            except:
                await send_telegram_message(chat_id, "❌ Error loading next day")
            return {"status": "success"}

        elif callback_data.startswith("occupancy_prev_week_"):
            date_str = callback_data.replace("occupancy_prev_week_", "")
            try:
                current_date = date.fromisoformat(date_str)
                prev_week_start = current_date - timedelta(days=7)
                prev_week_end = prev_week_start + timedelta(days=6)
                await show_occupancy_for_range(chat_id, prev_week_start, prev_week_end, db)
            except Exception as e:
                logger.error(f"Error loading previous week: {e}")
                await send_telegram_message(chat_id, "❌ Error loading previous week")
            return {"status": "success"}

        elif callback_data.startswith("occupancy_next_week_"):
            date_str = callback_data.replace("occupancy_next_week_", "")
            try:
                current_date = date.fromisoformat(date_str)
                next_week_start = current_date + timedelta(days=7)
                next_week_end = next_week_start + timedelta(days=6)
                await show_occupancy_for_range(chat_id, next_week_start, next_week_end, db)
            except Exception as e:
                logger.error(f"Error loading next week: {e}")
                await send_telegram_message(chat_id, "❌ Error loading next week")
            return {"status": "success"}

        # ===== COMPARE OCCUPANCY HANDLERS =====
        elif callback_data == "compare_week":
            logger.info("📊 Week over week comparison requested")
            today = datetime.now().date()
            end_current = today
            start_current = today - timedelta(days=6)
            end_previous = start_current - timedelta(days=1)
            start_previous = end_previous - timedelta(days=6)
            await compare_occupancy(chat_id, start_previous, end_previous, start_current, end_current, db)
            return {"status": "success"}

        elif callback_data == "compare_month":
            logger.info("📊 Month over month comparison requested")
            today = datetime.now().date()
            start_current = today.replace(day=1)
            if today.month == 12:
                end_current = today.replace(year=today.year+1, month=1, day=1) - timedelta(days=1)
            else:
                end_current = today.replace(month=today.month+1, day=1) - timedelta(days=1)
            
            if today.month == 1:
                start_previous = today.replace(year=today.year-1, month=12, day=1)
                end_previous = today.replace(year=today.year-1, month=12, day=31)
            else:
                start_previous = today.replace(month=today.month-1, day=1)
                end_previous = today.replace(month=today.month, day=1) - timedelta(days=1)
            
            await compare_occupancy(chat_id, start_previous, end_previous, start_current, end_current, db)
            return {"status": "success"}

        elif callback_data == "compare_custom":
            logger.info("📊 Custom comparison requested")
            await send_telegram_message(chat_id,
                "📊 *Custom Comparison*\n\n"
                "To compare two custom periods, use:\n"
                "• `/occupancy 2026-03-01 2026-03-07` for first period\n"
                "• `/occupancy 2026-03-08 2026-03-14` for second period\n\n"
                "We're working on an interactive comparison tool!")
            return {"status": "success"}
        
        # ===== BOOKINGS HANDLERS =====
        if callback_data.startswith("bookings_start_"):
            date_str = callback_data.replace("bookings_start_", "")
            logger.info(f"📅 Bookings start date selected: {date_str}")
            try:
                selected_date = date.fromisoformat(date_str)
                if not hasattr(handle_callback_query, "bookings_start_dates"):
                    handle_callback_query.bookings_start_dates = {}
                handle_callback_query.bookings_start_dates[chat_id] = selected_date
                await ask_for_end_date(chat_id, selected_date, db)
            except ValueError as e:
                logger.error(f"❌ Date parsing error: {e}")
                await send_telegram_message(chat_id, f"❌ Invalid date format: {date_str}")
            return {"status": "success"}

        elif callback_data.startswith("bookings_end_"):
            date_str = callback_data.replace("bookings_end_", "")
            logger.info(f"📅 Bookings end date selected: {date_str}")
            try:
                end_date = date.fromisoformat(date_str)
                logger.info(f"✅ Parsed end date: {end_date}")
                
                if not hasattr(handle_callback_query, "bookings_start_dates"):
                    logger.error("❌ bookings_start_dates dict doesn't exist")
                    await send_telegram_message(chat_id, "❌ Session expired. Please start over with /bookings")
                    return {"status": "error"}
                
                if chat_id not in handle_callback_query.bookings_start_dates:
                    logger.error(f"❌ No start date found for chat_id {chat_id}")
                    await send_telegram_message(chat_id, "❌ No start date selected. Please start over with /bookings")
                    return {"status": "error"}
                
                start_date = handle_callback_query.bookings_start_dates.pop(chat_id)
                logger.info(f"📅 Retrieved start date: {start_date}")
                
                if start_date > end_date:
                    logger.warning(f"❌ End date {end_date} is before start date {start_date}")
                    await send_telegram_message(chat_id, "❌ End date must be after start date. Please try again.")
                    await handle_bookings_command(chat_id, "", db)
                    return {"status": "error"}
                
                logger.info(f"✅ Calling handle_bookings_command with {start_date} {end_date}")
                try:
                    await handle_bookings_command(chat_id, f"{start_date} {end_date}", db)
                except Exception as e:
                    error_str = str(e)
                    logger.error(f"❌ Error in bookings command: {error_str}")
                    if "No bookings found" not in error_str:
                        await send_telegram_message(chat_id, "❌ Error processing date selection")
                    else:
                        logger.info("No bookings found - this is normal")
            except ValueError as e:
                logger.error(f"❌ Date parsing error: {e}")
                await send_telegram_message(chat_id, f"❌ Invalid date format: {date_str}")
            except Exception as e:
                logger.error(f"❌ Unexpected error: {e}", exc_info=True)
                if "No bookings found" not in str(e):
                    await send_telegram_message(chat_id, "❌ Error processing date selection")
            return {"status": "success"}

        elif callback_data == "bookings_cancel":
            logger.info("❌ Bookings check cancelled")
            if hasattr(handle_callback_query, "bookings_start_dates") and chat_id in handle_callback_query.bookings_start_dates:
                del handle_callback_query.bookings_start_dates[chat_id]
            await send_telegram_message(chat_id, "❌ Bookings check cancelled.")
            return {"status": "success"}
        
        # ===== CANCELLATION HANDLERS =====
        if callback_data.startswith("cancel_confirm_"):
            booking_id = int(callback_data.replace("cancel_confirm_", ""))
            booking = db.query(models.ConfirmedBooking).filter(models.ConfirmedBooking.id == booking_id).first()
            
            if booking:
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
        
        # ===== SPECIAL ACTIONS (STATS, TODAY, PENDING, HELP, STATUS, ROOMTYPES, ARRIVALS, DEPARTURES, MENU, AVAILABILITY, BOOKINGS, OCCUPANCY_TODAY) =====
        if callback_data in ["stats", "today", "pending", "help", "status", "roomtypes", "arrivals", "departures", "menu", "availability", "bookings", "occupancy_today"]:
            if callback_data == "stats":
                logger.info("Processing stats command from callback")
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
                
                await send_stats_dashboard(chat_id, stats)
                
            elif callback_data == "status":
                logger.info("🔄 Refreshing status dashboard")
                await handle_status_command(chat_id, db)

            elif callback_data == "roomtypes":
                logger.info("🔄 Refreshing room types overview")
                await handle_roomtypes_command(chat_id, db)

            elif callback_data == "arrivals":
                logger.info("🛬 Showing arrivals")
                await handle_arrivals_command(chat_id, db)
                
            elif callback_data == "departures":
                logger.info("🛫 Showing departures")
                await handle_departures_command(chat_id, db)
                
            elif callback_data == "menu":
                logger.info("🎯 Showing main menu")
                await handle_menu_command(chat_id, db)
                
            elif callback_data == "availability":
                logger.info("📅 Showing availability picker")
                await handle_availability_command(chat_id, "", db)
                
            elif callback_data == "bookings":
                logger.info("📋 Showing bookings picker")
                await handle_bookings_command(chat_id, "", db)
                
            elif callback_data == "occupancy_today":
                logger.info("📊 Showing today's occupancy")
                from datetime import datetime
                today = datetime.now().date()
                await show_occupancy_for_date(chat_id, today, db)
                
            elif callback_data == "today":
                logger.info("Processing today command from callback")
                today = date.today()
                arrivals = db.query(models.BookingRequest).filter(
                    models.BookingRequest.arrival_date == today
                ).all()
                departures = db.query(models.BookingRequest).filter(
                    models.BookingRequest.departure_date == today
                ).all()
                await send_today_summary(chat_id, arrivals, departures)
                
            elif callback_data == "pending":
                logger.info("Processing pending command from callback")
                await handle_pending_command(chat_id, db)
                
            elif callback_data == "help":
                logger.info("Processing help command from callback")
                await handle_help_command(chat_id)
                
            return {"status": "success"}
        
        # ===== BOOKING ACTIONS WITH IDS =====
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
        
        if action in ["mod_approve", "mod_reject", "mod_details"]:
            return await handle_modification_actions(action, booking_id, chat_id, message_id, db)
        
        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == booking_id
        ).first()
        
        if not booking:
            logger.error(f"Booking {booking_id} not found")
            await send_telegram_message(chat_id, f"❌ Booking #{booking_id} not found.")
            return {"status": "error", "message": "Booking not found"}
        
        logger.info(f"Found booking #{booking_id} with status: {booking.status}")
        
        if action in ["confirm", "reject", "waitlist"]:
            new_status = action.capitalize()
            booking.status = new_status
            db.commit()
            logger.info(f"Updated booking #{booking_id} status to: {new_status}")
            
            draft = generate_reply_draft(booking, new_status)
            booking.draft_reply = draft
            db.commit()
            logger.info(f"Generated draft for booking #{booking_id}")
            
            await send_draft_for_approval(booking, new_status, draft)
            
            await edit_message_text(
                chat_id, 
                message_id,
                f"✅ Booking #{booking.id} marked as {new_status}\nDraft generated. Please review above."
            )
        
        elif action == "edit":
            logger.info(f"Processing edit action for booking {booking_id}")
            
            existing_edit = db.query(models.BookingRequest).filter(
                models.BookingRequest.status == "Editing",
                models.BookingRequest.id != booking_id
            ).first()
            
            if existing_edit:
                warning_message = (
                    f"⚠️ *Cannot Enter Edit Mode*\n\n"
                    f"Booking #{existing_edit.id} is already being edited.\n\n"
                    f"Please finish editing that booking first or wait for it to timeout."
                )
                await send_telegram_message(chat_id, warning_message)
                return {"status": "error", "message": "Another booking is in editing mode"}
            
            booking.status = "Editing"
            db.commit()
            
            current_draft = booking.draft_reply or "No draft yet."
            
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
            
            edit_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "❌ CANCEL EDIT", "callback_data": f"cancel_{booking.id}"}
                    ]
                ]
            }
            
            await send_telegram_message(chat_id, instruction_message, reply_markup=edit_keyboard)
            
            await edit_message_text(
                chat_id,
                message_id,
                f"✏️ **Booking #{booking.id} is now in EDIT MODE**\n\nPlease reply to the edit instruction message above with your revised draft."
            )
        
        elif action == "send":
            logger.info(f"Processing send action for booking {booking_id}")
            
            booking.status = "Email_Sent"
            db.commit()
            
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

# ==================== AVAILABILITY COMMANDS ====================
async def handle_availability_command(chat_id: int, args: str, db: Session):
    """Usage: /availability [YYYY-MM-DD] [room_type]"""
    logger.info(f"=== AVAILABILITY COMMAND STARTED ===")
    logger.info(f"Raw args: '{args}'")
    logger.info(f"Chat ID: {chat_id}")
    
    parts = args.strip().split()
    logger.info(f"Parsed parts: {parts}")
    
    if not parts:
        logger.info("No parts provided, showing date picker")
        today = datetime.now().date()
        keyboard = {"inline_keyboard": []}
        row = []
        for i in range(7):
            date = today + timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            display = date.strftime("%d %b")
            row.append({
                "text": display,
                "callback_data": f"avail_date_{date_str}"
            })
            if len(row) == 3 or i == 6:
                keyboard["inline_keyboard"].append(row)
                row = []
        
        keyboard["inline_keyboard"].append([
            {"text": "❌ Cancel", "callback_data": "avail_cancel"}
        ])
        
        await send_telegram_message(
            chat_id,
            "📅 *Select a date to check availability:*",
            reply_markup=keyboard
        )
        return
    
    try:
        check_date = date.fromisoformat(parts[0])
        logger.info(f"Parsed date: {check_date}")
    except ValueError as e:
        logger.error(f"Date parsing error: {e}")
        await send_telegram_message(chat_id, "❌ Invalid date format. Use YYYY-MM-DD (e.g., 2026-03-05)")
        return
    
    room_type = parts[1] if len(parts) > 1 else None
    logger.info(f"Room type filter: {room_type}")
    
    hotel_id = 1
    logger.info(f"Using hotel_id: {hotel_id}")
    
    try:
        from services.availability import check_availability
        logger.info("Successfully imported check_availability")
        
        room_types_count = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).count()
        logger.info(f"Room types found for hotel {hotel_id}: {room_types_count}")
        
        if room_types_count == 0:
            logger.warning("No room types found!")
            await send_telegram_message(chat_id, 
                "❌ No room types found for this hotel. Please create room types first using the API.")
            return
        
        all_room_types = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).all()
        logger.info(f"Room types: {[{'name': rt.name, 'total': rt.total_rooms} for rt in all_room_types]}")
        
        logger.info(f"Calling check_availability with date={check_date}, room_type={room_type}")
        avail = check_availability(db, hotel_id, check_date, room_type)
        logger.info(f"Availability result: {avail}")
        
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
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📅 Check Another Date", "callback_data": "avail_another"}]
            ]
        }
    
    logger.info(f"Sending response message of length: {len(msg)}")
    
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

async def ask_for_end_date(chat_id: int, start_date: date, db: Session):
    """Show date picker for end date selection"""
    from services.telegram import send_telegram_message as send_msg
    
    logger.info(f"📅 Asking for end date after start date: {start_date}")
    
    keyboard = {"inline_keyboard": []}
    row = []
    for i in range(14):
        date = start_date + timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        display = date.strftime("%d %b")
        
        row.append({
            "text": display,
            "callback_data": f"bookings_end_{date_str}"
        })
        
        if len(row) == 3 or i == 13:
            keyboard["inline_keyboard"].append(row)
            row = []
    
    keyboard["inline_keyboard"].append([
        {"text": "❌ Cancel", "callback_data": "bookings_cancel"}
    ])
    
    await send_msg(
        chat_id,
        f"📅 *Select End Date*\n\nStart date: {start_date.strftime('%d %b %Y')}\n\nPlease select an end date:",
        reply_markup=keyboard
    )

async def show_availability(chat_id: int, check_date: date, db: Session):
    """Helper function to show availability for a specific date"""
    logger.info(f"📊 show_availability called for date: {check_date}")
    
    hotel_id = 1
    
    try:
        from services.availability import check_availability
        
        room_types_count = db.query(models.RoomType).filter(models.RoomType.hotel_id == hotel_id).count()
        
        if room_types_count == 0:
            await send_telegram_message(chat_id, "❌ No room types found. Please create room types first.")
            return
        
        avail = check_availability(db, hotel_id, check_date, None)
        
        if not avail:
            msg = f"📅 No availability data found for {check_date}."
        else:
            msg = f"📅 *Availability Summary for {check_date}*\n\n"
            for rt, data in avail.items():
                msg += f"🏨 *{rt}*: {data['available']}/{data['total']} available ({data['guests']} guests)\n"
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📅 Check Another Date", "callback_data": "avail_another"}]
            ]
        }
        
        await send_telegram_message(chat_id, msg, reply_markup=keyboard)
        logger.info("✅ Single availability message sent")
        
    except Exception as e:
        logger.error(f"❌ Availability error: {e}", exc_info=True)
        pass

# ==================== BOOKINGS COMMANDS ====================
async def handle_bookings_command(chat_id: int, args: str, db: Session):
    """Usage: /bookings [YYYY-MM-DD YYYY-MM-DD] - if no dates provided, shows interactive date picker"""
    from services.telegram import send_telegram_message as send_msg
    from datetime import date as date_class
    
    parts = args.strip().split()
    
    if len(parts) < 2:
        logger.info("No dates provided, showing date range picker")
        current_date = datetime.now().date()
        keyboard = {"inline_keyboard": []}
        row = []
        for i in range(14):
            pick_date = current_date + timedelta(days=i)
            date_str = pick_date.strftime("%Y-%m-%d")
            display = pick_date.strftime("%d %b")
            
            row.append({
                "text": display,
                "callback_data": f"bookings_start_{date_str}"
            })
            
            if len(row) == 3 or i == 13:
                keyboard["inline_keyboard"].append(row)
                row = []
        
        keyboard["inline_keyboard"].append([
            {"text": "❌ Cancel", "callback_data": "bookings_cancel"}
        ])
        
        await send_msg(
            chat_id,
            "📅 *Select Start Date*\n\nChoose the first date of your booking range:",
            reply_markup=keyboard
        )
        return
    
    try:
        start = date_class.fromisoformat(parts[0])
        end = date_class.fromisoformat(parts[1])
    except ValueError:
        await send_msg(chat_id, "❌ Invalid date format. Use YYYY-MM-DD")
        return

    if start > end:
        await send_msg(chat_id, "❌ Start date must be before end date.")
        return

    hotel_id = 1
    
    try:
        from services.availability import get_daily_occupancy, get_booking_summary
        occupancy = get_daily_occupancy(db, hotel_id, start, end)
        bookings = get_booking_summary(db, hotel_id, start, end)
    except Exception as e:
        logger.error(f"Bookings query error: {e}")
        await send_msg(chat_id, "❌ Error retrieving bookings. Please try again.")
        return

    if not bookings:
        await send_msg(chat_id, f"📋 No bookings found from {start} to {end}.")
        return

    summary_msg = f"📋 *Booking Summary*\n{start} → {end}\n\n"
    summary_msg += f"📊 Total Bookings: {len(bookings)}\n"
    
    room_counts = {}
    guest_counts = {}
    for b in bookings:
        room_counts[b['room_type']] = room_counts.get(b['room_type'], 0) + b['rooms']
        guest_counts[b['room_type']] = guest_counts.get(b['room_type'], 0) + b['guests']
    
    for rt, count in room_counts.items():
        summary_msg += f"🏨 {rt}: {count} rooms ({guest_counts[rt]} guests)\n"
    
    await send_msg(chat_id, summary_msg)

    if (end - start).days > 0:
        detail_msg = f"📅 *Daily Breakdown*\n\n"
        for d, rooms in occupancy.items():
            date_str = d
            daily_bookings = [b for b in bookings if b['arrival'] <= date_str < b['departure']]
            if daily_bookings:
                detail_msg += f"*{date_str}*:\n"
                for b in daily_bookings[:3]:
                    detail_msg += f"  • #{b['id']}: {b['guest']} - {b['room_type']} ({b['guests']} guests)\n"
                if len(daily_bookings) > 3:
                    detail_msg += f"  ... and {len(daily_bookings)-3} more\n"
        
        await send_msg(chat_id, detail_msg)
    
    return

# ==================== MODIFY COMMAND ====================
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

    booking.has_pending_modification = True
    db.commit()

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

# ==================== STATUS COMMAND ====================
async def handle_status_command(chat_id: int, db: Session):
    """Show real-time hotel status dashboard"""
    from services.telegram import send_telegram_message as send_msg
    from datetime import datetime, date
    from sqlalchemy import func
    
    logger.info(f"📊 Processing status command for chat {chat_id}")
    
    hotel_id = 1
    today = date.today()
    now = datetime.now()
    
    room_types = db.query(models.RoomType).filter(
        models.RoomType.hotel_id == hotel_id
    ).all()
    total_rooms = sum(rt.total_rooms for rt in room_types)
    
    today_bookings = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.arrival_date <= today,
        models.ConfirmedBooking.departure_date > today
    ).all()
    
    occupied_rooms = sum(b.number_of_rooms for b in today_bookings)
    available_rooms = total_rooms - occupied_rooms
    occupancy_rate = round((occupied_rooms / total_rooms * 100) if total_rooms > 0 else 0)
    
    check_ins = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.arrival_date == today
    ).count()
    
    check_outs = db.query(models.ConfirmedBooking).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.departure_date == today
    ).count()
    
    current_guests = db.query(func.sum(models.ConfirmedBooking.number_of_guests)).filter(
        models.ConfirmedBooking.hotel_id == hotel_id,
        models.ConfirmedBooking.arrival_date <= today,
        models.ConfirmedBooking.departure_date > today
    ).scalar() or 0
    
    pending_requests = db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Pending"
    ).count()
    
    pending_mods = db.query(models.ModificationRequest).filter(
        models.ModificationRequest.status == "Pending"
    ).count()
    
    drafts_ready = db.query(models.BookingRequest).filter(
        models.BookingRequest.status == "Draft_Ready"
    ).count()
    
    room_breakdown = []
    for rt in room_types:
        booked = db.query(models.ConfirmedBooking).filter(
            models.ConfirmedBooking.hotel_id == hotel_id,
            models.ConfirmedBooking.room_type == rt.name,
            models.ConfirmedBooking.arrival_date <= today,
            models.ConfirmedBooking.departure_date > today
        ).count()
        room_breakdown.append(f"• {rt.name}: {booked}/{rt.total_rooms} booked")
    
    message = f"""
🏨 *HOTEL STATUS DASHBOARD*
━━━━━━━━━━━━━━━━━━━
📅 *Today:* {today.strftime('%d %b %Y')}
🕐 *Time:* {now.strftime('%H:%M')}

📊 *OCCUPANCY*
• Total Rooms: {total_rooms}
• Occupied: {occupied_rooms}
• Available: {available_rooms}
• Occupancy Rate: {occupancy_rate}%

👥 *GUESTS TODAY*
• Check-ins: {check_ins}
• Check-outs: {check_outs}
• Currently In-house: {current_guests}

⏳ *PENDING ACTIONS*
• New Requests: {pending_requests}
• Modifications: {pending_mods}
• Drafts Ready: {drafts_ready}

🏨 *ROOM TYPE BREAKDOWN*
{chr(10).join(room_breakdown)}
━━━━━━━━━━━━━━━━━━━
💡 *Quick Actions*
"""
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📅 Today's Arrivals", "callback_data": "today"},
                {"text": "⏳ Pending", "callback_data": "pending"}
            ],
            [
                {"text": "📊 Stats", "callback_data": "stats"},
                {"text": "🔄 Refresh", "callback_data": "status"}
            ]
        ]
    }
    
    await send_msg(chat_id, message, reply_markup=keyboard)

# ==================== OCCUPANCY FUNCTIONS ====================
async def show_occupancy_for_date(chat_id: int, check_date: date, db: Session):
    """Show occupancy report for a single date"""
    from services.telegram import send_telegram_message
    from services.availability import get_daily_occupancy
    
    hotel_id = 1
    
    try:
        occupancy = get_daily_occupancy(db, hotel_id, check_date, check_date)
        day_data = occupancy.get(check_date.isoformat(), {})
        
        if not day_data:
            await send_telegram_message(chat_id, f"📊 No occupancy data found for {check_date}.")
            return
        
        total_rooms = sum(data['total'] for data in day_data.values())
        total_booked = sum(data['booked'] for data in day_data.values())
        total_guests = sum(data['guests'] for data in day_data.values())
        
        occupancy_pct = round((total_booked / total_rooms * 100) if total_rooms > 0 else 0)
        progress_blocks = round(occupancy_pct / 10)
        progress_bar = "█" * progress_blocks + "░" * (10 - progress_blocks)
        
        message = f"""
📊 *OCCUPANCY REPORT*
━━━━━━━━━━━━━━━━━━━
📅 *Date:* {check_date.strftime('%d %b %Y')}

🏨 *Overall Occupancy*
{progress_bar} {occupancy_pct}% ({total_booked}/{total_rooms} rooms)

📊 *By Room Type*
"""
        
        for rt_name, data in day_data.items():
            if data['total'] > 0:
                rt_pct = round((data['booked'] / data['total'] * 100))
                rt_blocks = round(rt_pct / 10)
                rt_bar = "█" * rt_blocks + "░" * (10 - rt_blocks)
                message += f"• {rt_name}: {rt_bar} {rt_pct}% ({data['booked']}/{data['total']})\n"
        
        message += f"""
👥 *Guest Statistics*
• Total Guests: {total_guests}
• Avg per room: {round(total_guests/total_booked, 1) if total_booked > 0 else 0}

━━━━━━━━━━━━━━━━━━━
💡 *Quick Actions*
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "◀️ Previous", "callback_data": f"occupancy_prev_{check_date}"},
                    {"text": "Next ▶️", "callback_data": f"occupancy_next_{check_date}"}
                ],
                [
                    {"text": "📅 This Week", "callback_data": "occupancy_week"},
                    {"text": "📅 This Month", "callback_data": "occupancy_month"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": f"occupancy_date_{check_date}"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info(f"✅ Occupancy report sent for {check_date}")
        
    except Exception as e:
        logger.error(f"Error in show_occupancy_for_date: {e}", exc_info=True)
        pass

async def show_occupancy_for_range(chat_id: int, start_date: date, end_date: date, db: Session):
    """Show average occupancy for a date range"""
    from services.telegram import send_telegram_message
    from services.availability import get_daily_occupancy
    
    hotel_id = 1
    delta_days = (end_date - start_date).days + 1
    
    try:
        occupancy = get_daily_occupancy(db, hotel_id, start_date, end_date)
        
        if not occupancy:
            await send_telegram_message(chat_id, f"📊 No occupancy data found for {start_date} to {end_date}.")
            return
        
        room_totals = {}
        guest_totals = {}
        daily_counts = 0
        
        for date_str, day_data in occupancy.items():
            daily_counts += 1
            for rt_name, data in day_data.items():
                if rt_name not in room_totals:
                    room_totals[rt_name] = {'total': data['total'], 'booked': 0, 'days': 0}
                room_totals[rt_name]['booked'] += data['booked']
                room_totals[rt_name]['days'] += 1
                guest_totals[rt_name] = guest_totals.get(rt_name, 0) + data['guests']
        
        total_rooms = sum(rt['total'] for rt in room_totals.values())
        avg_booked = sum(rt['booked'] for rt in room_totals.values()) / daily_counts if daily_counts > 0 else 0
        avg_guests = sum(guest_totals.values()) / daily_counts if daily_counts > 0 else 0
        
        avg_occupancy_pct = round((avg_booked / total_rooms * 100) if total_rooms > 0 else 0)
        progress_blocks = round(avg_occupancy_pct / 10)
        progress_bar = "█" * progress_blocks + "░" * (10 - progress_blocks)
        
        days_diff = (end_date - start_date).days
        if days_diff == 6:
            period_desc = "This Week"
        elif days_diff >= 28 and days_diff <= 31:
            period_desc = "This Month"
        else:
            period_desc = f"{start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}"
        
        message = f"""
📊 *OCCUPANCY REPORT*
━━━━━━━━━━━━━━━━━━━
📅 *Period:* {period_desc}
📊 *Days:* {daily_counts}

🏨 *Average Occupancy*
{progress_bar} {avg_occupancy_pct}% ({round(avg_booked, 1)}/{total_rooms} rooms avg)

📊 *By Room Type (Daily Average)*
"""
        
        for rt_name, rt_data in room_totals.items():
            avg_rt_booked = rt_data['booked'] / rt_data['days'] if rt_data['days'] > 0 else 0
            avg_rt_pct = round((avg_rt_booked / rt_data['total'] * 100))
            rt_blocks = round(avg_rt_pct / 10)
            rt_bar = "█" * rt_blocks + "░" * (10 - rt_blocks)
            message += f"• {rt_name}: {rt_bar} {avg_rt_pct}% ({round(avg_rt_booked, 1)}/{rt_data['total']})\n"
        
        message += f"""
👥 *Guest Statistics*
• Avg daily guests: {round(avg_guests, 1)}

━━━━━━━━━━━━━━━━━━━
💡 *Quick Actions*
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📅 View Daily", "callback_data": f"occupancy_date_{start_date}"},
                    {"text": "📊 Compare Weeks", "callback_data": "compare_week"}
                ],
                [
                    {"text": "◀️ Previous Week", "callback_data": f"occupancy_prev_week_{start_date}"},
                    {"text": "Next Week ▶️", "callback_data": f"occupancy_next_week_{start_date}"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info(f"✅ Occupancy range report sent for {start_date} to {end_date}")
        
    except Exception as e:
        logger.error(f"Error in show_occupancy_for_range: {e}", exc_info=True)
        pass

async def compare_occupancy(chat_id: int, period1_start: date, period1_end: date, period2_start: date, period2_end: date, db: Session):
    """Compare occupancy between two periods"""
    from services.telegram import send_telegram_message
    from services.availability import get_daily_occupancy
    
    hotel_id = 1
    
    try:
        occupancy1 = get_daily_occupancy(db, hotel_id, period1_start, period1_end)
        occupancy2 = get_daily_occupancy(db, hotel_id, period2_start, period2_end)
        
        room_totals1 = {}
        daily_counts1 = 0
        for date_str, day_data in occupancy1.items():
            daily_counts1 += 1
            for rt_name, data in day_data.items():
                if rt_name not in room_totals1:
                    room_totals1[rt_name] = {'total': data['total'], 'booked': 0, 'days': 0}
                room_totals1[rt_name]['booked'] += data['booked']
                room_totals1[rt_name]['days'] += 1
        
        room_totals2 = {}
        daily_counts2 = 0
        for date_str, day_data in occupancy2.items():
            daily_counts2 += 1
            for rt_name, data in day_data.items():
                if rt_name not in room_totals2:
                    room_totals2[rt_name] = {'total': data['total'], 'booked': 0, 'days': 0}
                room_totals2[rt_name]['booked'] += data['booked']
                room_totals2[rt_name]['days'] += 1
        
        if not room_totals1 or not room_totals2:
            await send_telegram_message(chat_id, "📊 Insufficient data for comparison.")
            return
        
        total_rooms = sum(rt['total'] for rt in room_totals1.values())
        
        avg_booked1 = sum(rt['booked'] for rt in room_totals1.values()) / daily_counts1 if daily_counts1 > 0 else 0
        avg_booked2 = sum(rt['booked'] for rt in room_totals2.values()) / daily_counts2 if daily_counts2 > 0 else 0
        
        avg_occupancy_pct1 = round((avg_booked1 / total_rooms * 100) if total_rooms > 0 else 0)
        avg_occupancy_pct2 = round((avg_booked2 / total_rooms * 100) if total_rooms > 0 else 0)
        
        change = avg_occupancy_pct2 - avg_occupancy_pct1
        change_emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        change_sign = "+" if change > 0 else ""
        
        period1_desc = f"{period1_start.strftime('%d %b')} - {period1_end.strftime('%d %b')}"
        period2_desc = f"{period2_start.strftime('%d %b')} - {period2_end.strftime('%d %b')}"
        
        message = f"""
📊 *OCCUPANCY COMPARISON*
━━━━━━━━━━━━━━━━━━━

📅 *Period 1:* {period1_desc}
📅 *Period 2:* {period2_desc}

🏨 *Overall Occupancy*
Period 1: {avg_occupancy_pct1}% ({round(avg_booked1, 1)}/{total_rooms} avg)
Period 2: {avg_occupancy_pct2}% ({round(avg_booked2, 1)}/{total_rooms} avg)
{change_emoji} Change: {change_sign}{change}%

📊 *By Room Type*
"""
        
        for rt_name in room_totals1.keys():
            if rt_name in room_totals2:
                rt_data1 = room_totals1[rt_name]
                rt_data2 = room_totals2[rt_name]
                
                avg_rt1 = rt_data1['booked'] / rt_data1['days'] if rt_data1['days'] > 0 else 0
                avg_rt2 = rt_data2['booked'] / rt_data2['days'] if rt_data2['days'] > 0 else 0
                
                pct1 = round((avg_rt1 / rt_data1['total'] * 100)) if rt_data1['total'] > 0 else 0
                pct2 = round((avg_rt2 / rt_data2['total'] * 100)) if rt_data2['total'] > 0 else 0
                
                rt_change = pct2 - pct1
                rt_emoji = "📈" if rt_change > 0 else "📉" if rt_change < 0 else "➡️"
                
                blocks1 = round(pct1 / 10)
                blocks2 = round(pct2 / 10)
                bar1 = "█" * blocks1 + "░" * (10 - blocks1)
                bar2 = "█" * blocks2 + "░" * (10 - blocks2)
                
                message += f"""
• *{rt_name}*
  P1: {bar1} {pct1}% ({round(avg_rt1, 1)}/{rt_data1['total']})
  P2: {bar2} {pct2}% ({round(avg_rt2, 1)}/{rt_data2['total']})
  {rt_emoji} Change: {rt_change:+d}%
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📅 Week over Week", "callback_data": "compare_week"},
                    {"text": "📅 Month over Month", "callback_data": "compare_month"}
                ],
                [
                    {"text": "🔄 Custom Compare", "callback_data": "compare_custom"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info("✅ Comparison report sent")
        
    except Exception as e:
        logger.error(f"Error in compare_occupancy: {e}", exc_info=True)
        pass

async def handle_occupancy_command(chat_id: int, args: str, db: Session):
    """Usage: /occupancy [date] or /occupancy [start_date] [end_date] - Show occupancy report"""
    from services.telegram import send_telegram_message as send_msg
    from datetime import datetime, date, timedelta
    
    parts = args.strip().split()
    
    if not parts:
        logger.info("No date provided, showing occupancy date picker")
        today = datetime.now().date()
        keyboard = {"inline_keyboard": []}
        row = []
        for i in range(7):
            pick_date = today + timedelta(days=i)
            date_str = pick_date.strftime("%Y-%m-%d")
            display = pick_date.strftime("%d %b")
            
            row.append({
                "text": display,
                "callback_data": f"occupancy_date_{date_str}"
            })
            
            if len(row) == 3 or i == 6:
                keyboard["inline_keyboard"].append(row)
                row = []
        
        keyboard["inline_keyboard"].append([
            {"text": "📅 Today", "callback_data": "occupancy_today"},
            {"text": "📅 This Week", "callback_data": "occupancy_week"},
            {"text": "📅 This Month", "callback_data": "occupancy_month"}
        ])
        keyboard["inline_keyboard"].append([
            {"text": "❌ Cancel", "callback_data": "occupancy_cancel"}
        ])
        
        await send_msg(
            chat_id,
            "📊 *Select Date for Occupancy Report*\n\nChoose a date or quick period:",
            reply_markup=keyboard
        )
        return
    
    try:
        from datetime import date as date_class
        
        if len(parts) == 1:
            check_date = date_class.fromisoformat(parts[0])
            await show_occupancy_for_date(chat_id, check_date, db)
            
        elif len(parts) == 2:
            start_date = date_class.fromisoformat(parts[0])
            end_date = date_class.fromisoformat(parts[1])
            
            if start_date > end_date:
                await send_msg(chat_id, "❌ Start date must be before end date.")
                return
            
            await show_occupancy_for_range(chat_id, start_date, end_date, db)
        else:
            await send_msg(chat_id, "❌ Invalid format. Use: /occupancy [date] or /occupancy [start] [end]")
            
    except ValueError as e:
        logger.error(f"Date parsing error: {e}")
        await send_msg(chat_id, "❌ Invalid date format. Use YYYY-MM-DD")

# ==================== ROOM TYPES OVERVIEW ====================
async def handle_roomtypes_command(chat_id: int, db: Session):
    """Show overview of all room types with current availability"""
    from services.telegram import send_telegram_message
    from services.availability import get_daily_occupancy
    from datetime import date
    
    logger.info(f"🏨 Processing roomtypes command for chat {chat_id}")
    
    hotel_id = 1
    today = date.today()
    
    try:
        occupancy = get_daily_occupancy(db, hotel_id, today, today)
        day_data = occupancy.get(today.isoformat(), {})
        
        if not day_data:
            await send_telegram_message(chat_id, "📊 No room type data found for today.")
            return
        
        message = f"""
🏨 *ROOM TYPES OVERVIEW*
━━━━━━━━━━━━━━━━━━━
📅 *Today:* {today.strftime('%d %b %Y')}

"""
        
        for rt_name, data in day_data.items():
            if data['total'] > 0:
                pct = round((data['booked'] / data['total'] * 100))
                blocks = round(pct / 10)
                bar = "█" * blocks + "░" * (10 - blocks)
                
                message += f"""
🛏 *{rt_name}* ({data['total']} rooms)
{bar} {pct}% full
• Available: {data['available']}
• Booked: {data['booked']}
• Guests: {data['guests']}
"""
        
        message += """
━━━━━━━━━━━━━━━━━━━
💡 *Quick Actions*
"""
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📅 Check Availability", "callback_data": "availability"},
                    {"text": "📊 Today's Occupancy", "callback_data": "occupancy_today"}
                ],
                [
                    {"text": "🔄 Refresh", "callback_data": "roomtypes"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info("✅ Room types overview sent successfully")
        
    except Exception as e:
        logger.error(f"Error in roomtypes command: {e}", exc_info=True)
        pass

# ==================== ARRIVALS COMMAND ====================
async def handle_arrivals_command(chat_id: int, db: Session):
    """Show today's check-ins only"""
    from services.telegram import send_telegram_message
    from datetime import date
    
    logger.info(f"🛬 Processing arrivals command for chat {chat_id}")
    
    today = date.today()
    
    try:
        arrivals = db.query(models.BookingRequest).filter(
            models.BookingRequest.arrival_date == today
        ).all()
        
        if not arrivals:
            await send_telegram_message(chat_id, f"📅 No check-ins scheduled for today ({today.strftime('%d %b %Y')}).")
            return
        
        message = f"""
🛬 *TODAY'S CHECK-INS*
━━━━━━━━━━━━━━━━━━━
📅 *Date:* {today.strftime('%d %b %Y')}
👥 *Total Guests:* {sum(b.number_of_guests for b in arrivals)}

"""
        
        for b in arrivals[:10]:
            message += f"• #{b.id}: {b.guest_name} - {b.room_type} ({b.number_of_guests} guests)\n"
        
        if len(arrivals) > 10:
            message += f"\n... and {len(arrivals) - 10} more"
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📋 All Today", "callback_data": "today"},
                    {"text": "🛫 Departures", "callback_data": "departures"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info("✅ Arrivals message sent successfully")
        
    except Exception as e:
        logger.error(f"Error in arrivals command: {e}", exc_info=True)
        pass

# ==================== DEPARTURES COMMAND ====================
async def handle_departures_command(chat_id: int, db: Session):
    """Show today's check-outs only"""
    from services.telegram import send_telegram_message
    from datetime import date
    
    logger.info(f"🛫 Processing departures command for chat {chat_id}")
    
    today = date.today()
    
    try:
        departures = db.query(models.BookingRequest).filter(
            models.BookingRequest.departure_date == today
        ).all()
        
        if not departures:
            await send_telegram_message(chat_id, f"📅 No check-outs scheduled for today ({today.strftime('%d %b %Y')}).")
            return
        
        message = f"""
🛫 *TODAY'S CHECK-OUTS*
━━━━━━━━━━━━━━━━━━━
📅 *Date:* {today.strftime('%d %b %Y')}
👥 *Total Guests:* {sum(b.number_of_guests for b in departures)}

"""
        
        for b in departures[:10]:
            message += f"• #{b.id}: {b.guest_name} - {b.room_type}\n"
        
        if len(departures) > 10:
            message += f"\n... and {len(departures) - 10} more"
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "📋 All Today", "callback_data": "today"},
                    {"text": "🛬 Arrivals", "callback_data": "arrivals"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info("✅ Departures message sent successfully")
        
    except Exception as e:
        logger.error(f"Error in departures command: {e}", exc_info=True)
        pass

# ==================== MENU COMMAND ====================
async def handle_menu_command(chat_id: int, db: Session):
    """Show main menu with all features"""
    from services.telegram import send_telegram_message
    from datetime import datetime
    
    logger.info(f"🎯 Processing menu command for chat {chat_id}")
    
    try:
        message = f"""
🤖 *THeO HOTEL BOT*
━━━━━━━━━━━━━━━━━━━
Welcome to your hotel management assistant!

*Quick Stats*
📅 {datetime.now().strftime('%d %b %Y, %H:%M')}
🏨 All systems operational

*What would you like to do?*
━━━━━━━━━━━━━━━━━━━
"""

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🏨 Status", "callback_data": "status"},
                    {"text": "📊 Stats", "callback_data": "stats"}
                ],
                [
                    {"text": "📅 Today", "callback_data": "today"},
                    {"text": "⏳ Pending", "callback_data": "pending"}
                ],
                [
                    {"text": "🛬 Arrivals", "callback_data": "arrivals"},
                    {"text": "🛫 Departures", "callback_data": "departures"}
                ],
                [
                    {"text": "📅 Availability", "callback_data": "availability"},
                    {"text": "📋 Bookings", "callback_data": "bookings"}
                ],
                [
                    {"text": "📊 Occupancy", "callback_data": "occupancy_today"},
                    {"text": "🏨 Room Types", "callback_data": "roomtypes"}
                ],
                [
                    {"text": "❓ Help", "callback_data": "help"}
                ]
            ]
        }
        
        await send_telegram_message(chat_id, message, reply_markup=keyboard)
        logger.info("✅ Menu sent successfully")
        
    except Exception as e:
        logger.error(f"Error in menu command: {e}", exc_info=True)
        pass

# ==================== NATURAL LANGUAGE HANDLER ====================
async def handle_natural_language(chat_id: int, text: str, db: Session):
    """Handle natural language queries"""
    from services.nlp_processor import nlp
    
    logger.info(f"🔍 Processing natural language: {text}")
    
    parsed = nlp.parse_query(text)
    logger.info(f"📊 Parsed result: {parsed}")
    
    if parsed['intent'] == 'availability':
        if parsed['dates']:
            check_date = parsed['dates'][0]
            room_type = parsed.get('room_type')
            
            if room_type:
                await handle_availability_command(chat_id, f"{check_date} {room_type}", db)
            else:
                await show_availability(chat_id, check_date, db)
        else:
            tomorrow = datetime.now().date() + timedelta(days=1)
            await show_availability(chat_id, tomorrow, db)
    
    elif parsed['intent'] == 'list_bookings':
        if len(parsed['dates']) >= 2:
            start, end = parsed['dates'][0], parsed['dates'][1]
            await handle_bookings_command(chat_id, f"{start} {end}", db)
        elif len(parsed['dates']) == 1:
            date = parsed['dates'][0]
            await handle_bookings_command(chat_id, f"{date} {date}", db)
        else:
            today = datetime.now().date()
            next_week = today + timedelta(days=7)
            await handle_bookings_command(chat_id, f"{today} {next_week}", db)
    
    elif parsed['intent'] == 'modify_booking':
        if parsed['booking_id']:
            await handle_modify_command(chat_id, str(parsed['booking_id']), db)
        else:
            await send_telegram_message(chat_id, 
                "I can help you modify a booking. Please provide the booking number.\n"
                "Example: `/modify 123` or 'Change booking #123'")
    
    elif parsed['intent'] == 'cancel_booking':
        if parsed['booking_id']:
            booking = db.query(models.ConfirmedBooking).filter(
                models.ConfirmedBooking.id == parsed['booking_id']
            ).first()
            
            if booking:
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
        if parsed['dates']:
            check_date = parsed['dates'][0]
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
        await handle_manager_question(chat_id, text, db)
    
    else:
        await send_telegram_message(chat_id,
            "🤔 I'm not sure I understood. Here's what I can help with:\n\n"
            "• Check availability: 'What rooms are free tomorrow?'\n"
            "• List bookings: 'Show bookings for next week'\n"
            "• Modify booking: 'Change booking #123'\n"
            "• Cancel booking: 'Cancel #456'\n"
            "• Guest counts: 'How many guests on Friday?'\n"
            "• Policies: 'Check-in time?' or 'Pet policy?'\n\n"
            "Or type /help to see all commands.")

# ==================== TEXT MESSAGE HANDLER ====================
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
        
        if hasattr(handle_modification_actions, "pending_rejections") and chat_id in handle_modification_actions.pending_rejections:
            modification_id = handle_modification_actions.pending_rejections.pop(chat_id)
            modification = db.query(models.ModificationRequest).filter(
                models.ModificationRequest.id == modification_id
            ).first()
            
            if modification:
                modification.status = "Rejected"
                modification.processed_at = datetime.utcnow()
                modification.modification_notes = text
                
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
        
        editing_booking = get_editing_booking(db)
        in_editing_mode = editing_booking is not None
        
        if text.startswith('/'):
            logger.info(f"Processing command: {text}")
            
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
                    booking = editing_booking
                    booking.status = "Pending"
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
            
            if in_editing_mode:
                await send_telegram_message(
                    chat_id,
                    f"❌ Command not available in edit mode.\n\nYou are currently editing Booking #{editing_booking.id}.\n\nType /cancel to exit edit mode or /help for available commands."
                )
                return {"status": "command_blocked"}
            
            if text == '/stats':
                await handle_stats_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/today':
                await handle_today_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/pending':
                await handle_pending_command(chat_id, db)
                return {"status": "command_processed"}
            elif text.startswith('/availability'):
                await handle_availability_command(chat_id, text[13:], db)
                return {"status": "command_processed"}
            elif text.startswith('/bookings'):
                await handle_bookings_command(chat_id, text[10:], db)
                return {"status": "command_processed"}
            elif text.startswith('/modify'):
                await handle_modify_command(chat_id, text[8:], db)
                return {"status": "command_processed"}
            elif text == '/status':
                await handle_status_command(chat_id, db)
                return {"status": "command_processed"}
            elif text.startswith('/occupancy'):
                await handle_occupancy_command(chat_id, text[11:], db)
                return {"status": "command_processed"}
            elif text == '/roomtypes':
                await handle_roomtypes_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/arrivals':
                await handle_arrivals_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/departures':
                await handle_departures_command(chat_id, db)
                return {"status": "command_processed"}
            elif text == '/menu' or text == '/start':
                await handle_menu_command(chat_id, db)
                return {"status": "command_processed"}
            else:
                await send_telegram_message(
                    chat_id, 
                    f"❌ Unknown command: {text}\n\nType /help for available commands."
                )
                return {"status": "command_processed"}
        
        if in_editing_mode:
            booking = editing_booking
            
            reply_to_message = message.get("reply_to_message")
            is_reply_to_edit = False
            
            if reply_to_message:
                reply_text = reply_to_message.get("text", "")
                if "EDITING MODE ACTIVATED" in reply_text or f"Booking #{booking.id}" in reply_text:
                    is_reply_to_edit = True
            
            if not is_reply_to_edit:
                warning = (
                    f"⚠️ *You're in edit mode*\n\n"
                    f"You are currently editing Booking #{booking.id}.\n\n"
                    f"Please reply to the edit instruction message with your revised draft.\n\n"
                    f"Type /cancel to exit edit mode."
                )
                await send_telegram_message(chat_id, warning)
                return {"status": "warning"}
            
            logger.info(f"Processing edit for booking #{booking.id}")
            booking.draft_reply = text
            booking.status = "Draft_Ready"
            db.commit()
            
            logger.info(f"Draft updated for booking #{booking.id}")
            
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
            
            try:
                delete_url = f"{TELEGRAM_API_URL}/deleteMessage"
                requests.post(delete_url, json={
                    "chat_id": chat_id,
                    "message_id": message_id
                }, timeout=5)
            except:
                pass
            
        else:
            logger.info("No booking in editing mode, trying natural language")
            from services.nlp_processor import nlp
            parsed = nlp.parse_query(text)
            
            if parsed['intent'] and parsed.get('confidence', 0) > 0.5:
                await handle_natural_language(chat_id, text, db)
            else:
                logger.info(f"Low confidence NLP match ({parsed.get('confidence', 0)}), falling back to Q&A")
                await handle_manager_question(chat_id, text, db)
        
        return {"status": "message_processed"}
        
    except Exception as e:
        logger.error(f"Error in handle_text_message: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

# ==================== MANAGER Q&A ====================
async def handle_manager_question(chat_id: int, question: str, db: Session):
    """Handle manager questions with predefined answers"""
    
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
    
    question_lower = question.lower()
    
    matched_answers = []
    for qa in qa_pairs:
        for keyword in qa["keywords"]:
            if keyword in question_lower:
                matched_answers.append(qa["answer"])
                break
    
    if matched_answers:
        unique_answers = list(dict.fromkeys(matched_answers))
        response = "📚 **Quick Answer:**\n\n" + "\n\n---\n\n".join(unique_answers)
        response += "\n\n💡 **Tip:** Use buttons on booking messages to manage specific reservations."
    else:
        response = (
            "🤔 I'm not sure about that. Here's what I can help with:\n\n"
            "• Booking status and management\n"
            "• Hotel policies (cancellation, check-in/out)\n"
            "• Facilities (parking, breakfast, wifi)\n"
            "• General hotel information\n\n"
            "Try asking about specific topics or use the buttons on booking messages."
        )
    
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

# ==================== STATISTICS COMMANDS ====================
async def handle_stats_command(chat_id: int, db: Session):
    """Handle /stats command"""
    try:
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
        logger.info("✅ Stats sent successfully")
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}", exc_info=True)
        pass

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
        for b in pending[:10]:
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
        "/modify <id> - Start modification for a confirmed booking\n"
        "/status - Hotel status dashboard\n\n"
        "**Availability & Reports:**\n"
        "/availability - Check room availability (interactive date picker)\n"
        "/bookings - List bookings in a date range (interactive date picker)\n"
        "/occupancy [date] - Show occupancy percentage with progress bars\n"
        "/roomtypes - List all room types with current availability\n"
        "/arrivals - Today's check-ins only\n"
        "/departures - Today's check-outs only\n\n"
        "**General:**\n"
        "/menu - Show main menu with buttons\n"
        "/help - Show this message\n\n"
        "**Sample Questions:**\n"
        "• \"What's the check-in time?\"\n"
        "• \"Do you have parking?\"\n"
        "• \"Cancellation policy?\"\n"
        "• \"Breakfast included?\"\n"
        "• \"Pet policy?\""
    )
    
    await send_telegram_message(chat_id, message)

# ==================== EDIT MESSAGE HELPER ====================
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