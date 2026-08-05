"""
AmneziaVPN Telegram Bot
Main bot file - handles user commands and key distribution
"""
import asyncio
import logging
import qrcode
import io
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, ADMIN_ID, SERVERS, AWG_PARAMS
from whitelist import (
    init_db, add_to_whitelist, remove_from_whitelist,
    is_in_whitelist, get_whitelist, count_user_keys,
    add_key, remove_key, get_user_keys, update_key_limit
)
from awg_manager import (
    create_peer, remove_peer, get_server_info,
    get_least_loaded_server, get_server_for_user,
    generate_wireguard_config, generate_vpn_uri
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- States ---
class KeyCreation(StatesGroup):
    waiting_for_name = State()


class AdminAction(StatesGroup):
    waiting_add_user = State()
    waiting_keys_user = State()
    waiting_revoke_user = State()
    waiting_limit_user = State()


# --- Helper functions ---

def make_qr_png(text: str) -> bytes:
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID


# --- Keyboards ---

def get_user_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔑 Ключ"), KeyboardButton(text="📋 Мои ключи")],
            [KeyboardButton(text="❌ Отозвать ключ")]
        ],
        resize_keyboard=True
    )


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить юзера", callback_data="admin_add")],
        [InlineKeyboardButton(text="👥 Список всех", callback_data="admin_list")],
        [InlineKeyboardButton(text="🔑 Ключи юзера", callback_data="admin_user_keys")],
        [InlineKeyboardButton(text="❌ Отозвать ключ", callback_data="admin_revoke")],
        [InlineKeyboardButton(text="🔢 Изменить лимит", callback_data="admin_limit")],
        [InlineKeyboardButton(text="📊 Серверы", callback_data="admin_servers")],
        [InlineKeyboardButton(text="↩️ Закрыть", callback_data="admin_close")],
    ])


# --- User commands ---

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    wl = is_in_whitelist(user.username or "")
    if not wl:
        await message.answer(
            f"Привет! У тебя нет доступа к этому боту.\n"
            f"Твой ник: @{user.username}\n"
            f"Обратись к администратору для получения доступа."
        )
        return

    await message.answer(
        f"Привет, @{user.username}!\n"
        f"Твой лимит ключей: {wl['key_limit']}\n"
        f"Использовано: {count_user_keys(user.username)}\n\n"
        f"Используй кнопки внизу:",
        reply_markup=get_user_keyboard()
    )


# --- Text button handlers (user keyboard) ---

@dp.message(F.text == "🔑 Ключ")
async def btn_key(message: Message, state: FSMContext):
    user = message.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await message.answer("У тебя нет доступа к этому боту.")
        return
    current = count_user_keys(username)
    if current >= wl["key_limit"]:
        await message.answer(
            f"Ты использовал все ключи ({current}/{wl['key_limit']}).\n"
            f"Обратись к администратору для увеличения лимита."
        )
        return
    await message.answer("Введи название для ключа (например: iPhone, MacBook, VPN-comp 1):")
    await state.set_state(KeyCreation.waiting_for_name)


@dp.message(F.text == "📋 Мои ключи")
async def btn_mykeys(message: Message):
    user = message.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await message.answer("У тебя нет доступа.")
        return
    keys = get_user_keys(username)
    if not keys:
        await message.answer("У тебя пока нет ключей. Нажми «🔑 Ключ» для получения.")
        return
    text = f"Твои ключи ({len(keys)}/{wl['key_limit']}):\n\n"
    for k in keys:
        text += f"• {k['key_name']} ({k['server_name']})\n"
    await message.answer(text)


@dp.message(F.text == "❌ Отозвать ключ")
async def btn_revoke(message: Message):
    user = message.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await message.answer("У тебя нет доступа.")
        return
    keys = get_user_keys(username)
    if not keys:
        await message.answer("У тебя пока нет ключей. Нажми «🔑 Ключ» для получения.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {k['key_name']}", callback_data=f"revoke:{k['id']}:{k['key_name']}")]
        for k in keys
    ])
    await message.answer("Выбери ключ для отзыва:", reply_markup=kb)


# --- Command handlers (same logic, for those who type commands) ---

@dp.message(Command("key"))
async def cmd_key(message: Message, state: FSMContext):
    user = message.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await message.answer("У тебя нет доступа к этому боту.")
        return
    current = count_user_keys(username)
    if current >= wl["key_limit"]:
        await message.answer(
            f"Ты использовал все ключи ({current}/{wl['key_limit']}).\n"
            f"Обратись к администратору для увеличения лимита."
        )
        return
    await message.answer("Введи название для ключа (например: iPhone, MacBook, VPN-comp 1):")
    await state.set_state(KeyCreation.waiting_for_name)


