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
from aiogram.types import Message, BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters.command import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import BOT_TOKEN, ADMIN_ID, SERVERS, AWG_PARAMS
from whitelist import (
    init_db, add_to_whitelist, remove_from_whitelist,
    is_in_whitelist, get_whitelist, count_user_keys,
    add_key, remove_key, get_user_keys
)
from awg_manager import (
    create_peer, remove_peer, get_server_info,
    get_least_loaded_server, generate_wireguard_config, generate_vpn_uri
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# --- States for key creation flow ---
class KeyCreation(StatesGroup):
    waiting_for_name = State()


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
        f"Команды:\n"
        f"/key — получить новый ключ\n"
        f"/mykeys — мои ключы\n"
        f"/help — помощь"
    )


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
        server = get_least_loaded_server()
        if not server:
            await message.answer("Все серверы недоступны. Попробуй позже.")
            return

        peer = create_peer(server)
        add_key(username, key_name, peer["server_name"], peer["client_ip"],
                peer["private_key"], peer["public_key"])

        vpn_link = generate_vpn_uri(peer, description=key_name)
        conf = generate_wireguard_config(peer)

        # 1. Send vpn:// link in code block (tap to copy in Telegram)
        await message.answer(
            f"Ключ \"{key_name}\" готов!\n\n"
            f"Ссылка для импорта в AmneziaVPN:\n"
            f"```\n{vpn_link}\n```"
        )

        # 2. Send QR code
        qr_png = make_qr_png(vpn_link)
        await message.answer_photo(
            BufferedInputFile(qr_png, filename=f"{key_name}.png"),
            caption="QR-код — открой камеру телефона и наведи на код"
        )

        # 3. Send .conf file
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
        text += f"#{k['id']} | {k['key_name']} | {k['server_name']}\n"
    text += "\nЧтобы отозвать ключ, введи: /revoke название_ключа"
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

    # Remove peer from server
    server = next((s for s in SERVERS if s["name"] == removed["server_name"]), None)
    if server:
        try:
            remove_peer(server, removed["public_key"])
        except Exception as e:
            logging.error(f"Error removing peer: {e}")

    await message.answer(
        f"Ключ \"{key_name}\" отозван и удалён с сервера.\n"
        f"Теперь ты можешь создать новый ключ командой /key"
    )


@dp.message(Command("help"))
async def cmd_help(message: Message):
    user = message.from_user
    wl = is_in_whitelist(user.username or "")
    if not wl:
        await message.answer("У тебя нет доступа к этому боту.")
        return

    await message.answer(
        "Команды:\n"
        "/key — получить новый VPN-ключ (бот спросит название)\n"
        "/mykeys — список твоих ключей\n"
        "/revoke название — отозвать ключ по названию\n"
        "/help — эта справка"
    )


# --- Admin commands ---

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
        text += f"@{u['username']} | лимит: {u['key_limit']} | ключей: {count}\n"
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


@dp.message(Command("admin_revoke"))
async def cmd_admin_revoke(message: Message, command: CommandObject):
    if not is_admin(message):
        return

    if not command.args:
        await message.answer("Использование: /admin_revoke @username [key_name]\nЕсли key_name не указан — отзывает все ключи пользователя")
        return

    parts = command.args.split()
    username = parts[0].replace("@", "").lower()
    key_name = parts[1] if len(parts) > 1 else None

    keys = get_user_keys(username)
    if not keys:
        await message.answer(f"У @{username} нет ключей.")
        return

    if key_name:
        keys_to_remove = [k for k in keys if k["key_name"] == key_name]
        if not keys_to_remove:
            await message.answer(f"Ключ \"{key_name}\" не найден у @{username}")
            return
    else:
        keys_to_remove = keys

    removed = 0
    for k in keys_to_remove:
        server = next((s for s in SERVERS if s["name"] == k["server_name"]), None)
        if server:
            if remove_peer(server, k["public_key"]):
                remove_key(username, key_id=k["id"])
                removed += 1

    await message.answer(f"Отозвано ключей: {removed} у @{username}")


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