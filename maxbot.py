import asyncio
import logging
from collections.abc import Callable
from datetime import date, datetime
from typing import TypedDict
from zoneinfo import ZoneInfo

from maxapi import Bot, Dispatcher
from maxapi.enums import Format
from maxapi.types import BotStarted, Command, MessageCallback, MessageCreated
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from parser import FullClass, Table, Workday, Workweek, normalize
from parser import main as load_schedule
from tokens import TOKEN

logging.basicConfig(level=logging.INFO)
bot = Bot(TOKEN, format=Format.MARKDOWN)
dp = Dispatcher()

FilterFunc = Callable[[str], list[Table]]


class Context(TypedDict, total=False):
    filter_by: FilterFunc
    search_term: str
    tables: list[Table]
    index: int
    listening: bool


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


schedule: list[Table] = []
codes: set[str] = set()
names: set[str] = set()
user_context: dict[int, Context] = {}

# Потенциальные улучшения:
# - Мемоизировать уже отфильтрованные таблицы
# - Преднормализовать поисковые метки
# - Автоматически обновлять кэш


async def load_tables(force: bool = False):
    """Загружает таблицы и обновляет поисковые метки"""
    global schedule, codes, names  # noqa: PLW0602
    if force or not schedule:
        schedule = load_schedule()
        codes.clear()
        names.clear()
        codes.update(t[1] for t in schedule)
        names.update(
            name
            for table in schedule
            for day in table[2]
            for lesson in day
            if lesson not in ("", "ВЫХОДНОЙ ДЕНЬ") and (name := lesson[0])
        )


def filter_by_code(code: str) -> list[Table]:
    """Фильтрует расписание по коду группы"""
    return [table for table in schedule if table[1] == code]


def filter_by_name(name: str) -> list[Table]:
    """Собирает расписание по имени преподавателя"""

    class _AggCell(TypedDict):
        groups: list[str]
        data: FullClass | None

    agg: dict[str, dict[date, list[list[_AggCell]]]] = {}
    for t_date, group_code, workweek in schedule:
        for day_idx, workday in enumerate(workweek):
            for slot_idx, ts in enumerate(workday):
                if not isinstance(ts, tuple):
                    continue
                instructor = ts[0]
                if instructor not in agg:
                    agg[instructor] = {}
                if t_date not in agg[instructor]:
                    agg[instructor][t_date] = [
                        [{"groups": [], "data": None} for _ in range(4)]
                        for _ in range(6)
                    ]
                cell = agg[instructor][t_date][day_idx][slot_idx]
                cell["groups"].append(group_code)
                if cell["data"] is None:
                    cell["data"] = ts
    result: list[Table] = []
    for instructor, dates_dict in agg.items():
        if name and instructor.lower() != name.lower():
            continue
        for t_date, workweek_structure in dates_dict.items():
            new_workweek: Workweek = []
            for day_idx in range(6):
                new_workday: Workday = []
                for slot_idx in range(4):
                    cell = workweek_structure[day_idx][slot_idx]
                    if not cell["groups"]:
                        new_workday.append("")
                        continue
                    groups_str = ", ".join(sorted(set(cell["groups"])))
                    orig_data = cell["data"]
                    if orig_data is None:
                        continue
                    new_ts: FullClass = (
                        groups_str,
                        orig_data[1],
                        orig_data[2],
                        orig_data[3],
                        orig_data[4],
                        orig_data[5],
                    )
                    new_workday.append(new_ts)
                new_workweek.append(new_workday)
            result.append((t_date, instructor, new_workweek))
    return result


def get_sorted_tables(filtered_tables: list[Table]) -> list[Table]:
    """Возвращает таблицы, отсортированные по дате (от новых к старым)"""
    return sorted(filtered_tables, key=lambda x: x[0], reverse=True)


def pick_current_table(tables: list[Table]) -> Table:
    """Выбирает позднейшую из недель, начавшихся до сегодняшнего дня"""
    curr_date = datetime.now(ZoneInfo("Asia/Krasnoyarsk")).date()
    return max((t for t in tables if t[0] < curr_date), key=lambda x: x[0])


