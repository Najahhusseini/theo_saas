import requests
import os
import json

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN not set")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_telegram_message(chat_id: str, message: str, reply_markup: dict = None):
    url = f"{TELEGRAM_API_URL}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        print("Telegram status:", response.status_code)
        print("Telegram response:", response.text)

        return response.json()

    except Exception as e:
        print("⚠️ Telegram failed:", str(e))
        return None


def send_booking_to_manager(chat_id: str, booking):
    message = f"""
🏨 <b>New Booking Request</b>

👤 <b>Guest:</b> {booking.guest_name}
📧 <b>Email:</b> {booking.email}

🛏 <b>Room:</b> {booking.room_type}
📅 <b>Arrival:</b> {booking.arrival_date}
📅 <b>Departure:</b> {booking.departure_date}

🔢 <b>Rooms:</b> {booking.number_of_rooms}
👥 <b>Guests:</b> {booking.number_of_guests}

📝 <b>Special Requests:</b>
{booking.special_requests or "None"}

📨 <b>Original Email:</b>
{(booking.raw_email[:3500] + "...(truncated)") if booking.raw_email and len(booking.raw_email) > 3500 else booking.raw_email or "No email content stored"}

📌 <b>Status:</b> {booking.status}
"""

    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Confirm",
                    "callback_data": f"confirm_{booking.id}"
                },
                {
                    "text": "❌ Reject",
                    "callback_data": f"reject_{booking.id}"
                },
                {
                    "text": "⏳ Waitlist",
                    "callback_data": f"waitlist_{booking.id}"
                }
            ]
        ]
    }

    return send_telegram_message(chat_id, message, reply_markup=keyboard)