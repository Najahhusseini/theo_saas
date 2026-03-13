import os
from dotenv import load_dotenv

load_dotenv()
print("DATABASE_URL =", os.getenv("DATABASE_URL"))
print("TELEGRAM_BOT_TOKEN =", os.getenv("TELEGRAM_BOT_TOKEN")[:10] + "..." if os.getenv("TELEGRAM_BOT_TOKEN") else "Not set")
print("MANAGER_CHAT_ID =", os.getenv("MANAGER_CHAT_ID"))