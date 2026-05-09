import asyncio
import logging
from parser import main as load_schedule, wash
from keys import TEST_TOKEN
from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command, MessageCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

logging.basicConfig(level=logging.INFO)
bot = Bot(TEST_TOKEN)
dp = Dispatcher()

schedule = None
codes = set()
names = set()
listening: bool = False


@dp.message_created(Command("rasp"))
async def start_handler(event: MessageCreated):
    global schedule
    global listening
    try:
        schedule = load_schedule()
    except Exception as e:
        await event.message.answer(text=f"⚠️ Ошибка при загрузке расписаний: {e}")
    else:
        await event.message.answer(text="Напишите код группы или ФИО преподавателя")
        codes.update(t[2] for t in schedule)  # ty:ignore[not-iterable]
        names.update(
            name
            for table in schedule  # ty:ignore[not-iterable]
            for day in table[3]
            for lesson in day
            if (name := lesson[0]) and name not in ("", "ВЫХОДНОЙ ДЕНЬ")
        )
        listening = True


@dp.message_created()
async def search_handler(event: MessageCreated):
    global listening
    if listening:
        query = wash(event.message.body.text)  # ty:ignore[unresolved-attribute]
        keyboard = InlineKeyboardBuilder()
        keyboard_height = 0
        for term in codes | names:
            if query in wash(term):
                keyboard.row(CallbackButton(text=term, payload=term))
                keyboard_height += 1
                if keyboard_height == 5:
                    break
        await event.message.answer(text="Найдено:", attachments=[keyboard.as_markup()])
        listening = False


@dp.message_callback()
async def button_handler(event: MessageCallback):
    term_clicked = event.callback.payload
    # TODO: отфильтровать и вывести само расписание
    if term_clicked in codes:
        await event.message.edit(  # ty:ignore[unresolved-attribute]
            text=f"Расписание группы {term_clicked}", attachments=[]
        )
    else:
        await event.message.edit(  # ty:ignore[unresolved-attribute]
            text=f"Расписание преподавателя {term_clicked}", attachments=[]
        )


async def main():
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
