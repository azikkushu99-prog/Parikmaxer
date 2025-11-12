import logging
from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
import db
from datetime import datetime, timedelta
import asyncio
import aiosqlite

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_IDS = [785219206, 5176507854]

admin_router = Router()


# Состояния FSM для админа
class AdminStates(StatesGroup):
    waiting_for_date = State()
    waiting_for_day = State()
    waiting_for_time = State()
    waiting_for_del_date = State()
    waiting_for_del_time = State()
    waiting_for_notification = State()


# Клавиатура админ панели
def get_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить слот", callback_data="add_slot")
    builder.button(text="❌ Удалить слот", callback_data="del_slot")
    builder.button(text="📋 Просмотр записей", callback_data="view_appointments")
    builder.button(text="🔧 Исправить время", callback_data="fix_time_format")
    builder.adjust(1)
    return builder.as_markup()


# Клавиатура с кнопкой Назад в админ-меню
def get_back_to_admin_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад в админ-панель", callback_data="back_to_admin")
    return builder.as_markup()


# Клавиатура для отмены действий
def get_cancel_action_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data="back_to_admin")
    return builder.as_markup()


# Навигация в админ-панели
@admin_router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👨‍💼 Панель администратора:\n\n"
        "ℹ️ Выберите действие:",
        reply_markup=get_admin_keyboard()
    )


# Добавление слота
@admin_router.callback_query(F.data == "add_slot")
async def add_slot_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "➕ Добавление нового слота:\n\n"
        "📅 Введите дату в формате ДД.ММ (например, 25.12):",
        reply_markup=get_cancel_action_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_date)


