#!/usr/bin/env python3
"""
Скрипт для остановки бота и очистки webhook.
Запустите этот скрипт, если получаете ошибку 409 (Conflict).
"""
import os
import sys
from dotenv import load_dotenv
import telebot

load_dotenv()

token = os.getenv('TG_TOKEN')
if not token:
    print("Ошибка: TG_TOKEN не найден в .env")
    sys.exit(1)

print("Удаление webhook и сброс pending updates...")
bot = telebot.TeleBot(token)

try:
    # Remove webhook and drop all pending updates
    bot.remove_webhook(drop_pending_updates=True)
    print("✓ Webhook удален")
    print("✓ Pending updates очищены")
    print("\nБот остановлен. Теперь можно запустить новый экземпляр.")
except Exception as e:
    print(f"Ошибка: {e}")
    sys.exit(1)