@dp.message(KeyCreation.waiting_for_name)
async def process_key_name(message: Message, state: FSMContext):
    user = message.from_user
    username = user.username or ""
    key_name = message.text.strip()

    if not key_name or len(key_name) > 50:
        await message.answer("Название слишком длинное или пустое. Попробуй ещё раз /key")
        await state.clear()
        return

    await state.clear()

    # Check limit again (in case user created keys in parallel)
    wl = is_in_whitelist(username)
    current = count_user_keys(username)
    if current >= wl["key_limit"]:
        await message.answer("Лимит ключей исчерпан.")
        return

    await message.answer("Генерирую ключ, подожди...")

    try:
        server = get_server_for_user(username)
        if not server:
            await message.answer("Все серверы недоступны. Попробуй позже.")
            return

        peer = create_peer(server)
        add_key(username, key_name, peer["server_name"], peer["client_ip"],
                peer["private_key"], peer["public_key"])

        vpn_link = generate_vpn_uri(peer, description=key_name)
        conf = generate_wireguard_config(peer)

        # 1. Send header
        await message.answer(
            f"Ключ \"{key_name}\" готов!\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Дальше код пришлётся отдельным сообщением — просто скопируй его."
        )

        # 2. Send vpn:// link as plain text (separate message = tap to copy)
        await message.answer(vpn_link)

        # 3. Send QR code
        qr_png = make_qr_png(vpn_link)
        await message.answer_photo(
            BufferedInputFile(qr_png, filename=f"{key_name}.png"),
            caption="QR-код — открой камеру телефона и наведи на код"
        )

        # 4. Send .conf file
        conf_bytes = conf.encode("utf-8")
        safe_name = key_name.replace(" ", "_").replace("/", "_")
        await message.answer_document(
            BufferedInputFile(conf_bytes, filename=f"{safe_name}.conf"),
            caption="Файл конфига — можно импортировать в AmneziaVPN как файл"
        )

    except Exception as e:
        logging.error(f"Error creating peer: {e}")
        await message.answer(f"Ошибка при создании ключа: {e}")


@dp.message(Command("mykeys"))
async def cmd_mykeys(message: Message):
    user = message.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await message.answer("У тебя нет доступа.")
        return
    keys = get_user_keys(username)
    if not keys:
        await message.answer("У тебя пока нет ключей. Используй /key для получения.")
        return
    text = f"Твои ключи ({len(keys)}/{wl['key_limit']}):\n\n"
    for k in keys:
        text += f"• {k['key_name']} ({k['server_name']})\n"
    await message.answer(text)


@dp.message(Command("revoke"))
async def cmd_revoke(message: Message, command: CommandObject):
    user = message.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await message.answer("У тебя нет доступа.")
        return
    if not command.args:
        await message.answer("Использование: /revoke название_ключа\nНапример: /revoke iPhone")
        return
    key_name = command.args.strip()
    removed = remove_key(username, key_name=key_name)
    if not removed:
        await message.answer(f"Ключ \"{key_name}\" не найден.")
        return
    server = next((s for s in SERVERS if s["name"] == removed["server_name"]), None)
    if server:
        try:
            remove_peer(server, removed["public_key"])
        except Exception as e:
            logging.error(f"Error removing peer: {e}")
    await message.answer(
        f"Ключ \"{key_name}\" отозван и удалён с сервера.\n"
        f"Теперь ты можешь создать новый ключ — нажми «🔑 Ключ»"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    user = message.from_user
    wl = is_in_whitelist(user.username or "")
    if not wl:
        await message.answer("У тебя нет доступа к этому боту.")
        return
    await message.answer(
        "Используй кнопки внизу:\n\n"
        "🔑 Ключ — получить новый VPN-ключ\n"
        "📋 Мои ключи — список твоих ключей\n"
        "❌ Отозвать ключ — выбрать ключ для отзыва"
    )


# --- Callback: revoke key by inline button ---

@dp.callback_query(F.data.startswith("revoke:"))
async def cb_revoke_key(callback: CallbackQuery):
    user = callback.from_user
    username = user.username or ""
    wl = is_in_whitelist(username)
    if not wl:
        await callback.answer("Нет доступа")
        return
    parts = callback.data.split(":", 2)
    key_id = int(parts[1])
    key_name = parts[2] if len(parts) > 2 else ""
    removed = remove_key(username, key_id=key_id)
    if not removed:
        await callback.answer("Ключ не найден")
        return
    server = next((s for s in SERVERS if s["name"] == removed["server_name"]), None)
    if server:
        try:
            remove_peer(server, removed["public_key"])
        except Exception as e:
            logging.error(f"Error removing peer: {e}")
    await callback.message.edit_text(
        f"Ключ \"{key_name}\" отозван и удалён с сервера."
    )
    await callback.answer("Отозвано")


# --- Admin menu ---

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message):
        return
    await message.answer("🔧 Админ-меню:", reply_markup=get_admin_keyboard())


