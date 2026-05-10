import asyncio
import logging
from parser import main as load_schedule, normalize
from keys import TEST_TOKEN
from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command, MessageCallback
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

logging.basicConfig(level=logging.INFO)
bot = Bot(TEST_TOKEN)
dp = Dispatcher()
MAX_SEARCH_RESULTS_SHOWN = 5

schedule = None
codes = set()
names = set()
listening: bool = False


def update_searchables():
    global schedule
    codes.update(t[2] for t in schedule)  # ty:ignore[not-iterable]
    names.update(
        name
        for table in schedule  # ty:ignore[not-iterable]
        for day in table[3]
        for lesson in day
        if (name := lesson[0]) and name not in ("", "ВЫХОДНОЙ ДЕНЬ")
    )


@dp.message_created(Command("rasp"))
async def menu(event: MessageCreated | MessageCallback):
    global schedule
    global listening
    send_message = (
        event.message.answer if type(event) is MessageCreated else event.message.edit  # ty:ignore[unresolved-attribute]
    )
    try:
        schedule = load_schedule()
    except Exception as e:
        await send_message(
            text=f"⚠️ {e}",
            attachments=[],
        )
    else:
        await send_message(
            text="Напишите код группы или ФИО преподавателя",
            attachments=[],
        )
        update_searchables()
        listening = True


@dp.message_created()
async def search_handler(event: MessageCreated):
    global listening
    if listening:
        try:
            query = normalize(event.message.body.text)  # ty:ignore[unresolved-attribute]
            search_results = InlineKeyboardBuilder()
            search_results_shown = 0
            for searchable in codes | names:
                if query in normalize(searchable):
                    search_results.row(
                        CallbackButton(text=searchable, payload=searchable)
                    )
                    search_results_shown += 1
                    if search_results_shown == MAX_SEARCH_RESULTS_SHOWN:
                        break
            if search_results_shown == 0:
                raise Exception("Ничего не найдено :(")
            else:
                search_results.row(
                    CallbackButton(text="🔍 Назад в поиск", payload="back")
                )
                await event.message.answer(
                    text="Найдено:",
                    attachments=[search_results.as_markup()],
                )
        except Exception as e:
            await event.message.answer(text=f"{e}\n\nПопробуйте еще раз")
        else:
            listening = False


@dp.message_callback()
async def button_handler(event: MessageCallback):
    filter_chosen = event.callback.payload
    navigation = (
        InlineKeyboardBuilder()
        .row(
            CallbackButton(text="⬅️ Пред. неделя", payload="prev"),
            CallbackButton(text="След. неделя ➡️", payload="next"),
        )
        .row(CallbackButton(text="🔍 Назад в поиск", payload="back"))
    )
    if filter_chosen in codes:
        await event.message.edit(  # ty:ignore[unresolved-attribute]
            text=f"Расписание для группы {filter_chosen}",
            attachments=[navigation.as_markup()],
        )
    elif filter_chosen in names:
        await event.message.edit(  # ty:ignore[unresolved-attribute]
            text=f"Расписание для преподавателя {filter_chosen}",
            attachments=[navigation.as_markup()],
        )
    elif filter_chosen == "next":
        logging.log(level=logging.WARN, msg="TO BE IMPLEMENTED")
    elif filter_chosen == "prev":
        logging.log(level=logging.WARN, msg="TO BE IMPLEMENTED")
    elif filter_chosen == "back":
        await menu(event)
    else:
        logging.log(level=logging.ERROR, msg=f"Нераспознанный ключ: {filter_chosen}")


async def main():
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
