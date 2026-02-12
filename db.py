import sqlite3
from datetime import datetime, timedelta
import random


MOTIVATIONAL_PHRASES = [
    "Отличная работа! Так держать! 🎉",
    "Супер! Клиент точно доволен! ⭐",
    "Молодец! Еще один довольный клиент! 🚀",
    "Отлично справились! 💪",
    "Прекрасная работа! Ты настоящий профи! 🌟",
    "Великолепно! Продолжай в том же духе! 🔥",
    "Так держать! Ты лучший! 👍",
    "Отличный результат! Клиент счастлив! 😊",
    "Профессионально выполнено! 👏",
    "Ты сегодня на высоте! 🎯",
    "Идеальная доставка! 🏆",
    "Клиент в восторге! Спасибо за работу! 🌈",
    "Отличный темп! Ты делаешь мир лучше! ⚡",
    "Блестяще! Продолжай радовать клиентов! 💫",
    "Ты звезда доставки! ⭐",
]


class DB:
    def __init__(self):
        self._db_path = 'db.sqlite3'
        self._init_db()

    def _init_db(self):
        """Initialize database tables"""
        db = sqlite3.connect(self._db_path)
        cursor = db.cursor()
        
        # Table for courier chat_id to courier_id mapping
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS courier (
                chat_id INTEGER PRIMARY KEY, 
                courier_id INTEGER
            )
        """)
        
        # Table for completed orders
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS completed_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                courier_id INTEGER,
                order_id TEXT,
                order_number TEXT,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        db.commit()
        db.close()

    def get_courier_id(self, chat_id):
        db = sqlite3.connect(self._db_path)
        cursor = db.cursor()
        cursor.execute("SELECT courier_id FROM courier WHERE chat_id = ?", (chat_id,))

        courier_id = cursor.fetchone()
        db.close()

        if courier_id is None:
            return None
        return courier_id[0]

    def add_courier(self, chat_id, courier_id):
        db = sqlite3.connect(self._db_path)
        cursor = db.cursor()
        cursor.execute("DELETE FROM courier WHERE courier_id = ?", (courier_id,))
        cursor.execute("DELETE FROM courier WHERE chat_id = ?", (chat_id,))
        cursor.execute("INSERT INTO courier (chat_id, courier_id) VALUES (?, ?)", (chat_id, courier_id))
        db.commit()
        db.close()

    def add_completed_order(self, courier_id, order_id, order_number):
        """Add a completed order to the database"""
        db = sqlite3.connect(self._db_path)
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO completed_orders (courier_id, order_id, order_number) VALUES (?, ?, ?)",
            (courier_id, order_id, order_number)
        )
        db.commit()
        db.close()

    def get_completed_orders_count(self, courier_id, period='day'):
        """Get count of completed orders for a courier in a given period
        
        Args:
            courier_id: ID of the courier
            period: 'day', 'week', or 'month'
        """
        db = sqlite3.connect(self._db_path)
        cursor = db.cursor()
        
        now = datetime.now()
        
        if period == 'day':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = now - timedelta(days=now.weekday())
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        cursor.execute(
            "SELECT COUNT(*) FROM completed_orders WHERE courier_id = ? AND completed_at >= ?",
            (courier_id, start_date)
        )
        
        count = cursor.fetchone()[0]
        db.close()
        return count

    def get_top_couriers(self, period='day', limit=10):
        """Get top couriers by completed orders for a period"""
        db = sqlite3.connect(self._db_path)
        cursor = db.cursor()
        
        now = datetime.now()
        
        if period == 'day':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = now - timedelta(days=now.weekday())
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'month':
            start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        cursor.execute(
            """
            SELECT courier_id, COUNT(*) as order_count 
            FROM completed_orders 
            WHERE completed_at >= ? 
            GROUP BY courier_id 
            ORDER BY order_count DESC 
            LIMIT ?
            """,
            (start_date, limit)
        )
        
        results = cursor.fetchall()
        db.close()
        return results

    def get_random_motivational_phrase(self):
        """Get a random motivational phrase"""
        return random.choice(MOTIVATIONAL_PHRASES)
