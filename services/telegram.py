import requests
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")

if not BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN not set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ====================== HELPER FUNCTIONS ======================

def format_date(date_obj):
    """Format date in a readable way"""
    if isinstance(date_obj, str):
        return date_obj
    return date_obj.strftime("%d %b %Y") if hasattr(date_obj, 'strftime') else str(date_obj)

def create_booking_header(booking):
    """Create consistent header for booking messages"""
    status_emoji = {
        "Pending": "⏳",
        "Confirmed": "✅",
        "Waitlist": "⏱",
        "Rejected": "❌",
        "Editing": "✏️",
        "Draft_Ready": "📝",
        "Email_Sent": "📧"
    }
    emoji = status_emoji.get(booking.status, "🆕")
    
    return f"{emoji} *Booking #{booking.id}* | {booking.guest_name}"

# ====================== MAIN MESSAGING FUNCTIONS ======================

def send_telegram_message(chat_id: str, message: str, reply_markup: dict = None, parse_mode: str = "Markdown"):
    """Send a message to a Telegram chat with error handling"""
    
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
        "parse_mode": parse_mode
    }
    
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        logger.info(f"Sending message to chat_id: {chat_id}")
        response = requests.post(url, json=payload, timeout=15)
        response_data = response.json()
        
        if response.status_code == 200:
            logger.info("✅ Message sent successfully")
        else:
            logger.error(f"❌ Telegram API error: {response_data.get('description')}")
        
        return response_data
        
    except Exception as e:
        logger.error(f"❌ Telegram failed: {str(e)}")
        return None

def send_booking_to_manager(booking):
    """Send new booking notification to manager with professional formatting"""
    
    # Format dates
    arrival = format_date(booking.arrival_date)
    departure = format_date(booking.departure_date)
    created = format_date(booking.created_at) if hasattr(booking, 'created_at') else "Just now"
    
    # Calculate stay duration
    if hasattr(booking.arrival_date, 'strftime') and hasattr(booking.departure_date, 'strftime'):
        stay_nights = (booking.departure_date - booking.arrival_date).days
        stay_text = f"{stay_nights} night{'s' if stay_nights != 1 else ''}"
    else:
        stay_text = "Stay period"
    
    # Professional message template
    message = f"""
🏨 *NEW BOOKING REQUEST* #{booking.id}

━━━━━━━━━━━━━━━━━━━

👤 *Guest Information*
• Name: {booking.guest_name}
• Email: `{booking.email}`
• Status: ⏳ Pending

📅 *Stay Details*
• Check-in: {arrival}
• Check-out: {departure}
• Duration: {stay_text}

🛏 *Room Details*
• Type: {booking.room_type}
• Rooms: {booking.number_of_rooms}
• Guests: {booking.number_of_guests}

📝 *Special Requests*
{booking.special_requests or "─ No special requests ─"}

📎 *Reference*
• Request ID: `#{booking.id}`
• Received: {created}

━━━━━━━━━━━━━━━━━━━
👇 *Select an action below*
"""
    # Professional inline keyboard
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ CONFIRM", "callback_data": f"confirm_{booking.id}"},
                {"text": "⏱ WAITLIST", "callback_data": f"waitlist_{booking.id}"},
                {"text": "❌ REJECT", "callback_data": f"reject_{booking.id}"}
            ],
            [
                {"text": "📋 VIEW DETAILS", "callback_data": f"details_{booking.id}"}
            ]
        ]
    }

    return send_telegram_message(MANAGER_CHAT_ID, message, reply_markup=keyboard)

def send_draft_for_approval(booking, decision: str, draft: str):
    """Send AI-generated draft for manager approval with professional formatting"""
    
    # Decision color coding
    decision_colors = {
        "Confirm": "✅",
        "Reject": "❌", 
        "Waitlist": "⏱"
    }
    emoji = decision_colors.get(decision, "📝")
    
    # Format dates
    arrival = format_date(booking.arrival_date)
    departure = format_date(booking.departure_date)
    
    message = f"""
{emoji} *DRAFT EMAIL - {decision.upper()}* | Booking #{booking.id}

━━━━━━━━━━━━━━━━━━━

📧 *Email Preview*
```{draft}```

━━━━━━━━━━━━━━━━━━━

👤 *Guest:* {booking.guest_name}
📧 *Email:* `{booking.email}`
📅 *Stay:* {arrival} → {departure}
🛏 *Room:* {booking.room_type}

━━━━━━━━━━━━━━━━━━━
👇 *Review and choose action*
"""
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✏️ EDIT DRAFT", "callback_data": f"edit_{booking.id}"},
                {"text": "📧 SEND EMAIL", "callback_data": f"send_{booking.id}"}
            ],
            [
                {"text": "❌ CANCEL", "callback_data": f"cancel_{booking.id}"}
            ]
        ]
    }

    return send_telegram_message(MANAGER_CHAT_ID, message, reply_markup=keyboard)

# ====================== COMMAND RESPONSES ======================

def send_welcome_message(chat_id: str):
    """Send welcome message when bot is started"""
    message = """
🤖 *Welcome to THeO Hotel Automation System*

━━━━━━━━━━━━━━━━━━━

I'm your AI-powered booking assistant. I'll help you manage all hotel booking requests efficiently.

*✨ What I can do for you:*

📨 *Booking Management*
• Receive new booking requests instantly
• Confirm, waitlist, or reject bookings
• AI-generated email drafts

📊 *Statistics & Reports*
• View booking statistics
• Check today's arrivals
• See pending bookings

❓ *Quick Answers*
• Hotel policies (check-in/out, cancellation)
• Facilities information
• Pricing and availability

━━━━━━━━━━━━━━━━━━━
*Commands:*
/stats - View dashboard statistics
/today - See today's arrivals
/pending - List pending bookings
/help - Show this message again

*Or simply ask me a question!*
"""
    return send_telegram_message(chat_id, message)

