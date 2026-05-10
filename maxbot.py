import asyncio
import logging

from datetime import datetime
from parser import main as load_schedule, normalize
from keys import TEST_TOKEN
from maxapi import Bot, Dispatcher
from maxapi.enums import Format
from maxapi.types import MessageCreated, Command
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
from maxapi.types.attachments.buttons import CallbackButton

logging.basicConfig(level=logging.INFO)
bot = Bot(TEST_TOKEN)
dp = Dispatcher()

SEARCH_RESULTS_SHOWN = 5
SEARCH_BUTTON = CallbackButton(text="🔍 Назад в поиск", payload="back")
DAYS_OF_WEEK = (
    "# ☕️ Понедельник\n",
    "# 📈 Вторник\n",
    "# 🐪 Среда\n",
    "# ⏳ Четверг\n",
    "# 🔥 Пятница\n",
    "# 😴 Суббота\n",
)
NUMBERS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣")

schedule = []
codes = set()
names = set()
listening: bool = False


def load_tables():
    """Загружает таблицы и обновляет поисковые метки"""
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


async def try_load_tables(event):
    """Более осторожный младший брат load_tables"""
    send_message = pick_message_sender(event)
    try:
        load_tables()
    except Exception as e:
        await send_message(
            text=f"⚠️ Возникла проблема при загрузке таблиц:\n{e}",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )


def filter_by_code(code):
    global schedule
    return [table for table in schedule if table[2] == code]


def filter_by_name(name):
    global schedule
    raise NotImplementedError


def pick_current_table(tables):
    """Выбирает позднейшую из недель, начавшихся до сегодняшнего дня"""
    curr_data = datetime.now().date()
    return max((t for t in tables if t[0] < curr_data), key=lambda x: x[0])


def prettyprint(workweek):
    to_display = ""
    for day_idx, day in enumerate(workweek):
        to_display += DAYS_OF_WEEK[day_idx]
        for class_idx, c in enumerate(day):
            if c[0] == "":
                continue
            elif c[0] == "ВЫХОДНОЙ ДЕНЬ":
                to_display += "> Выходной день 🎉\n"
                break
            else:
                instr_or_group_name = c[0]
                class_name = c[1]
                class_room = c[3]
                # Чистый текст если нет ссылки, иначе кликабельный
                class_form = c[2] if not c[4] else f"[{c[2]}]({c[4]})"

                to_display += f"> {NUMBERS[class_idx]} {class_name}\n"
                to_display += f"👤 *{instr_or_group_name}*\n"
                to_display += f"🚪 *{class_form}, {class_room}*\n\n"
    return to_display


async def serve(event, filter_by, filter):
    navigation = (
        InlineKeyboardBuilder()
        .row(
            CallbackButton(text="⬅️ Пред. неделя", payload="prev"),
            CallbackButton(text="След. неделя ➡️", payload="next"),
        )
        .row(SEARCH_BUTTON)
    )
    send_message = pick_message_sender(event)
    filtered_tables = filter_by(filter)
    current_table = pick_current_table(filtered_tables)
    header = f"🗓️ Расписание на **{current_table[0]}** для {'преподавателя' if filter_by is filter_by_name else 'группы'} {filter}:\n"
    content = prettyprint(current_table[3])
    await send_message(
        text=header + content,
        attachments=[navigation.as_markup()],
        format=Format.MARKDOWN,
    )


def pick_message_sender(event):
    return event.message.answer if type(event) is MessageCreated else event.message.edit


@dp.message_created(Command("rasp"))
async def menu_handler(event):
    send_message = pick_message_sender(event)
    global listening
    await try_load_tables(event)
    await send_message(
        text="Напишите код группы или ФИО преподавателя",
        attachments=[],
    )
    listening = True


@dp.message_created()
async def search_handler(event):
    send_message = pick_message_sender(event)
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
                    if search_results_shown == SEARCH_RESULTS_SHOWN:
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
    # Всегда свежие данные
    await try_load_tables(event)

    button_pressed = event.callback.payload
    if button_pressed in codes:
        await serve(event, filter_by_code, button_pressed)
    elif button_pressed in names:
        await serve(event, filter_by_name, button_pressed)
    elif button_pressed == "next":
        raise NotImplementedError
    elif button_pressed == "prev":
        raise NotImplementedError
    elif button_pressed == "back":
        await menu_handler(event)
    else:
        logging.log(level=logging.ERROR, msg=f"Нераспознанный ключ: {button_pressed}")


async def main():
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
