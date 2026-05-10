import asyncio
import logging

from parser import main as load_schedule, normalize
from keys import TEST_TOKEN
from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

logging.basicConfig(level=logging.INFO)
bot = Bot(TEST_TOKEN)
dp = Dispatcher()
MAX_SEARCH_RESULTS_SHOWN = 5
SEARCH_BUTTON = CallbackButton(text="🔍 Назад в поиск", payload="back")

schedule = None
codes = set()
names = set()
listening: bool = False


def load_tables():
    """Загружает таблицы и обновляет поисковые метки, если еще не закэшированы"""
    global schedule
    if not schedule:
        schedule = load_schedule()
    if not codes or not names:
        codes.update(t[2] for t in schedule)
        names.update(
            name
            for table in schedule
            for day in table[3]
            for lesson in day
            if (name := lesson[0]) and name not in ("", "ВЫХОДНОЙ ДЕНЬ")
        )


def filter_by_code():
    raise NotImplementedError


def filter_by_name():
    raise NotImplementedError


def message_sender(event):
    return event.message.answer if type(event) is MessageCreated else event.message.edit


async def try_load_tables(event):
    """Более осторожный младший брат load_tables"""
    send_message = message_sender(event)
    try:
        load_tables()
    except Exception as e:
        await send_message(
            text=f"⚠️ Возникла проблема при загрузке таблиц:\n{e}",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )


@dp.message_created(Command("rasp"))
async def menu_handler(event):
    send_message = message_sender(event)
    global listening
    await try_load_tables(event)
    await send_message(
        text="Напишите код группы или ФИО преподавателя",
        attachments=[],
    )
    listening = True


@dp.message_created()
async def search_handler(event):
    send_message = message_sender(event)
    global listening
    if listening:
        try:
            query = normalize(event.message.body.text)
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
                search_results.row(SEARCH_BUTTON)
                await send_message(
                    text="Найдено:",
                    attachments=[search_results.as_markup()],
                )
        except Exception as e:
            await send_message(text=f"{e}\n\nПопробуйте еще раз")
        else:
            listening = False


@dp.message_callback()
async def button_handler(event):
    send_message = message_sender(event)
    # Всегда свежие данные
    await try_load_tables(event)

    filter_chosen = event.callback.payload
    navigation = (
        InlineKeyboardBuilder()
        .row(
            CallbackButton(text="⬅️ Пред. неделя", payload="prev"),
            CallbackButton(text="След. неделя ➡️", payload="next"),
        )
        .row(SEARCH_BUTTON)
    )
    if filter_chosen in codes:
        await send_message(
            text=f"Расписание для группы {filter_chosen}",
            attachments=[navigation.as_markup()],
        )
    elif filter_chosen in names:
        await send_message(
            text=f"Расписание для преподавателя {filter_chosen}",
            attachments=[navigation.as_markup()],
        )
    elif filter_chosen == "next":
        raise NotImplementedError
    elif filter_chosen == "prev":
        raise NotImplementedError
    elif filter_chosen == "back":
        await menu_handler(event)
    else:
        logging.log(level=logging.ERROR, msg=f"Нераспознанный ключ: {filter_chosen}")


async def main():
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
