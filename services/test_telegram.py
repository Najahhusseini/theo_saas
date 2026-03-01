# test_telegram.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MANAGER_CHAT_ID = os.getenv("MANAGER_CHAT_ID")

def test_bot():
    print(f"Bot Token: {BOT_TOKEN[:10]}...{BOT_TOKEN[-5:] if BOT_TOKEN else 'NOT SET'}")
    print(f"Manager Chat ID: {MANAGER_CHAT_ID}")
    
    # Test 1: Get bot info
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
    response = requests.get(url)
    print("\n1. Bot Info:", response.json())
    
    # Test 2: Get updates (to see if bot has received any messages)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    response = requests.get(url)
    print("\n2. Recent Updates:", response.json())
    
    # Test 3: Try to send a message
    if MANAGER_CHAT_ID:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": MANAGER_CHAT_ID,
            "text": "🔧 Test message from THEO bot"
        }
        response = requests.post(url, json=payload)
        print("\n3. Send Message Result:", response.json())

if __name__ == "__main__":
    test_bot()