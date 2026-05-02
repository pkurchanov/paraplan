import asyncio
from parser import main as parse
from keys import TEST_TOKEN
from maxapi import Bot, Dispatcher

# TODO:
# - Принять теги для фильтрации
# - Отфильтровать
# - Красиво подать (как встроенное веб приложение)

bot = Bot(TEST_TOKEN)
dp = Dispatcher()


async def main():
    try:
        tables = parse()
    except Exception as e:
        print(f"Произошла ошибка при обработке таблиц: {e}")
        return e
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
