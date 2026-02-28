from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from database import get_db
import models
from services.ai_drafts import generate_reply_draft
from services.telegram import send_telegram_message

import requests
import os

router = APIRouter()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()

    # ==========================
    # HANDLE CALLBACK BUTTONS
    # ==========================
    if "callback_query" in data:
        callback = data["callback_query"]
        callback_data = callback["data"]
        chat_id = callback["message"]["chat"]["id"]

        # Answer callback (VERY IMPORTANT)
        callback_id = callback["id"]
        try:
           requests.post(
           f"{TELEGRAM_API_URL}/answerCallbackQuery",
           json={"callback_query_id": callback_id},
           timeout=5
           )
        except Exception as e:
                print("Telegram callback answer failed:", e)

        action, booking_id = callback_data.split("_")
        booking_id = int(booking_id)

        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.id == booking_id
        ).first()

        if not booking:
            send_telegram_message(chat_id, "❌ Booking not found.")
            return {"status": "error"}

        if action == "edit":
            booking.status = "Editing"
            db.commit()

            send_telegram_message(
                chat_id,
                "✏️ Send the updated draft message now."
            )

        return {"status": "callback_processed"}

    # ==========================
    # HANDLE TEXT MESSAGES
    # ==========================
    if "message" in data:
        message = data["message"]

        if "text" not in message:
            return {"status": "ignored_non_text"}

        chat_id = message["chat"]["id"]
        text = message["text"]

        booking = db.query(models.BookingRequest).filter(
            models.BookingRequest.status == "Editing"
        ).order_by(models.BookingRequest.id.desc()).first()

        if booking:
            booking.ai_draft_email = text
            booking.status = "Confirmed"
            db.commit()

            send_telegram_message(chat_id, "✅ Draft updated successfully.")
        else:
            send_telegram_message(chat_id, "⚠️ No booking is currently being edited.")

        return {"status": "message_processed"}

    # ==========================
    # IGNORE EVERYTHING ELSE
    # ==========================
    return {"status": "ignored_update"}