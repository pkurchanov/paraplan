import asyncio
from parser import main as parse
from keys import TEST_TOKEN
from maxapi import Bot, Dispatcher

# TODO:
# - Написать и где-то поместить мини-приложение
# - Скармливать ему: роль (студент/преподаватель), группу (если студент), фамилию (если преподаватель)
# - Фильтровать таблицы по соответствующему критерию
# - Получать обратно красивую страничку с расписанием

bot = Bot(TEST_TOKEN)
dp = Dispatcher()

_schedule_cache = None


def load_schedule():
    """Загружает и кэширует расписание"""
    global _schedule_cache
    if not _schedule_cache:
        _schedule_cache = parse()
    return _schedule_cache


async def main():
    try:
        load_schedule()
        print("✅ Расписание загружено")
    except Exception as e:
        print(f"⚠️ Ошибка загрузки расписания: {e}")
        return e
    finally:
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
