import aiosqlite
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_PATH = 'bot.db'


async def init_db():
    """Инициализация базы данных с проверкой структуры"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица пользователей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица слотов
        await db.execute('''
            CREATE TABLE IF NOT EXISTS slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                day TEXT NOT NULL,
                time TEXT NOT NULL,
                available BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(date, time)
            )
        ''')

        # Таблица записей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                slot_id INTEGER NOT NULL,
                client_name TEXT NOT NULL,
                date TEXT,
                time TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reminder_24h_sent BOOLEAN DEFAULT 0,
                reminder_1h_sent BOOLEAN DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')

        # Таблица опросов
        await db.execute('''
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                yes_votes INTEGER DEFAULT 0,
                no_votes INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Таблица голосов
        await db.execute('''
            CREATE TABLE IF NOT EXISTS poll_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                vote TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(poll_id) REFERENCES polls(id) ON DELETE CASCADE,
                UNIQUE(poll_id, user_id)
            )
        ''')

        # Проверяем и добавляем недостающие колонки в таблицу appointments
        await add_missing_columns()

        await db.commit()
    logger.info("База данных инициализирована")


async def add_missing_columns():
    """Добавляем недостающие колонки в таблицу appointments"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверяем существующие колонки в таблице appointments
        cursor = await db.execute("PRAGMA table_info(appointments)")
        columns = await cursor.fetchall()
        column_names = [column[1] for column in columns]

        # Добавляем колонку date, если её нет
        if 'date' not in column_names:
            await db.execute("ALTER TABLE appointments ADD COLUMN date TEXT")
            logger.info("Добавлена колонка date в таблицу appointments")

        # Добавляем колонку time, если её нет
        if 'time' not in column_names:
            await db.execute("ALTER TABLE appointments ADD COLUMN time TEXT")
            logger.info("Добавлена колонка time в таблицу appointments")

        # Добавляем колонки для напоминаний
        if 'reminder_24h_sent' not in column_names:
            await db.execute("ALTER TABLE appointments ADD COLUMN reminder_24h_sent BOOLEAN DEFAULT 0")
            logger.info("Добавлена колонка reminder_24h_sent в таблицу appointments")

        if 'reminder_1h_sent' not in column_names:
            await db.execute("ALTER TABLE appointments ADD COLUMN reminder_1h_sent BOOLEAN DEFAULT 0")
            logger.info("Добавлена колонка reminder_1h_sent в таблицу appointments")

        await db.commit()


# Пользователи
async def add_user(user_id, username, first_name, phone):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, username, first_name, phone) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, phone)
        )
        await db.commit()


async def get_user(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return await cursor.fetchone()


async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users")
        return await cursor.fetchall()


# Слоты
async def add_slot(date, day, time):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO slots (date, day, time) VALUES (?, ?, ?)",
                (date, day, time)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_available_slots():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM slots WHERE available = 1 ORDER BY date, time"
        )
        return await cursor.fetchall()


async def get_slots_by_date(date):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM slots WHERE date = ? ORDER BY time", (date,)
        )
        return await cursor.fetchall()


async def get_all_slots_by_date(date):
    """Получает ВСЕ слоты на дату (и доступные и занятые)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM slots WHERE date = ? ORDER BY time", (date,)
        )
        return await cursor.fetchall()


async def get_slot(slot_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM slots WHERE id = ?", (slot_id,))
        return await cursor.fetchone()


async def delete_slot(slot_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM slots WHERE id = ?", (slot_id,))
        await db.commit()


async def update_slot_availability(slot_id, available):
    """Обновляет доступность слота"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE slots SET available = ? WHERE id = ?",
            (available, slot_id)
        )
        await db.commit()


async def get_all_dates():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT DISTINCT date, day FROM slots WHERE available = 1 ORDER BY date"
        )
        return await cursor.fetchall()


