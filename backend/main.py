import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from handlers.message import router as message_router
from handlers.callback import router as callback_router
from handlers.availability import router as availability_router   # ← новое

async def main():
    if not BOT_TOKEN:
        raise ValueError("Не задан TELEGRAM_BOT_TOKEN в файле .env")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(availability_router)   # ← лучше раньше message/callback
    dp.include_router(message_router)
    dp.include_router(callback_router)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())