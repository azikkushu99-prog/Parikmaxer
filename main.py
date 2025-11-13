import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter, TelegramBadRequest
import asyncio
import db
from admin import admin_router, get_admin_keyboard
from datetime import datetime, timedelta
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = "8128570631:AAFhVFcNneJJHYEdkFzTcJXWnl_9rixS5tM"
ADMIN_IDS = [785219206, 5176507854]

# Создаем бота с увеличенным таймаутом
bot = Bot(token=TOKEN, timeout=60)
dp = Dispatcher()

# Включаем роутеры
dp.include_router(admin_router)


# Состояния FSM
class UserStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_name = State()


# Функция для повторных попыток при сетевых ошибках
async def safe_edit_message(message: types.Message, text: str, reply_markup=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            await message.edit_text(text, reply_markup=reply_markup)
            return True
        except (TelegramNetworkError, TelegramRetryAfter) as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Экспоненциальная backoff
                logger.warning(f"Сетевая ошибка, повтор через {wait_time} сек: {e}")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Не удалось отредактировать сообщение после {max_retries} попыток: {e}")
                return False
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            return False
    return False


# Клавиатуры
def get_phone_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# Инлайн-клавиатура главного меню
def get_main_inline_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✂️ Записаться на стрижку", callback_data="book_haircut")
    builder.button(text="📋 Мои записи", callback_data="my_appointments")
    builder.adjust(1)
    return builder.as_markup()


# Клавиатура с кнопкой Назад в главное меню
def get_back_to_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад в меню", callback_data="back_to_main")
    return builder.as_markup()


# Клавиатура с кнопкой Назад к выбору даты
def get_back_to_dates_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к датам", callback_data="back_to_dates")
    return builder.as_markup()


# Клавиатура с кнопкой Назад к записям
def get_back_to_appointments_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к записям", callback_data="back_to_appointments")
    return builder.as_markup()


# Клавиатура для отмены ввода имени
def get_cancel_name_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_name_input")
    return builder.as_markup()


# Сервис напоминаний
async def check_reminders():
    """Проверяет и отправляет напоминания о записях"""
    while True:
        try:
            appointments = await db.get_appointments_for_reminders()
            now = datetime.now()

            for appointment in appointments:
                try:
                    # Парсим дату и время записи
                    appointment_datetime = parse_appointment_datetime(appointment['date'], appointment['time'])
                    if not appointment_datetime:
                        continue

                    # Вычисляем точное время для напоминаний
                    reminder_24h_time = appointment_datetime - timedelta(hours=24)
                    reminder_1h_time = appointment_datetime - timedelta(hours=1)

                    # Текущее время с точностью до минуты (игнорируем секунды)
                    current_time = now.replace(second=0, microsecond=0)
                    reminder_24h_time = reminder_24h_time.replace(second=0, microsecond=0)
                    reminder_1h_time = reminder_1h_time.replace(second=0, microsecond=0)

                    # Напоминание за 24 часа (ровно за 24 часа)
                    if current_time == reminder_24h_time and not appointment['reminder_24h_sent']:
                        await send_reminder_24h(appointment)
                        await db.update_reminder_status(appointment['id'], '24h', True)
                        logger.info(f"Отправлено напоминание за 24 часа для записи {appointment['id']}")

                    # Напоминание за 1 час (ровно за 1 час)
                    elif current_time == reminder_1h_time and not appointment['reminder_1h_sent']:
                        await send_reminder_1h(appointment)
                        await db.update_reminder_status(appointment['id'], '1h', True)
                        logger.info(f"Отправлено напоминание за 1 час для записи {appointment['id']}")

                except Exception as e:
                    logger.error(f"Ошибка при обработке напоминания для записи {appointment['id']}: {e}")

            # Проверяем каждую минуту (60 секунд) - оптимально для слабого сервера
            await asyncio.sleep(60)

        except Exception as e:
            logger.error(f"Ошибка в сервисе напоминаний: {e}")
            # При ошибке ждем 2 минуты перед повторной попыткой
            await asyncio.sleep(120)


def parse_appointment_datetime(date_str, time_str):
    """Парсит дату и время из строк в объект datetime"""
    try:
        # Предполагаем формат DD.MM для даты и HH:MM для времени
        day, month = map(int, date_str.split('.'))
        hour, minute = map(int, time_str.split(':'))

        current_year = datetime.now().year
        # Создаем datetime объект (предполагаем, что время указано для Новосибирска UTC+7)
        appointment_datetime = datetime(current_year, month, day, hour, minute)

        # Если дата уже прошла в этом году, предполагаем следующий год
        if appointment_datetime < datetime.now():
            appointment_datetime = datetime(current_year + 1, month, day, hour, minute)

        return appointment_datetime
    except Exception as e:
        logger.error(f"Ошибка парсинга даты {date_str} {time_str}: {e}")
        return None


async def send_reminder_24h(appointment):
    """Отправляет напоминание за 24 часа"""
    try:
        message_text = (
            "👋 Привет! Напоминаем о вашей записи завтра!\n\n"
            f"📅 Дата: {appointment['date']}\n"
            f"⏰ Время: {appointment['time']}\n"
            f"👤 Имя: {appointment['client_name']}\n\n"
            "💈 Не забудьте прочитать правила посещения и прийти вовремя! 😊\n\n"
            "✨ Ждем вас с нетерпением! ✨"
        )

        await bot.send_message(
            appointment['user_id'],
            message_text
        )
    except TelegramBadRequest as e:
        if "chat not found" in str(e):
            logger.warning(f"Пользователь {appointment['user_id']} заблокировал бота, невозможно отправить напоминание")
        else:
            logger.error(f"Не удалось отправить напоминание за 24 часа: {e}")
    except Exception as e:
        logger.error(f"Не удалось отправить напоминание за 24 часа: {e}")


async def send_reminder_1h(appointment):
    """Отправляет напоминание за 1 час"""
    try:
        message_text = (
            "⏰ Скорее-скорее! Напоминаем о вашей записи через час!\n\n"
            f"📅 Дата: {appointment['date']}\n"
            f"⏰ Время: {appointment['time']}\n"
            f"👤 Имя: {appointment['client_name']}\n\n"
            "🚀 Успейте подготовиться и приходите вовремя! 💪\n\n"
            "💖 Мы уже готовимся к вашему визиту! 💖"
        )

        await bot.send_message(
            appointment['user_id'],
            message_text
        )
    except TelegramBadRequest as e:
        if "chat not found" in str(e):
            logger.warning(f"Пользователь {appointment['user_id']} заблокировал бота, невозможно отправить напоминание")
        else:
            logger.error(f"Не удалось отправить напоминание за 1 час: {e}")
    except Exception as e:
        logger.error(f"Не удалось отправить напоминание за 1 час: {e}")


# Обработчики
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user = message.from_user
    user_data = await db.get_user(user.id)

    if user_data:
        await message.answer(
            "👋 Добро пожаловать в главное меню! Выберите действие:",
            reply_markup=get_main_inline_keyboard()
        )
        await state.clear()
    else:
        await message.answer(
            "👋 Добро пожаловать! Для использования бота необходимо поделиться номером телефона.\n\n"
            "📞 Нажмите кнопку ниже, чтобы поделиться номером:",
            reply_markup=get_phone_keyboard()
        )
        await state.set_state(UserStates.waiting_for_phone)


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    await message.answer("👨‍💼 Панель администратора:", reply_markup=get_admin_keyboard())


@dp.message(F.contact, UserStates.waiting_for_phone)
async def get_phone(message: types.Message, state: FSMContext):
    contact = message.contact
    user = message.from_user

    await db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        phone=contact.phone_number
    )

    await message.answer(
        "✅ Номер успешно сохранен!",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer(
        "👋 Добро пожаловать в главное меню! Выберите действие:",
        reply_markup=get_main_inline_keyboard()
    )
    await state.clear()


# Обработчики навигации
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_message(
        callback.message,
        "👋 Добро пожаловать в главное меню! Выберите действие:",
        get_main_inline_keyboard()
    )


@dp.callback_query(F.data == "back_to_dates")
async def back_to_dates(callback: types.CallbackQuery):
    dates = await db.get_all_dates()

    if not dates:
        await safe_edit_message(
            callback.message,
            "❌ На данный момент нет доступных дат для записи.",
            get_back_to_main_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for date in dates:
        builder.button(
            text=f"📅 {date['date']} ({date['day']})",
            callback_data=f"date_{date['date']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))

    await safe_edit_message(
        callback.message,
        "📅 Выберите удобную дату для записи:",
        builder.as_markup()
    )


@dp.callback_query(F.data == "back_to_appointments")
async def back_to_appointments(callback: types.CallbackQuery):
    appointments = await db.get_user_appointments(callback.from_user.id)

    if not appointments:
        await safe_edit_message(
            callback.message,
            "📭 У вас пока нет активных записей.",
            get_back_to_main_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for app in appointments:
        builder.button(
            text=f"📅 {app['date']} ⏰ {app['time']}",
            callback_data=f"app_{app['id']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))

    await safe_edit_message(
        callback.message,
        "📋 Ваши активные записи:\n\n"
        "ℹ️ Нажмите на запись для просмотра деталей или отмены:",
        builder.as_markup()
    )


@dp.callback_query(F.data == "cancel_name_input")
async def cancel_name_input(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit_message(
        callback.message,
        "❌ Ввод имени отменен.",
        get_main_inline_keyboard()
    )


# Обработчики инлайн-кнопок главного меню
@dp.callback_query(F.data == "book_haircut")
async def show_dates(callback: types.CallbackQuery):
    dates = await db.get_all_dates()

    if not dates:
        await safe_edit_message(
            callback.message,
            "❌ На данный момент нет доступных дат для записи.\n\n"
            "⚠️ Пожалуйста, попробуйте позже или свяжитесь с администратором.",
            get_back_to_main_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for date in dates:
        builder.button(
            text=f"📅 {date['date']} ({date['day']})",
            callback_data=f"date_{date['date']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))

    await safe_edit_message(
        callback.message,
        "📅 Выберите удобную дату для записи:",
        builder.as_markup()
    )


@dp.callback_query(F.data == "my_appointments")
async def show_my_appointments(callback: types.CallbackQuery):
    appointments = await db.get_user_appointments(callback.from_user.id)

    if not appointments:
        await safe_edit_message(
            callback.message,
            "📭 У вас пока нет активных записей.\n\n"
            "💡 Вы можете записаться на стрижку, нажав соответствующую кнопку в меню.",
            get_back_to_main_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for app in appointments:
        builder.button(
            text=f"📅 {app['date']} ⏰ {app['time']}",
            callback_data=f"app_{app['id']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_main"))

    await safe_edit_message(
        callback.message,
        "📋 Ваши активные записи:\n\n"
        "ℹ️ Нажмите на запись для просмотра деталей или отмены:",
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("date_"))
async def show_times(callback: types.CallbackQuery, state: FSMContext):
    date = callback.data.split("_")[1]
    slots = await db.get_slots_by_date(date)

    builder = InlineKeyboardBuilder()
    available_slots = [slot for slot in slots if slot['available']]

    if not available_slots:
        await safe_edit_message(
            callback.message,
            f"❌ На дату {date} нет доступных времен для записи.",
            get_back_to_dates_keyboard()
        )
        return

    for slot in available_slots:
        builder.button(
            text=f"⏰ {slot['time']}",
            callback_data=f"time_{slot['id']}"
        )

    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад к датам", callback_data="back_to_dates"))

    await safe_edit_message(
        callback.message,
        f"📅 Выбрана дата: {date}\n\n"
        "⏰ Выберите удобное время:",
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("time_"))
async def get_name_for_booking(callback: types.CallbackQuery, state: FSMContext):
    slot_id = int(callback.data.split("_")[1])

    # Получаем информацию о слоте до записи
    slot = await db.get_slot(slot_id)
    if not slot:
        await safe_edit_message(
            callback.message,
            "❌ Извините, это время уже занято.\n\n"
            "⚠️ Пожалуйста, выберите другое время.",
            get_back_to_dates_keyboard()
        )
        return

    await state.update_data(selected_slot=slot_id, slot_date=slot['date'], slot_time=slot['time'])

    await safe_edit_message(
        callback.message,
        "✍️ Введите ваше имя для записи:\n\n"
        "ℹ️ Это имя будет использоваться для вашей записи.",
        get_cancel_name_keyboard()
    )
    await state.set_state(UserStates.waiting_for_name)


@dp.message(UserStates.waiting_for_name)
async def confirm_booking(message: types.Message, state: FSMContext):
    name = message.text.strip()

    if not name or len(name) < 2:
        await message.answer(
            "❌ Имя должно содержать хотя бы 2 символа.\n\n"
            "✍️ Пожалуйста, введите ваше имя еще раз:",
            reply_markup=get_cancel_name_keyboard()
        )
        return

    user_data = await state.get_data()
    slot_id = user_data['selected_slot']
    slot_date = user_data['slot_date']
    slot_time = user_data['slot_time']

    success = await db.add_appointment(message.from_user.id, slot_id, name, slot_date, slot_time)

    if not success:
        await message.answer(
            "❌ Извините, это время уже занято.\n\n"
            "⚠️ Пожалуйста, выберите другое время.",
            reply_markup=get_main_inline_keyboard()
        )
        await state.clear()
        return

    user = await db.get_user(message.from_user.id)

    # Отправляем подтверждение пользователю
    await message.answer(
        f"✅ Вы успешно записаны!\n\n"
        f"📅 Дата: {slot_date}\n"
        f"⏰ Время: {slot_time}\n"
        f"👤 Имя: {name}\n\n"
        f"💡 Вы можете просмотреть или отменить запись в разделе \"Мои записи\".",
        reply_markup=get_main_inline_keyboard()
    )

    # Уведомление админам с обработкой ошибок
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🔔 Новая запись!\n\n"
                f"📅 Дата: {slot_date}\n"
                f"⏰ Время: {slot_time}\n"
                f"👤 Клиент: {name}\n"
                f"👤 Username: @{message.from_user.username}\n"
                f"📞 Телефон: {user['phone']}"
            )
        except (TelegramNetworkError, TelegramRetryAfter) as e:
            logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    await state.clear()


@dp.callback_query(F.data.startswith("app_"))
async def show_appointment_details(callback: types.CallbackQuery):
    app_id = int(callback.data.split("_")[1])
    appointment = await db.get_appointment(app_id)

    if not appointment:
        await safe_edit_message(
            callback.message,
            "❌ Запись не найдена.",
            get_back_to_appointments_keyboard()
        )
        return

    # Проверяем, принадлежит ли запись пользователю
    if appointment['user_id'] != callback.from_user.id:
        await safe_edit_message(
            callback.message,
            "❌ У вас нет доступа к этой записи.",
            get_back_to_appointments_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить запись", callback_data=f"confirm_cancel_{app_id}")
    builder.button(text="🔙 Назад к записям", callback_data="back_to_appointments")
    builder.adjust(1)

    await safe_edit_message(
        callback.message,
        f"📋 Детали записи:\n\n"
        f"📅 Дата: {appointment['date']}\n"
        f"⏰ Время: {appointment['time']}\n"
        f"👤 Имя: {appointment['client_name']}\n"
        f"📞 Телефон: {appointment['phone']}\n\n"
        f"ℹ️ Вы можете отменить запись, нажав кнопку ниже:",
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("confirm_cancel_"))
async def show_cancel_confirmation(callback: types.CallbackQuery):
    app_id = int(callback.data.split("_")[2])
    appointment = await db.get_appointment(app_id)

    if not appointment:
        await safe_edit_message(
            callback.message,
            "❌ Запись не найдена.",
            get_back_to_appointments_keyboard()
        )
        return

    # Проверяем, принадлежит ли запись пользователю
    if appointment['user_id'] != callback.from_user.id:
        await safe_edit_message(
            callback.message,
            "❌ У вас нет доступа к этой записи.",
            get_back_to_appointments_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, отменить", callback_data=f"do_cancel_{app_id}")
    builder.button(text="❌ Нет, вернуться", callback_data=f"app_{app_id}")
    builder.adjust(2)

    await safe_edit_message(
        callback.message,
        f"⚠️ Вы уверены, что хотите отменить запись?\n\n"
        f"📅 Дата: {appointment['date']}\n"
        f"⏰ Время: {appointment['time']}\n"
        f"👤 Имя: {appointment['client_name']}\n\n"
        f"❌ Это действие нельзя отменить!",
        builder.as_markup()
    )


@dp.callback_query(F.data.startswith("do_cancel_"))
async def cancel_appointment(callback: types.CallbackQuery):
    app_id = int(callback.data.split("_")[2])
    appointment = await db.get_appointment(app_id)

    if not appointment:
        await safe_edit_message(
            callback.message,
            "❌ Запись не найдена.",
            get_back_to_appointments_keyboard()
        )
        return

    # Проверяем, принадлежит ли запись пользователю
    if appointment['user_id'] != callback.from_user.id:
        await safe_edit_message(
            callback.message,
            "❌ У вас нет доступа к этой записи.",
            get_back_to_appointments_keyboard()
        )
        return

    success = await db.delete_appointment(app_id, callback.from_user.id)

    if success:
        await safe_edit_message(
            callback.message,
            f"✅ Запись успешно отменена!\n\n"
            f"📅 Дата: {appointment['date']}\n"
            f"⏰ Время: {appointment['time']}\n\n"
            f"💡 Вы можете записаться на другое время.",
            get_main_inline_keyboard()
        )

        # Уведомление админам с обработкой ошибок
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"❌ Запись отменена!\n\n"
                    f"📅 Дата: {appointment['date']}\n"
                    f"⏰ Время: {appointment['time']}\n"
                    f"👤 Пользователь: @{callback.from_user.username}"
                )
            except (TelegramNetworkError, TelegramRetryAfter) as e:
                logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")
    else:
        await safe_edit_message(
            callback.message,
            "❌ Произошла ошибка при отмене записи.\n\n"
            "⚠️ Пожалуйста, попробуйте позже.",
            get_back_to_appointments_keyboard()
        )


async def main():
    await db.init_db()

    # Запускаем сервис напоминаний в фоне
    asyncio.create_task(check_reminders())

    # Настраиваем обработку ошибок при запуске
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        # Перезапуск через 30 секунд
        await asyncio.sleep(30)
        await main()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