async def get_all_dates_with_slots():
    """Получает ВСЕ даты со слотами (и доступные и занятые)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT DISTINCT date, day FROM slots ORDER BY date"
        )
        return await cursor.fetchall()


async def get_dates_with_appointments():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT DISTINCT a.date
            FROM appointments a 
            WHERE a.date IS NOT NULL
            ORDER BY a.date
        ''')
        return await cursor.fetchall()


# Записи
async def add_appointment(user_id, slot_id, client_name, date, time):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            # Добавляем запись
            await db.execute(
                "INSERT INTO appointments (user_id, slot_id, client_name, date, time) VALUES (?, ?, ?, ?, ?)",
                (user_id, slot_id, client_name, date, time)
            )
            # Помечаем слот как недоступный
            await db.execute(
                "UPDATE slots SET available = 0 WHERE id = ?",
                (slot_id,)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def get_user_appointments(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT a.id, a.date, a.time, a.client_name, a.slot_id, a.reminder_24h_sent, a.reminder_1h_sent
            FROM appointments a
            WHERE a.user_id = ? AND a.date IS NOT NULL AND a.time IS NOT NULL
            ORDER BY a.date, a.time
        ''', (user_id,))
        return await cursor.fetchall()


async def get_appointment(appointment_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT a.*, u.username, u.first_name, u.phone
            FROM appointments a
            JOIN users u ON a.user_id = u.user_id
            WHERE a.id = ?
        ''', (appointment_id,))
        return await cursor.fetchone()


async def get_appointment_by_slot_id(slot_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT a.*, u.username, u.first_name, u.phone
            FROM appointments a
            JOIN users u ON a.user_id = u.user_id
            WHERE a.slot_id = ?
        ''', (slot_id,))
        return await cursor.fetchone()


async def delete_appointment(appointment_id, user_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем slot_id перед удалением записи
        if user_id:
            # С проверкой прав доступа
            cursor = await db.execute(
                "SELECT slot_id FROM appointments WHERE id = ? AND user_id = ?",
                (appointment_id, user_id)
            )
        else:
            # Без проверки прав (для админа)
            cursor = await db.execute("SELECT slot_id FROM appointments WHERE id = ?", (appointment_id,))

        result = await cursor.fetchone()

        if result:
            slot_id = result[0]
            # Удаляем запись
            if user_id:
                await db.execute(
                    "DELETE FROM appointments WHERE id = ? AND user_id = ?",
                    (appointment_id, user_id)
                )
            else:
                await db.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))

            # Делаем слот снова доступным
            await db.execute("UPDATE slots SET available = 1 WHERE id = ?", (slot_id,))
            await db.commit()
            return True
        return False


async def get_appointments_by_date(date):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT a.id, a.time, u.username, u.first_name, u.phone, a.client_name
            FROM appointments a
            JOIN users u ON a.user_id = u.user_id
            WHERE a.date = ?
            ORDER BY a.time
        ''', (date,))
        return await cursor.fetchall()


async def get_appointments_for_reminders():
    """Получает записи, для которых нужно отправить напоминания"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute('''
            SELECT a.*, u.user_id, u.username, u.phone
            FROM appointments a
            JOIN users u ON a.user_id = u.user_id
            WHERE a.date IS NOT NULL AND a.time IS NOT NULL
        ''')
        return await cursor.fetchall()


async def update_reminder_status(appointment_id, reminder_type, sent=True):
    """Обновляет статус отправки напоминания"""
    async with aiosqlite.connect(DB_PATH) as db:
        if reminder_type == '24h':
            await db.execute(
                "UPDATE appointments SET reminder_24h_sent = ? WHERE id = ?",
                (1 if sent else 0, appointment_id)
            )
        elif reminder_type == '1h':
            await db.execute(
                "UPDATE appointments SET reminder_1h_sent = ? WHERE id = ?",
                (1 if sent else 0, appointment_id)
            )
        await db.commit()


# Опросы
async def create_poll(question):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("INSERT INTO polls (question) VALUES (?)", (question,))
        await db.commit()
        return cursor.lastrowid


async def get_poll(poll_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,))
        return await cursor.fetchone()


async def get_all_polls():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM polls ORDER BY created_at DESC")
        return await cursor.fetchall()


async def add_vote(poll_id, user_id, vote):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Проверяем существующий голос
        cursor = await db.execute(
            "SELECT * FROM poll_votes WHERE poll_id = ? AND user_id = ?",
            (poll_id, user_id)
        )
        existing = await cursor.fetchone()

        if existing:
            old_vote = existing['vote']
            # Уменьшаем старый голос
            if old_vote == 'yes':
                await db.execute("UPDATE polls SET yes_votes = yes_votes - 1 WHERE id = ?", (poll_id,))
            else:
                await db.execute("UPDATE polls SET no_votes = no_votes - 1 WHERE id = ?", (poll_id,))

            # Обновляем голос
            await db.execute(
                "UPDATE poll_votes SET vote = ? WHERE poll_id = ? AND user_id = ?",
                (vote, poll_id, user_id)
            )
        else:
            # Новый голос
            await db.execute(
                "INSERT INTO poll_votes (poll_id, user_id, vote) VALUES (?, ?, ?)",
                (poll_id, user_id, vote)
            )

        # Увеличиваем новый голос
        if vote == 'yes':
            await db.execute("UPDATE polls SET yes_votes = yes_votes + 1 WHERE id = ?", (poll_id,))
        else:
            await db.execute("UPDATE polls SET no_votes = no_votes + 1 WHERE id = ?", (poll_id,))

        await db.commit()
        return True