def send_stats_dashboard(chat_id: str, stats: dict):
    """Send professional statistics dashboard"""
    message = f"""
📊 *BOOKING DASHBOARD*

━━━━━━━━━━━━━━━━━━━

*Overview*
• Total Bookings: `{stats['total']}`
• Response Rate: `{stats.get('response_rate', 'N/A')}`

━━━━━━━━━━━━━━━━━━━

*Status Breakdown*

✅ Confirmed: `{stats['confirmed']}`
⏳ Pending: `{stats['pending']}`
⏱ Waitlist: `{stats['waitlist']}`
❌ Rejected: `{stats['rejected']}`
📝 Draft Ready: `{stats['draft_ready']}`
📧 Email Sent: `{stats['email_sent']}`

━━━━━━━━━━━━━━━━━━━

*Today's Activity*
• Arrivals: `{stats['today_arrivals']}`
• Departures: `{stats['today_departures']}`

📅 *Updated:* {datetime.now().strftime("%d %b %Y, %I:%M %p")}
"""
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔄 REFRESH", "callback_data": "stats"},
                {"text": "📅 TODAY", "callback_data": "today"}
            ]
        ]
    }
    
    return send_telegram_message(chat_id, message, reply_markup=keyboard)

def send_today_summary(chat_id: str, arrivals: list, departures: list):
    """Send professional today's summary"""
    today = datetime.now().strftime("%d %b %Y")
    
    message = f"""
📅 *TODAY'S OVERVIEW* | {today}

━━━━━━━━━━━━━━━━━━━
"""
    # Arrivals section
    if arrivals:
        message += f"\n*🛬 Arrivals ({len(arrivals)})*\n"
        for booking in arrivals[:5]:
            message += f"• #{booking.id}: {booking.guest_name} - {booking.room_type}\n"
        if len(arrivals) > 5:
            message += f"  ... and {len(arrivals) - 5} more\n"
    else:
        message += "\n🛬 *Arrivals:* No arrivals today\n"
    
    # Departures section
    if departures:
        message += f"\n*🛫 Departures ({len(departures)})*\n"
        for booking in departures[:5]:
            message += f"• #{booking.id}: {booking.guest_name}\n"
        if len(departures) > 5:
            message += f"  ... and {len(departures) - 5} more\n"
    else:
        message += "\n🛫 *Departures:* No departures today\n"
    
    # Occupancy info
    total_rooms = len(arrivals)  # This should be calculated properly
    message += f"""
━━━━━━━━━━━━━━━━━━━
*Current Status*
• Check-ins: {len(arrivals)}
• Check-outs: {len(departures)}
• Net change: {len(arrivals) - len(departures)}
"""
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 STATS", "callback_data": "stats"},
                {"text": "⏳ PENDING", "callback_data": "pending"}
            ]
        ]
    }
    
    return send_telegram_message(chat_id, message, reply_markup=keyboard)

def send_booking_details(chat_id: str, booking):
    """Send comprehensive booking details"""
    
    # Format dates
    arrival = format_date(booking.arrival_date)
    departure = format_date(booking.departure_date)
    created = format_date(booking.created_at) if hasattr(booking, 'created_at') else "N/A"
    
    # Status emoji
    status_emoji = {
        "Pending": "⏳",
        "Confirmed": "✅",
        "Waitlist": "⏱",
        "Rejected": "❌",
        "Editing": "✏️",
        "Draft_Ready": "📝",
        "Email_Sent": "📧"
    }
    status_icon = status_emoji.get(booking.status, "🆕")
    
    message = f"""
📋 *BOOKING DETAILS* #{booking.id}

━━━━━━━━━━━━━━━━━━━

*Status:* {status_icon} {booking.status}

━━━━━━━━━━━━━━━━━━━

👤 *GUEST INFORMATION*
• Name: {booking.guest_name}
• Email: `{booking.email}`

📅 *STAY DETAILS*
• Check-in: {arrival}
• Check-out: {departure}
• Nights: {booking.number_of_rooms} room(s)
• Guests: {booking.number_of_guests}

🛏 *ROOM INFORMATION*
• Type: {booking.room_type}
• Room Class: {getattr(booking, 'room_class', 'Standard')}

📝 *SPECIAL REQUESTS*
{booking.special_requests or "─ No special requests ─"}

📎 *SYSTEM INFORMATION*
• Request ID: `#{booking.id}`
• Created: {created}
• Last Updated: {booking.updated_at if hasattr(booking, 'updated_at') else created}

━━━━━━━━━━━━━━━━━━━
*Current Draft:*
```{booking.draft_reply or "No draft generated yet"}```
"""
    
    # Contextual actions based on status
    keyboard_buttons = []
    
    if booking.status == "Draft_Ready":
        keyboard_buttons = [
            [
                {"text": "📧 SEND EMAIL", "callback_data": f"send_{booking.id}"},
                {"text": "✏️ EDIT", "callback_data": f"edit_{booking.id}"}
            ]
        ]
    elif booking.status in ["Pending", "Editing"]:
        keyboard_buttons = [
            [
                {"text": "✅ CONFIRM", "callback_data": f"confirm_{booking.id}"},
                {"text": "⏱ WAITLIST", "callback_data": f"waitlist_{booking.id}"}
            ],
            [
                {"text": "❌ REJECT", "callback_data": f"reject_{booking.id}"}
            ]
        ]
    
    if keyboard_buttons:
        keyboard = {"inline_keyboard": keyboard_buttons}
        return send_telegram_message(chat_id, message, reply_markup=keyboard)
    else:
        return send_telegram_message(chat_id, message)