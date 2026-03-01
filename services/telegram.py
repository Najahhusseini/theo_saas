import requests
import os
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")

if not BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN not set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_telegram_message(chat_id: str, message: str, reply_markup: dict = None):
    """Send a message to a Telegram chat with error handling"""
    
    # If no chat_id provided, use manager's chat ID
    if not chat_id:
        chat_id = MANAGER_CHAT_ID
        logger.info(f"No chat_id provided, using manager chat ID: {chat_id}")
    
    if not chat_id:
        logger.error("No chat_id provided and MANAGER_CHAT_ID not set")
        return None
    
    url = f"{TELEGRAM_API_URL}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        logger.info(f"Sending message to chat_id: {chat_id}")
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )
        
        response_data = response.json()
        logger.info(f"Telegram status: {response.status_code}")
        logger.info(f"Telegram response: {response_data}")
        
        if not response_data.get("ok"):
            logger.error(f"Telegram API error: {response_data.get('description')}")
            
            # If chat not found, log detailed error
            if response_data.get("error_code") == 400 and "chat not found" in response_data.get("description", ""):
                logger.error(f"Chat ID {chat_id} not found. Make sure the bot has been started by this user and the ID is correct.")
                logger.error("To fix this: 1. Message your bot first, 2. Run test_telegram.py to get correct chat ID")
        
        return response_data
        
    except requests.exceptions.Timeout:
        logger.error("Telegram request timed out")
        return None
    except Exception as e:
        logger.error(f"Telegram failed: {str(e)}")
        return None

def send_booking_to_manager(booking):
    """Send booking details to manager (uses default manager chat ID)"""
    message = f"""
🏨 <b>New Booking Request #{booking.id}</b>

👤 <b>Guest:</b> {booking.guest_name}
📧 <b>Email:</b> {booking.email}

🛏 <b>Room:</b> {booking.room_type}
📅 <b>Arrival:</b> {booking.arrival_date}
📅 <b>Departure:</b> {booking.departure_date}

🔢 <b>Rooms:</b> {booking.number_of_rooms}
👥 <b>Guests:</b> {booking.number_of_guests}

📝 <b>Special Requests:</b>
{booking.special_requests or "None"}

📌 <b>Status:</b> {booking.status}
"""

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Confirm", "callback_data": f"confirm_{booking.id}"},
                {"text": "❌ Reject", "callback_data": f"reject_{booking.id}"},
                {"text": "⏳ Waitlist", "callback_data": f"waitlist_{booking.id}"}
            ]
        ]
    }

    return send_telegram_message(MANAGER_CHAT_ID, message, reply_markup=keyboard)

def send_draft_for_approval(booking, decision: str, draft: str):
    """Send the AI-generated draft to manager for approval"""
    message = f"""
📝 <b>Draft Email for Booking #{booking.id}</b>

<b>Decision:</b> {decision}

<b>Draft:</b>
<pre>{draft}</pre>

<b>Guest:</b> {booking.guest_name}
<b>Email:</b> {booking.email}
"""

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✏️ Edit Draft", "callback_data": f"edit_{booking.id}"},
                {"text": "📤 Send Email", "callback_data": f"send_{booking.id}"}
            ],
            [
                {"text": "❌ Cancel", "callback_data": f"cancel_{booking.id}"}
            ]
        ]
    }

    return send_telegram_message(MANAGER_CHAT_ID, message, reply_markup=keyboard)