import asyncio
import json
import os
import random
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import aiosqlite
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in env")

DB_PATH = os.getenv("DATABASE_PATH", "darikum.db")
CATALOG_FILE = os.getenv("CATALOG_FILE", "catalog.json")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# --- Database helpers ---
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                stars INTEGER DEFAULT 0
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS collection (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id TEXT,
                item_title TEXT,
                rarity TEXT,
                UNIQUE(user_id, item_id)
            );
        """)
        await db.commit()

async def get_user(user_id: int, username: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, username, stars FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row:
            return {"user_id": row[0], "username": row[1], "stars": row[2]}
        # create with starter balance
        starter = int(os.getenv("STARTER_STARS", "500"))
        await db.execute("INSERT INTO users (user_id, username, stars) VALUES (?, ?, ?)", (user_id, username or "", starter))
        await db.commit()
        return {"user_id": user_id, "username": username or "", "stars": starter}

async def change_stars(user_id: int, delta: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET stars = stars + ? WHERE user_id = ?", (delta, user_id))
        await db.commit()
        cur = await db.execute("SELECT stars FROM users WHERE user_id = ?", (user_id,))
        r = await cur.fetchone()
        return r[0] if r else None

async def add_to_collection(user_id: int, item: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO collection (user_id, item_id, item_title, rarity) VALUES (?, ?, ?, ?)",
                (user_id, item["id"], item["title"], item.get("rarity", "common"))
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

async def get_collection(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT item_id, item_title, rarity FROM collection WHERE user_id = ?", (user_id,))
        rows = await cur.fetchall()
        return [{"id": r[0], "title": r[1], "rarity": r[2]} for r in rows]

# --- Catalog helpers ---
if not os.path.exists(CATALOG_FILE):
    # default small catalog if файл не задан
    CATALOG = {
        "cases": [
            {
                "id": "case_basic",
                "title": "Basic Case",
                "price": 100,
                "items": [
                    {"id": "pudgy_dog", "title": "Pudgy Dog", "rarity": "legendary", "weight": 1},
                    {"id": "heart_locket", "title": "Heart Locket", "rarity": "rare", "weight": 5},
                    {"id": "rose", "title": "Rose", "rarity": "common", "weight": 20}
                ]
            }
        ]
    }
else:
    with open(CATALOG_FILE, "r", encoding="utf-8") as f:
        CATALOG = json.load(f)

def list_cases_kb():
    kb = InlineKeyboardMarkup()
    for case in CATALOG["cases"]:
        kb.add(InlineKeyboardButton(f"{case['title']} — {case['price']} ⭐", callback_data=f"open_case:{case['id']}"))
    return kb

def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Открыть кейс"))
    kb.add(KeyboardButton("Каталог подарков"))
    kb.add(KeyboardButton("Моя коллекция"))
    kb.add(KeyboardButton("Баланс"))
    return kb

# --- Bot handlers ---
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await get_user(message.from_user.id, message.from_user.username)
    text = "Добро пожаловать в DARIKUM! Открывай кейсы, собирай коллекцию и трать Stars (⭐)."
    await message.answer(text, reply_markup=main_keyboard())

@dp.message_handler(lambda m: m.text == "Открыть кейс")
async def open_case_menu(message: types.Message):
    await message.answer("Выберите кейс:", reply_markup=list_cases_kb())

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("open_case:"))
async def process_open_case(cb: types.CallbackQuery):
    _, case_id = cb.data.split(":", 1)
    case = next((c for c in CATALOG["cases"] if c["id"] == case_id), None)
    if not case:
        await cb.answer("Кейс не найден", show_alert=True)
        return
    user = await get_user(cb.from_user.id, cb.from_user.username)
    if user["stars"] < case["price"]:
        await cb.answer("Недостаточно Stars", show_alert=True)
        return
    # charge user
    await change_stars(cb.from_user.id, -case["price"])
    # simulate animation by editing message
    msg = await bot.send_message(cb.from_user.id, "Открываем кейс... Пожалуйста, подождите ⏳")
    # short fake animation
    for i in range(3):
        await asyncio.sleep(1.0)
        try:
            await bot.edit_message_text(f"Открываем кейс... Идёт генерация подарка{'.'*(i+1)}", cb.from_user.id, msg.message_id)
        except Exception:
            pass
    # choose random item by weights
    items = case["items"]
    weights = [it.get("weight", 1) for it in items]
    chosen = random.choices(items, weights=weights, k=1)[0]
    # add to collection
    added = await add_to_collection(cb.from_user.id, chosen)
    res_text = f"Вы получили: {chosen['title']} ({chosen.get('rarity','common')})\n"
    if added:
        res_text += "Предмет добавлен в вашу коллекцию!"
    else:
        res_text += "У вас уже был этот предмет."
    # show result
    await bot.edit_message_text(res_text, cb.from_user.id, msg.message_id)
    await cb.answer()

@dp.message_handler(lambda m: m.text == "Каталог подарков")
async def catalog_cmd(message: types.Message):
    text_lines = []
    for case in CATALOG["cases"]:
        text_lines.append(f"{case['title']} — {case['price']} ⭐")
    await message.answer("Каталог кейсов:\n" + "\n".join(text_lines), reply_markup=list_cases_kb())

@dp.message_handler(lambda m: m.text == "Моя коллекция")
async def my_collection(message: types.Message):
    col = await get_collection(message.from_user.id)
    if not col:
        await message.answer("Ваша коллекция пуста. Откройте кейсы чтобы получить предметы.")
        return
    lines = [f"{i+1}. {it['title']} ({it['rarity']})" for i, it in enumerate(col)]
    await message.answer("Ваша коллекция:\n" + "\n".join(lines))

@dp.message_handler(lambda m: m.text == "Баланс")
async def balance_cmd(message: types.Message):
    user = await get_user(message.from_user.id, message.from_user.username)
    await message.answer(f"Ваш баланс: {user['stars']} ⭐\n(стартовый баланс выдан при первом запуске)")

@dp.message_handler(commands=["addstars"])
async def addstars_test(message: types.Message):
    # тестовая команда для добавления монет (в идеале: только для админа)
    args = message.get_args()
    try:
        delta = int(args)
    except:
        await message.answer("Использование: /addstars 100")
        return
    new = await change_stars(message.from_user.id, delta)
    await message.answer(f"Баланс обновлён: {new} ⭐")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init_db())
    executor.start_polling(dp, skip_updates=True)