@dp.callback_query(F.data == "admin_close")
async def cb_admin_close(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Меню закрыто.")
    await callback.answer()


@dp.callback_query(F.data == "admin_add")
async def cb_admin_add(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text(
        "Введи @username и лимит ключей.\n"
        "Пример: @vasya 5\n"
        "Или просто @vasya (лимит по умолчанию — 3)"
    )
    await state.set_state(AdminAction.waiting_add_user)
    await callback.answer()


@dp.message(AdminAction.waiting_add_user)
async def process_add_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if not parts:
        await message.answer("Нужен @username. Попробуй ещё раз: /admin")
        await state.clear()
        return
    username = parts[0].replace("@", "").lower()
    limit = int(parts[1]) if len(parts) > 1 else None
    if add_to_whitelist(username, limit):
        await message.answer(
            f"✅ Добавлен @{username} с лимитом {limit or 'по умолчанию (3)'}",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer("Ошибка при добавлении.")
    await state.clear()


@dp.callback_query(F.data == "admin_list")
async def cb_admin_list(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    wl = get_whitelist()
    if not wl:
        await callback.message.edit_text("Вайтлист пуст.")
        await callback.answer()
        return
    text = f"Вайтлист ({len(wl)}):\n\n"
    for u in wl:
        count = count_user_keys(u["username"])
        srv = u.get("assigned_server") or "—"
        text += f"@{u['username']} | лимит: {u['key_limit']} | ключей: {count} | сервер: {srv}\n"
    text += "\n🔒 Меню:"
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin_user_keys")
async def cb_admin_user_keys(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Введи @username для просмотра ключей:")
    await state.set_state(AdminAction.waiting_keys_user)
    await callback.answer()


@dp.message(AdminAction.waiting_keys_user)
async def process_keys_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    username = message.text.strip().replace("@", "").lower()
    keys = get_user_keys(username)
    if not keys:
        await message.answer(
            f"У @{username} нет ключей.",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()
        return
    text = f"Ключи @{username} ({len(keys)}):\n\n"
    for k in keys:
        text += f"• {k['key_name']} ({k['server_name']})\n"
    await message.answer(text, reply_markup=get_admin_keyboard())
    await state.clear()


@dp.callback_query(F.data == "admin_revoke")
async def cb_admin_revoke(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Введи @username для отзыва ключей:")
    await state.set_state(AdminAction.waiting_revoke_user)
    await callback.answer()


@dp.message(AdminAction.waiting_revoke_user)
async def process_revoke_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    username = message.text.strip().replace("@", "").lower()
    keys = get_user_keys(username)
    if not keys:
        await message.answer(
            f"У @{username} нет ключей.",
            reply_markup=get_admin_keyboard()
        )
        await state.clear()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"❌ {k['key_name']} ({k['server_name']})",
                              callback_data=f"arevoke:{username}:{k['id']}:{k['key_name']}")]
        for k in keys
    ] + [[InlineKeyboardButton(text="❌❌ Отозвать ВСЕ", callback_data=f"arevoke_all:{username}")]])
    await message.answer(f"Ключи @{username}. Выбери для отзыва:", reply_markup=kb)
    await state.clear()


@dp.callback_query(F.data.startswith("arevoke:"))
async def cb_admin_revoke_key(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    parts = callback.data.split(":", 3)
    username = parts[1]
    key_id = int(parts[2])
    key_name = parts[3] if len(parts) > 3 else ""
    removed = remove_key(username, key_id=key_id)
    if not removed:
        await callback.answer("Ключ не найден")
        return
    server = next((s for s in SERVERS if s["name"] == removed["server_name"]), None)
    if server:
        try:
            remove_peer(server, removed["public_key"])
        except Exception as e:
            logging.error(f"Error removing peer: {e}")
    await callback.message.edit_text(f"Ключ \"{key_name}\" отозван у @{username}.")
    await callback.answer("Отозвано")


@dp.callback_query(F.data.startswith("arevoke_all:"))
async def cb_admin_revoke_all(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    username = callback.data.split(":", 1)[1]
    keys = get_user_keys(username)
    removed = 0
    for k in keys:
        server = next((s for s in SERVERS if s["name"] == k["server_name"]), None)
        if server:
            try:
                remove_peer(server, k["public_key"])
                remove_key(username, key_id=k["id"])
                removed += 1
            except Exception as e:
                logging.error(f"Error: {e}")
    await callback.message.edit_text(f"Отозвано {removed} ключей у @{username}.")
    await callback.answer(f"Отозвано {removed}")


@dp.callback_query(F.data == "admin_limit")
async def cb_admin_limit(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await callback.message.edit_text("Введи @username и новый лимит.\nПример: @vasya 10")
    await state.set_state(AdminAction.waiting_limit_user)
    await callback.answer()


@dp.message(AdminAction.waiting_limit_user)
async def process_limit_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Нужны @username и лимит. Пример: @vasya 10")
        await state.clear()
        return
    username = parts[0].replace("@", "").lower()
    try:
        new_limit = int(parts[1])
    except ValueError:
        await message.answer("Лимит должен быть числом. Попробуй ещё раз: /admin")
        await state.clear()
        return
    if update_key_limit(username, new_limit):
        await message.answer(
            f"✅ Лимит для @{username} изменён на {new_limit}",
            reply_markup=get_admin_keyboard()
        )
    else:
        await message.answer(
            f"@{username} не найден в вайтлисте.",
            reply_markup=get_admin_keyboard()
        )
    await state.clear()


@dp.callback_query(F.data == "admin_servers")
async def cb_admin_servers(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    text = "Серверы:\n\n"
    for server in SERVERS:
        info = get_server_info(server)
        status = "OK" if info["peer_count"] >= 0 else "ERROR"
        # Count users assigned to this server
        wl = get_whitelist()
        users_on_server = sum(1 for u in wl if u.get("assigned_server") == server["name"])
        text += (
            f"📍 {info['name']} | {info['host']}\n"
            f"   Статус: {status} | peers: {info['peer_count']}/{info['max_users']}\n"
            f"   Юзеров закреплено: {users_on_server}\n\n"
        )
    text += "🔒 Меню:"
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
    await callback.answer()


# --- Legacy admin commands (keep for typing) ---

@dp.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject):
    if not is_admin(message):
        return
    parts = command.args.split() if command.args else []
    if not parts:
        await message.answer("Использование: /add @username [лимит]\nПример: /add @vasya 3")
        return
    username = parts[0].replace("@", "").lower()
    limit = int(parts[1]) if len(parts) > 1 else None
    if add_to_whitelist(username, limit):
        await message.answer(f"Добавлен @{username} с лимитом {limit or 'по умолчанию'}")
    else:
        await message.answer("Ошибка при добавлении.")


@dp.message(Command("remove"))
async def cmd_remove(message: Message, command: CommandObject):
    if not is_admin(message):
        return
    if not command.args:
        await message.answer("Использование: /remove @username")
        return
    username = command.args.replace("@", "").lower()
    if remove_from_whitelist(username):
        await message.answer(f"Удалён @{username} из вайтлиста")
    else:
        await message.answer(f"@{username} не найден в вайтлисте")


@dp.message(Command("list"))
async def cmd_list(message: Message):
    if not is_admin(message):
        return
    wl = get_whitelist()
    if not wl:
        await message.answer("Вайтлист пуст.")
        return
    text = f"Вайтлист ({len(wl)}):\n\n"
    for u in wl:
        count = count_user_keys(u["username"])
        srv = u.get("assigned_server") or "—"
        text += f"@{u['username']} | лимит: {u['key_limit']} | ключей: {count} | сервер: {srv}\n"
    await message.answer(text)


@dp.message(Command("servers"))
async def cmd_servers(message: Message):
    if not is_admin(message):
        return
    text = "Серверы:\n\n"
    for server in SERVERS:
        info = get_server_info(server)
        status = "OK" if info["peer_count"] >= 0 else "ERROR"
        text += f"{info['name']} | {info['host']} | {status} | peers: {info['peer_count']}/{info['max_users']}\n"
    await message.answer(text)


@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject):
    if not is_admin(message):
        return
    if not command.args:
        await message.answer("Использование: /broadcast текст сообщения")
        return
    wl = get_whitelist()
    sent = 0
    failed = 0
    for u in wl:
        try:
            await bot.send_message(u["username"], f"Сообщение от администратора:\n\n{command.args}")
            sent += 1
        except:
            failed += 1
    await message.answer(f"Отправлено: {sent}, не доставлено: {failed}")


# --- Start ---

async def main():
    init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())