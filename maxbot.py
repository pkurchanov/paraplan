import asyncio
import logging
from datetime import datetime
from typing import Callable, TypedDict

from maxapi import Bot, Dispatcher
from maxapi.enums import Format
from maxapi.types import BotStarted, Command, MessageCallback, MessageCreated
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from parser import Table, Workweek, normalize
from parser import main as load_schedule
from tokens import TOKEN

bot = Bot(TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

FilterFunc = Callable[[str], list[Table]]


class Context(TypedDict):
    filter_by: FilterFunc
    search_term: str
    tables: list[Table]
    index: int


SEARCH_RESULTS_SHOWN = 10
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


schedule: list[Table] = []
codes: set[str] = set()
names: set[str] = set()
user_context: dict[int, Context] = {}
listening: bool = False

# Потенциальные улучшения:
# - Мемоизировать уже отфильтрованные таблицы
# - Преднормализовать поисковые метки
# - Ввести TTL для кэшей


async def load_tables(force: bool = False):
    """Загружает таблицы и обновляет поисковые метки"""
    global schedule, codes, names
    if force or not schedule:
        schedule = load_schedule()
        codes.clear()
        names.clear()
        codes.update(t[2] for t in schedule)
        names.update(
            name
            for table in schedule
            for day in table[3]
            for lesson in day
            if (name := lesson[0]) and name not in ("", "ВЫХОДНОЙ ДЕНЬ")
        )


async def try_load_tables(event: MessageCreated | MessageCallback, force: bool = False):
    """Более осторожный младший брат load_tables"""
    send_message = pick_message_sender(event)
    try:
        await load_tables(force)
    except Exception as e:
        await send_message(
            text=f"⚠️ Возникла проблема при загрузке таблиц:\n{e}",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )


def filter_by_code(code: str) -> list[Table]:
    """Фильтрует расписание по коду группы"""
    global schedule
    return [table for table in schedule if table[2] == code]


def filter_by_name(name: str) -> list[Table]:
    """Собирает расписание по имени преподавателя"""
    global schedule
    date_map = {}
    for date, _, code, days in schedule:
        if date not in date_map:
            date_map[date] = [[] for _ in days]
        for day_idx, day in enumerate(days):
            for slot, c in enumerate(day):
                if len(c) == 5 and c[0] == name:
                    date_map[date][day_idx].append((slot, code, c[1], c[2], c[3], c[4]))
    result = []
    for date in date_map:
        new_days = []
        for day_slots in date_map[date]:
            if not day_slots:
                new_days.append([("",)])
                continue
            by_slot = {}
            for slot, code, cname, form, room, link in day_slots:
                by_slot.setdefault(slot, []).append((code, cname, form, room, link))
            filtered_day = []
            for slot in sorted(by_slot.keys()):
                entries = by_slot[slot]
                if len(entries) == 1:
                    filtered_day.append(entries[0])
                else:
                    codes = ", ".join(dict.fromkeys(e[0] for e in entries))
                    _, cname, form, room, link = entries[0]
                    filtered_day.append((codes, cname, form, room, link))
            new_days.append(filtered_day if filtered_day else [("",)])
        result.append((date, "", name, new_days))
    return result


def get_sorted_tables(filtered_tables: list[Table]) -> list[Table]:
    """Возвращает таблицы, отсортированные по дате (от новых к старым)"""
    return sorted(filtered_tables, key=lambda x: x[0], reverse=True)


def pick_current_table(tables: list[Table]) -> Table:
    """Выбирает позднейшую из недель, начавшихся до сегодняшнего дня"""
    curr_date = datetime.now().date()
    return max((t for t in tables if t[0] < curr_date), key=lambda x: x[0])


def make_header(table: Table, filter_by: FilterFunc, search_term: str) -> str:
    """Формирует заголовок расписания"""
    entity_type = "преподавателя" if filter_by is filter_by_name else "группы"
    return f"🗓️ Расписание на **{table[0]}** для {entity_type} {search_term}:\n"


def make_content(workweek: Workweek) -> str:
    """Формирует текст расписания"""
    to_display = ""
    for day_idx, day in enumerate(workweek):
        has_content = False
        for c in day:
            if c[0]:
                has_content = True
                break
        if not has_content:
            continue
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
                class_form = c[2] if not c[4] else f"[{c[2]}]({c[4]})"
                to_display += f"> {NUMBERS[class_idx]} {class_name}\n"
                to_display += f"👤 *{instr_or_group_name}*\n"
                to_display += f"🚪 *{class_form}, {class_room}*\n\n"
    if not to_display.strip():
        return "> Нет занятий на эту неделю ✨\n"
    return to_display


def make_navigation() -> InlineKeyboardBuilder:
    """Формирует клавиатуру для навигации"""
    return (
        InlineKeyboardBuilder()
        .row(
            CallbackButton(text="⬅️ Пред. неделя", payload="prev"),
            CallbackButton(text="След. неделя ➡️", payload="next"),
        )
        .row(SEARCH_BUTTON)
    )


async def serve(event: MessageCallback, filter_by: FilterFunc, search_term: str):
    """Оркестрирует формирование сообщения и обновление контекста"""
    send_message = pick_message_sender(event)
    filtered_tables = filter_by(search_term)
    sorted_tables = get_sorted_tables(filtered_tables)
    curr_table = pick_current_table(filtered_tables)
    try:
        curr_idx = next(i for i, t in enumerate(sorted_tables) if t[0] == curr_table[0])
    except StopIteration:
        curr_idx = 0
    user_id = event.callback.user.user_id
    user_context[user_id] = {
        "filter_by": filter_by,
        "search_term": search_term,
        "tables": sorted_tables,
        "index": curr_idx,
    }
    navigation = make_navigation()
    header = make_header(curr_table, filter_by, search_term)
    content = make_content(curr_table[3])
    await send_message(
        text=header + content,
        attachments=[navigation.as_markup()],
        format=Format.MARKDOWN,
    )


async def handle_navigation(event: MessageCallback, user_id: int, direction: str):
    """Обрабатывает переключение недель"""
    send_message = pick_message_sender(event)
    context = user_context.get(user_id)
    if not context:
        await send_message(
            text="⚠️ Сессия истекла. Начните поиск заново.",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )
        return
    tables = context["tables"]
    curr_idx = context["index"]
    if direction == "next":
        new_idx = curr_idx - 1
    else:
        new_idx = curr_idx + 1
    if new_idx < 0 or new_idx >= len(tables):
        boundary_msg = (
            "Это последняя доступная неделя 📚"
            if direction == "next"
            else "📚 Это самая ранняя запись в архиве"
        )
        await send_message(
            text=boundary_msg,
            attachments=[make_navigation().as_markup()],
            format=Format.MARKDOWN,
        )
        return
    context["index"] = new_idx
    selected_table = tables[new_idx]
    header = make_header(selected_table, context["filter_by"], context["search_term"])
    content = make_content(selected_table[3])
    await send_message(
        text=header + content,
        attachments=[make_navigation().as_markup()],
        format=Format.MARKDOWN,
    )


def pick_message_sender(event: MessageCreated | MessageCallback) -> Callable:
    """Решает между редактированием и отправкой нового сообщения смотря откуда вызван"""
    return event.message.answer if type(event) is MessageCreated else event.message.edit  # ty:ignore[unresolved-attribute]


@dp.bot_started()
async def greet(event: BotStarted):
    await bot.send_message(
        chat_id=event.chat_id,
        text="🪂 Доступные команды:\n"
        + "> /search\n\nНачать поиск по группе или по имени преподавателя\n"
        + "> /refresh\n\nОбновить имеющиеся данные о расписаниях\n",
        format=Format.MARKDOWN,
    )


@dp.message_created(Command("search"))
async def searchbar_summoner(event: MessageCreated | MessageCallback):
    send_message = pick_message_sender(event)
    global listening
    await try_load_tables(event)
    await send_message(
        text="Напишите код группы или ФИО преподавателя",
        attachments=[],
    )
    listening = True


@dp.message_created()
async def search_handler(event: MessageCreated):
    send_message = pick_message_sender(event)
    global listening
    if listening:
        try:
            if event.message.body:
                query = normalize(event.message.body.text)
            search_results = InlineKeyboardBuilder()
            search_results_shown = 0
            for term in codes | names:
                if query in normalize(term):
                    search_results.row(CallbackButton(text=term, payload=term))
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


@dp.message_created(Command("refresh"))
async def refresh_handler(event: MessageCreated):
    send_message = pick_message_sender(event)
    try:
        await try_load_tables(event, force=True)
        await send_message(text="✅ Расписание обновлено")
    except Exception as e:
        await send_message(text=f"⚠️ Ошибка обновления: {e}")


@dp.message_callback()
async def button_handler(event: MessageCallback):
    await try_load_tables(event)
    button_pressed = event.callback.payload
    user_id = event.callback.user.user_id
    if button_pressed in codes:
        await serve(event, filter_by_code, button_pressed)
    elif button_pressed in names:
        await serve(event, filter_by_name, button_pressed)
    elif button_pressed in ("next", "prev"):
        await handle_navigation(event, user_id, button_pressed)
    elif button_pressed == "back":
        await searchbar_summoner(event)
    else:
        logging.log(level=logging.ERROR, msg=f"Нераспознанный ключ: {button_pressed}")


async def main():
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