@admin_router.message(AdminStates.waiting_for_date)
async def get_date(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.update_data(new_date=message.text)
    await message.answer(
        "📅 Введите день недели (пн, вт, ср, чт, пт, сб, вс):",
        reply_markup=get_cancel_action_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_day)


@admin_router.message(AdminStates.waiting_for_day)
async def get_day(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    await state.update_data(new_day=message.text)
    await message.answer(
        "⏰ Введите время в формате ЧЧ:ММ (например, 14:30):",
        reply_markup=get_cancel_action_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_time)


@admin_router.message(AdminStates.waiting_for_time)
async def get_time(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    # Нормализуем формат времени: заменяем точки на двоеточия
    time_input = message.text.strip()
    normalized_time = time_input.replace('.', ':')
    
    # Проверяем формат времени
    try:
        hours, minutes = normalized_time.split(':')
        if len(hours) != 2 or len(minutes) != 2:
            raise ValueError
        int(hours), int(minutes)
    except ValueError:
        await message.answer(
            "❌ Неверный формат времени!\n\n"
            "⏰ Введите время в формате ЧЧ:ММ (например, 14:30):",
            reply_markup=get_cancel_action_keyboard()
        )
        return

    data = await state.get_data()
    success = await db.add_slot(data['new_date'], data['new_day'], normalized_time)

    if success:
        await message.answer(
            f"✅ Слот успешно добавлен!\n\n"
            f"📅 Дата: {data['new_date']}\n"
            f"📆 День: {data['new_day']}\n"
            f"⏰ Время: {normalized_time}",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            "❌ Ошибка: слот с такой датой и временем уже существует.\n\n"
            "⚠️ Пожалуйста, введите другие данные.",
            reply_markup=get_admin_keyboard()
        )

    await state.clear()


# Удаление слота
@admin_router.callback_query(F.data == "del_slot")
async def del_slot_start(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    # Получаем все даты со слотами
    dates = await db.get_all_dates_with_slots()

    if not dates:
        await callback.message.edit_text(
            "❌ Нет доступных слотов для удаления.",
            reply_markup=get_back_to_admin_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for date in dates:
        builder.button(
            text=f"📅 {date['date']} ({date['day']})",
            callback_data=f"deldate_{date['date']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="back_to_admin"))

    await callback.message.edit_text(
        "🗑️ Удаление слота:\n\n"
        "📅 Выберите дату:",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_del_date)


@admin_router.callback_query(AdminStates.waiting_for_del_date, F.data.startswith("deldate_"))
async def del_date(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    date = callback.data.split("_")[1]
    await state.update_data(del_date=date)

    # Получаем все слоты на эту дату (и занятые и свободные)
    slots = await db.get_all_slots_by_date(date)

    if not slots:
        await callback.message.edit_text(
            f"❌ На дату {date} нет слотов.",
            reply_markup=get_back_to_admin_keyboard()
        )
        await state.clear()
        return

    builder = InlineKeyboardBuilder()
    for slot in slots:
        # Проверяем, есть ли запись на этот слот
        appointment = await db.get_appointment_by_slot_id(slot['id'])
        status = "🔴 Занят" if appointment else "🟢 Свободен"
        builder.button(
            text=f"⏰ {slot['time']} ({status})",
            callback_data=f"deltime_{slot['id']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад к датам", callback_data="del_slot"))

    await callback.message.edit_text(
        f"🗑️ Удаление слота:\n\n"
        f"📅 Выбрана дата: {date}\n\n"
        f"⏰ Выберите время для удаления:\n"
        f"🟢 Свободен - можно удалить без оповещения\n"
        f"🔴 Занят - будет запрошено сообщение для пользователя",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.waiting_for_del_time)


@admin_router.callback_query(AdminStates.waiting_for_del_time, F.data.startswith("deltime_"))
async def del_time(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return

    slot_id = int(callback.data.split("_")[1])
    slot = await db.get_slot(slot_id)

    if not slot:
        await callback.message.edit_text(
            "❌ Слот не найден.",
            reply_markup=get_back_to_admin_keyboard()
        )
        await state.clear()
        return

    # Проверяем, есть ли запись на этот слот
    appointment = await db.get_appointment_by_slot_id(slot_id)

    if appointment:
        # Если есть запись, просим админа написать сообщение для пользователя
        await state.update_data(
            del_slot_id=slot_id,
            appointment_id=appointment['id'],
            appointment_user_id=appointment['user_id'],
            appointment_date=appointment['date'],
            appointment_time=appointment['time'],
            client_name=appointment['client_name']
        )

        await callback.message.edit_text(
            f"⚠️ На этот слот есть активная запись!\n\n"
            f"👤 Клиент: {appointment['client_name']}\n"
            f"📅 Дата: {appointment['date']}\n"
            f"⏰ Время: {appointment['time']}\n\n"
            f"💬 Пожалуйста, напишите сообщение для пользователя, которое будет отправлено при отмене записи:",
            reply_markup=get_cancel_action_keyboard()
        )
        await state.set_state(AdminStates.waiting_for_notification)
    else:
        # Если записи нет, просто удаляем слот
        await db.delete_slot(slot_id)
        await callback.message.edit_text(
            "✅ Слот удален (без активных записей).",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()


@admin_router.message(AdminStates.waiting_for_notification)
async def send_notification_and_delete(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return

    data = await state.get_data()
    slot_id = data['del_slot_id']
    appointment_id = data['appointment_id']
    user_id = data['appointment_user_id']
    notification_text = message.text

    try:
        # Отправляем сообщение пользователю
        await message.bot.send_message(
            user_id,
            f"❌ Ваша запись отменена администратором.\n\n"
            f"📅 Дата: {data['appointment_date']}\n"
            f"⏰ Время: {data['appointment_time']}\n"
            f"👤 Имя: {data['client_name']}\n\n"
            f"💬 Сообщение от администратора: {notification_text}\n\n"
            f"⚠️ Пожалуйста, запишитесь на другое время."
        )

        # Удаляем запись и слот
        await db.delete_appointment(appointment_id)
        await db.delete_slot(slot_id)

        await message.answer(
            "✅ Слот удален с оповещением пользователя.",
            reply_markup=get_admin_keyboard()
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления: {e}")
        # Если не удалось отправить сообщение, все равно удаляем
        await db.delete_appointment(appointment_id)
        await db.delete_slot(slot_id)
        await message.answer(
            f"✅ Слот удален, но не удалось отправить уведомление пользователю: {e}",
            reply_markup=get_admin_keyboard()
        )

    await state.clear()


# Просмотр записей
@admin_router.callback_query(F.data == "view_appointments")
async def view_appointments_start(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    dates = await db.get_dates_with_appointments()

    if not dates:
        await callback.message.edit_text(
            "📭 Нет активных записей.",
            reply_markup=get_back_to_admin_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for date in dates:
        builder.button(
            text=f"📅 {date['date']}",
            callback_data=f"viewdate_{date['date']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад в админ-панель", callback_data="back_to_admin"))

    await callback.message.edit_text(
        "📋 Просмотр записей:\n\n"
        "📅 Выберите дату:",
        reply_markup=builder.as_markup()
    )


@admin_router.callback_query(F.data.startswith("viewdate_"))
async def view_appointments_date(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    date = callback.data.split("_")[1]
    appointments = await db.get_appointments_by_date(date)

    if not appointments:
        await callback.message.edit_text(
            f"📭 На дату {date} нет записей.",
            reply_markup=get_back_to_admin_keyboard()
        )
        return

    builder = InlineKeyboardBuilder()
    for app in appointments:
        builder.button(
            text=f"⏰ {app['time']} - {app['client_name']}",
            callback_data=f"viewapp_{app['id']}"
        )
    builder.adjust(1)
    builder.row(types.InlineKeyboardButton(text="🔙 Назад к датам", callback_data="view_appointments"))

    await callback.message.edit_text(
        f"📋 Записи на {date}:\n\n"
        "ℹ️ Выберите запись для просмотра деталей:",
        reply_markup=builder.as_markup()
    )


@admin_router.callback_query(F.data.startswith("viewapp_"))
async def view_appointments_time(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        return

    app_id = int(callback.data.split("_")[1])
    appointment = await db.get_appointment(app_id)

    if appointment:
        text = (
            f"📋 Детали записи:\n\n"
            f"📅 Дата: {appointment['date']}\n"
            f"⏰ Время: {appointment['time']}\n"
            f"👤 Username: @{appointment['username']}\n"
            f"👨‍💼 Имя: {appointment['first_name']}\n"
            f"📞 Телефон: {appointment['phone']}\n"
            f"✂️ Имя для записи: {appointment['client_name']}"
        )
    else:
        text = "❌ Запись не найдена."

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к записям", callback_data=f"viewdate_{appointment['date']}")
    builder.button(text="🏠 В админ-панель", callback_data="back_to_admin")

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup()
    )


# Исправление формата времени
@admin_router.callback_query(F.data == "fix_time_format")
async def fix_time_format(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text(
        "🔧 Исправление формата времени в слотах...\n\n"
        "⏳ Пожалуйста, подождите...",
        reply_markup=get_back_to_admin_keyboard()
    )

    try:
        # Получаем все слоты
        slots = await db.get_available_slots()
        fixed_count = 0
        
        for slot in slots:
            old_time = slot['time']
            # Заменяем точки на двоеточия
            if '.' in old_time:
                new_time = old_time.replace('.', ':')
                # Обновляем слот в базе данных
                async with aiosqlite.connect('bot.db') as db_conn:
                    await db_conn.execute(
                        "UPDATE slots SET time = ? WHERE id = ?",
                        (new_time, slot['id'])
                    )
                    await db_conn.commit()
                fixed_count += 1
        
        if fixed_count > 0:
            await callback.message.edit_text(
                f"✅ Формат времени исправлен!\n\n"
                f"🔧 Обновлено слотов: {fixed_count}\n\n"
                f"💡 Теперь время отображается в правильном формате ЧЧ:ММ",
                reply_markup=get_admin_keyboard()
            )
        else:
            await callback.message.edit_text(
                "ℹ️ Все слоты уже имеют правильный формат времени.",
                reply_markup=get_admin_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Ошибка при исправлении формата времени: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка при исправлении формата времени: {e}",
            reply_markup=get_admin_keyboard()
        )


# Команда для исправления времени через сообщение
@admin_router.message(Command("fix_time"))
async def cmd_fix_time(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    await message.answer(
        "🔧 Исправление формата времени в слотах...\n\n"
        "⏳ Пожалуйста, подождите...",
        reply_markup=get_back_to_admin_keyboard()
    )

    try:
        # Получаем все слоты
        slots = await db.get_available_slots()
        fixed_count = 0
        
        for slot in slots:
            old_time = slot['time']
            # Заменяем точки на двоеточия
            if '.' in old_time:
                new_time = old_time.replace('.', ':')
                # Обновляем слот в базе данных
                async with aiosqlite.connect('bot.db') as db_conn:
                    await db_conn.execute(
                        "UPDATE slots SET time = ? WHERE id = ?",
                        (new_time, slot['id'])
                    )
                    await db_conn.commit()
                fixed_count += 1
        
        if fixed_count > 0:
            await message.answer(
                f"✅ Формат времени исправлен!\n\n"
                f"🔧 Обновлено слотов: {fixed_count}\n\n"
                f"💡 Теперь время отображается в правильном формате ЧЧ:ММ",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer(
                "ℹ️ Все слоты уже имеют правильный формат времени.",
                reply_markup=get_admin_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Ошибка при исправлении формата времени: {e}")
        await message.answer(
            f"❌ Ошибка при исправлении формата времени: {e}",
            reply_markup=get_admin_keyboard()
        )
