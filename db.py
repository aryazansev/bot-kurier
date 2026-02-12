import sqlite3


class DB:
    def __init__(self):
        self._db_path = 'db.sqlite3'
        db = sqlite3.connect('db.sqlite3')
        cursor = db.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS courier (chat_id INTEGER, courier_id INTEGER)")
        db.commit()

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
