import os
import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

message = "سلام! تست اتصال ربات AyarenginBot از طریق GitHub Actions موفقیت‌آمیز بود. ✅"

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
payload = {"chat_id": CHAT_ID, "text": message}

response = requests.post(url, json=payload)
print("Response:", response.json())