def make_header(table: Table, filter_by: FilterFunc, search_term: str) -> str:
    """Формирует заголовок расписания"""
    entity_type = "преподавателя" if filter_by is filter_by_name else "группы"
    return f"🗓️ Расписание на **{table[0]}** для {entity_type} {search_term}:\n"


def make_content(workweek: Workweek) -> str:
    """Формирует текст расписания"""
    message_text = ""
    for day_idx, day in enumerate(workweek):
        message_text += DAYS_OF_WEEK[day_idx]
        day_text = ""
        for ts_idx, ts in enumerate(day):
            if ts == "":
                continue
            elif ts == "выходной день":
                day_text += "> Выходной день 🎉\n"
                break
            else:
                name_or_codes = ts[0]
                class_name, class_room, class_time = ts[1], ts[3], ts[5]
                # Кликабельно если есть ссылка
                class_form = f"[{ts[2]}]({ts[4]})" if ts[4] else ts[2]
                day_text += (
                    f"> {NUMBERS[ts_idx]} {class_name}\n"
                    + f"👤 *{name_or_codes}*\n"
                    + f"🕰️ *{class_time}*\n"
                    + f"🚪 *{class_form}, {class_room}*\n\n"
                )
        if not day_text:
            day_text += "> Нет занятий 🍃\n"
        message_text += day_text
    return message_text


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
    content = make_content(curr_table[2])
    await send_message(
        text=header + content,
        attachments=[navigation.as_markup()],
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
            "⚠️ **Это последняя доступная неделя** 📚\n\n"
            if direction == "next"
            else "📚 **Это самая ранняя запись в архиве** ⚠️\n\n"
        )
        selected_table = tables[curr_idx]
        header = make_header(
            selected_table, context["filter_by"], context["search_term"]
        )
        content = make_content(selected_table[2])

        await send_message(
            text=boundary_msg + header + content,
            attachments=[make_navigation().as_markup()],
        )
        return

    context["index"] = new_idx
    selected_table = tables[new_idx]
    header = make_header(selected_table, context["filter_by"], context["search_term"])
    content = make_content(selected_table[2])

    await send_message(
        text=header + content,
        attachments=[make_navigation().as_markup()],
    )


def pick_message_sender(event: MessageCreated | MessageCallback) -> Callable:
    """Решает между редактированием и отправкой нового сообщения смотря откуда вызван"""
    return event.message.answer if type(event) is MessageCreated else event.message.edit  # ty:ignore[unresolved-attribute]


def get_user_id(event: MessageCreated | MessageCallback) -> int:
    if type(event) is MessageCreated:
        return getattr(getattr(event.message, "user", event.message), "user_id", 0)
    return event.callback.user.user_id  # ty:ignore[unresolved-attribute]


@dp.bot_started()
async def greet(event: BotStarted):
    await bot.send_message(
        chat_id=event.chat_id,
        text="🪂 Доступные команды:\n"
        + "> /search\n\nПоиск по группе или по имени преподавателя\n"
        + "> /refresh\n\nОбновить данные о расписаниях\n",
    )


@dp.message_created(Command("search"))
async def searchbar_summoner(event: MessageCreated | MessageCallback):
    send_message = pick_message_sender(event)
    user_id = get_user_id(event)
    try:
        await load_tables()
        await send_message(
            text="Напишите код группы или ФИО преподавателя",
            attachments=[],
        )
        if user_id not in user_context:
            user_context[user_id] = {}
        user_context[user_id]["listening"] = True
    except Exception as e:
        await send_message(text=f"⚠️ Ошибка загрузки таблиц: {e}")


@dp.message_created()
async def search_handler(event: MessageCreated):
    send_message = pick_message_sender(event)
    user_id = get_user_id(event)
    if user_context.get(user_id, {}).get("listening"):
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
            user_context[user_id]["listening"] = False


@dp.message_created(Command("refresh"))
async def refresh_handler(event: MessageCreated):
    send_message = pick_message_sender(event)
    try:
        await load_tables(force=True)
        await send_message(text="✅ Расписание обновлено")
    except Exception as e:
        await send_message(text=f"⚠️ Ошибка обновления таблиц: {e}")


@dp.message_callback()
async def button_handler(event: MessageCallback):
    await load_tables()
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
