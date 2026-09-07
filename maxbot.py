import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from datetime import date, datetime
from typing import TypedDict

from dotenv import load_dotenv
from maxapi import Bot, Dispatcher
from maxapi.enums import Format
from maxapi.types import BotStarted, Command, MessageCallback, MessageCreated
from maxapi.types.attachments.buttons import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from parser import DAY_OFF, EMPTY, TZ, FullClass, Table, Workday, Workweek, normalize
from parser import main as load_schedule

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

bot = Bot(format=Format.MARKDOWN)
dp = Dispatcher()

FilterFunc = Callable[[str], list[Table]]


class Context(TypedDict, total=False):
    listening: bool
    updated_at: datetime


SEARCH_RESULTS_SHOWN = 5
NAV_BACK = "nav:back"
SEARCH_BUTTON = CallbackButton(text="🔍 Назад в поиск", payload=NAV_BACK)
DAYS_OF_WEEK = (
    "# ☕️ Понедельник\n ",
    "# 📈 Вторник\n ",
    "# 🐪 Среда\n ",
    "# ⏳ Четверг\n ",
    "# 🔥 Пятница\n ",
    "# 😴 Суббота\n ",
)
NUMBERS = ("1️⃣ ", "2️⃣ ", "3️⃣ ", "4️⃣ ")

schedule: list[Table] = []
codes: set[str] = set()
names: set[str] = set()
user_context: dict[int, Context] = {}

# Индексы и преднормализованные поисковые метки
code_index: dict[str, list[Table]] = {}
teacher_index: dict[str, list[Table]] = {}
search_terms: list[tuple[str, str]] = []
schedule_loaded = False

RENDER_CACHE_LIMIT = 1000
_render_cache: OrderedDict[tuple[date, str, str, str], str] = OrderedDict()

SCHEDULE_REFRESH_SECONDS = 30 * 60
USER_CONTEXT_TTL_SECONDS = 30 * 60
USER_CONTEXT_CLEANUP_SECONDS = 60

_load_lock = asyncio.Lock()


def build_code_index(tables: list[Table]) -> dict[str, list[Table]]:
    """Строит индекс расписаний по коду группы"""
    index: dict[str, list[Table]] = {}
    for table in tables:
        index.setdefault(table[1], []).append(table)
    for rows in index.values():
        rows.sort(key=lambda x: x[0], reverse=True)
    return index


def build_teacher_index(
    tables: list[Table],
) -> tuple[dict[str, list[Table]], set[str]]:
    """Строит индекс расписаний по имени преподавателя"""

    class _AggCell(TypedDict):
        groups: list[str]
        data: FullClass | None

    agg: dict[str, dict[date, list[list[_AggCell]]]] = {}
    display_names: dict[str, str] = {}
    teacher_names: set[str] = set()

    for t_date, group_code, workweek in tables:
        for day_idx, workday in enumerate(workweek):
            for slot_idx, ts in enumerate(workday):
                if not isinstance(ts, tuple):
                    continue
                if day_idx >= 6 or slot_idx >= 4:
                    continue

                instructor = ts[0]
                if not instructor:
                    continue

                teacher_names.add(instructor)
                key = normalize(instructor)
                display_names.setdefault(key, instructor)

                dates_dict = agg.setdefault(key, {})
                if t_date not in dates_dict:
                    dates_dict[t_date] = [
                        [{"groups": [], "data": None} for _ in range(4)]
                        for _ in range(6)
                    ]

                cell = dates_dict[t_date][day_idx][slot_idx]
                cell["groups"].append(group_code)
                if cell["data"] is None:
                    cell["data"] = ts

    index: dict[str, list[Table]] = {}
    for key, dates_dict in agg.items():
        instructor = display_names.get(key, key)
        teacher_tables: list[Table] = []

        for t_date, workweek_structure in dates_dict.items():
            new_workweek: Workweek = []
            for day_idx in range(6):
                new_workday: Workday = []
                for slot_idx in range(4):
                    cell = workweek_structure[day_idx][slot_idx]
                    if not cell["groups"]:
                        new_workday.append(EMPTY)
                        continue

                    groups_str = ", ".join(sorted(set(cell["groups"])))
                    orig_data = cell["data"]
                    if orig_data is None:
                        new_workday.append(EMPTY)
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

            teacher_tables.append((t_date, instructor, new_workweek))

        teacher_tables.sort(key=lambda x: x[0], reverse=True)
        index[key] = teacher_tables

    return index, teacher_names


def build_search_terms(codes: set[str], names: set[str]) -> list[tuple[str, str]]:
    """Преднормализует поисковые метки"""
    terms = sorted(codes | names, key=lambda term: (term.lower(), term))
    return [(term, normalize(term)) for term in terms]


def find_search_matches(query: str, limit: int) -> list[str]:
    """Ищет совпадения по меткам"""
    q = normalize(query)
    if not q:
        return []

    ranked: list[tuple[bool, str, str]] = []
    for term, term_norm in search_terms:
        if q in term_norm:
            ranked.append((not term_norm.startswith(q), term.lower(), term))

    ranked.sort()
    return [term for _, _, term in ranked[:limit]]


async def load_tables(force: bool = False):
    """Загружает таблицы и обновляет поисковые метки"""
    global \
        schedule, \
        codes, \
        names, \
        code_index, \
        teacher_index, \
        search_terms, \
        schedule_loaded

    async with _load_lock:
        if force or not schedule_loaded:
            schedule = await asyncio.to_thread(load_schedule)
            code_index = build_code_index(schedule)
            teacher_index, teacher_names = build_teacher_index(schedule)
            codes = set(code_index.keys())
            names = teacher_names
            search_terms = build_search_terms(codes, names)
            schedule_loaded = True
            _render_cache.clear()


def filter_by_code(code: str) -> list[Table]:
    """Фильтрует расписание по коду группы"""
    return code_index.get(code, [])


def filter_by_name(name: str) -> list[Table]:
    """Собирает расписание по имени преподавателя"""
    return teacher_index.get(normalize(name), [])


def get_sorted_tables(filtered_tables: list[Table]) -> list[Table]:
    """Возвращает таблицы, отсортированные по дате (от новых к старым)"""
    return sorted(filtered_tables, key=lambda x: x[0], reverse=True)


def pick_current_table(tables: list[Table]) -> Table | None:
    """Выбирает позднейшую из недель, начавшихся не позже сегодняшнего дня"""
    curr_date = datetime.now(TZ).date()
    eligible = [t for t in tables if t[0] <= curr_date]
    if eligible:
        return max(eligible, key=lambda x: x[0])
    if tables:
        return min(tables, key=lambda x: x[0])
    return None


def touch_user_context(user_id: int):
    """Продлевает время жизни пользовательского контекста"""
    context = user_context.get(user_id)
    if context is not None:
        context["updated_at"] = datetime.now(TZ)


def prune_expired_user_contexts():
    """Удаляет пользовательские контексты с истёкшим временем жизни"""
    now = datetime.now(TZ)
    expired_user_ids = []

    for user_id, context in user_context.items():
        updated_at = context.get("updated_at")
        if (
            updated_at is None
            or (now - updated_at).total_seconds() > USER_CONTEXT_TTL_SECONDS
        ):
            expired_user_ids.append(user_id)

    for user_id in expired_user_ids:
        user_context.pop(user_id, None)


async def maintenance_loop():
    """Фоновая служба: автоматически обновляет кэш и чистит устаревшие контексты"""
    refresh_elapsed = 0

    while True:
        await asyncio.sleep(USER_CONTEXT_CLEANUP_SECONDS)

        try:
            prune_expired_user_contexts()
        except Exception:
            logger.exception("Ошибка очистки пользовательских контекстов")

        refresh_elapsed += USER_CONTEXT_CLEANUP_SECONDS
        if refresh_elapsed >= SCHEDULE_REFRESH_SECONDS:
            try:
                await load_tables(force=True)
                refresh_elapsed = 0
            except Exception:
                logger.exception("Ошибка автоматического обновления таблиц")
                # Не сбрасываем счётчик, чтобы повторить попыку на следующем цикле


def make_header(table: Table, filter_by: FilterFunc, search_term: str) -> str:
    """Формирует заголовок расписания"""
    entity_type = "преподавателя" if filter_by is filter_by_name else "группы"
    return f"Расписание на {table[0]} для {entity_type} {search_term}:\n"


def make_content(workweek: Workweek) -> str:
    """Формирует текст расписания"""
    message_text = ""
    for day_idx, day in enumerate(workweek):
        if day_idx >= len(DAYS_OF_WEEK):
            break
        message_text += DAYS_OF_WEEK[day_idx]
        day_text = ""
        for ts_idx, ts in enumerate(day):
            if ts == EMPTY:
                continue
            elif ts == DAY_OFF:
                day_text += " > Выходной день\n"
                break
            else:
                name_or_codes, class_name, form_type, class_room, link, class_time = (
                    ts[0],
                    ts[1],
                    ts[2],
                    ts[3],
                    ts[4],
                    ts[5],
                )
                number = NUMBERS[ts_idx] if ts_idx < len(NUMBERS) else ""
                header = f" > {number} {class_name}".rstrip()
                teacher_line = f"👤 *{name_or_codes}*" if name_or_codes else ""
                time_line = f"🕰️ *{class_time}*" if class_time else ""
                class_form = (
                    f"[{form_type}]({link})"
                    if (form_type and link)
                    else (form_type or "")
                )
                room_and_form = ", ".join(filter(None, [class_form, class_room]))
                room_line = f"🚪 *{room_and_form}*" if room_and_form else ""
                slot_lines = [
                    line
                    for line in (header, teacher_line, time_line, room_line)
                    if line
                ]
                if slot_lines:
                    day_text += "\n".join(slot_lines) + "\n\n"
        if not day_text:
            day_text += " > Нет занятий\n"
        message_text += day_text
    return message_text


def make_navigation(kind: str, term: str, idx: int) -> InlineKeyboardBuilder:
    """Формирует клавиатуру для навигации с зашитым состоянием"""
    return (
        InlineKeyboardBuilder()
        .row(
            CallbackButton(
                text="⬅️ Пред. неделя", payload=f"page:{kind}:{idx + 1}:{term}"
            ),
            CallbackButton(
                text="След. неделя ➡️", payload=f"page:{kind}:{idx - 1}:{term}"
            ),
        )
        .row(SEARCH_BUTTON)
    )


def render_schedule_message(
    table: Table,
    filter_by: FilterFunc,
    search_term: str,
) -> str:
    """Кэширует собранное сообщение для одной таблицы"""
    kind = "teacher" if filter_by is filter_by_name else "group"
    key = (table[0], table[1], kind, search_term)

    cached = _render_cache.get(key)
    if cached is not None:
        _render_cache.move_to_end(key)
        return cached

    rendered = make_header(table, filter_by, search_term) + make_content(table[2])
    _render_cache[key] = rendered
    _render_cache.move_to_end(key)

    while len(_render_cache) > RENDER_CACHE_LIMIT:
        _render_cache.popitem(last=False)

    return rendered


async def serve(event: MessageCallback, filter_by: FilterFunc, search_term: str):
    """Оркестрирует формирование сообщения"""
    send_message = pick_message_sender(event)
    filtered_tables = filter_by(search_term)

    if not filtered_tables:
        await send_message(
            text="Ничего не найдено",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )
        return

    sorted_tables = get_sorted_tables(filtered_tables)
    curr_table = pick_current_table(sorted_tables)
    if curr_table is None:
        await send_message(
            text="Ничего не найдено",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )
        return

    try:
        curr_idx = next(i for i, t in enumerate(sorted_tables) if t[0] == curr_table[0])
    except StopIteration:
        curr_idx = 0

    kind = "c" if filter_by is filter_by_code else "t"
    message_text = render_schedule_message(curr_table, filter_by, search_term)

    await send_message(
        text=message_text,
        attachments=[make_navigation(kind, search_term, curr_idx).as_markup()],
    )


async def handle_navigation(
    event: MessageCallback, kind: str, new_idx: int, search_term: str
):
    """Обрабатывает переключение недель по данным из payload"""
    send_message = pick_message_sender(event)

    filter_by = filter_by_code if kind == "c" else filter_by_name
    filtered_tables = filter_by(search_term)
    tables = get_sorted_tables(filtered_tables)

    if not tables:
        await send_message(
            text="⚠️ Расписание не найдено! Начните поиск заново",
            attachments=[InlineKeyboardBuilder().row(SEARCH_BUTTON).as_markup()],
        )
        return

    if new_idx < 0 or new_idx >= len(tables):
        boundary_msg = (
            "⚠️ **Это последняя доступная неделя** 📚\n\n"
            if new_idx < 0
            else "📚 **Это самая ранняя запись в архиве** ⚠️\n\n"
        )
        clamped_idx = max(0, min(new_idx, len(tables) - 1))
        selected_table = tables[clamped_idx]
        message_text = render_schedule_message(selected_table, filter_by, search_term)
        await send_message(
            text=boundary_msg + message_text,
            attachments=[make_navigation(kind, search_term, clamped_idx).as_markup()],
        )
        return

    selected_table = tables[new_idx]
    message_text = render_schedule_message(selected_table, filter_by, search_term)
    await send_message(
        text=message_text,
        attachments=[make_navigation(kind, search_term, new_idx).as_markup()],
    )


def pick_message_sender(event: MessageCreated | MessageCallback) -> Callable:
    """Решает между редактированием и отправкой нового сообщения смотря откуда вызван"""
    return event.message.answer if type(event) is MessageCreated else event.message.edit  # ty:ignore[unresolved-attribute]


def get_user_id(event: MessageCreated | MessageCallback) -> int:
    if type(event) is MessageCreated:
        return getattr(getattr(event.message, "user", event.message), "user_id", 0)
    return event.callback.user.user_id  # ty:ignore[unresolved-attribute]


async def enter_search_mode(event: MessageCreated | MessageCallback):
    """Включает режим поиска и сбрасывает устаревший пользовательский контекст"""
    user_id = get_user_id(event)
    send_message = pick_message_sender(event)

    try:
        await load_tables()
    except Exception:
        logger.exception("Ошибка загрузки таблиц при активации поиска")
        try:
            await send_message(text="⚠️ Ошибка загрузки таблиц")
        except Exception:
            logger.exception("Не удалось сообщить об ошибке загрузки таблиц")
        return

    # Контекст сбрасывается до вывода приглашения
    user_context[user_id] = {
        "listening": True,
        "updated_at": datetime.now(TZ),
    }

    try:
        await send_message(
            text="Напишите код группы или ФИО преподавателя",
            attachments=[],
        )
    except Exception:
        logger.exception("Не удалось показать приглашение поиска")
        # Если редактирование не сработало, пробуем отправить обычное сообщение
        fallback_send = getattr(event.message, "answer", None)
        if fallback_send is not None:
            try:
                await fallback_send(text="Напишите код группы или ФИО преподавателя")
            except Exception:
                logger.exception("Не удалось отправить приглашение поиска")


@dp.bot_started()
async def greet(event: BotStarted):
    await bot.send_message(
        chat_id=event.chat_id,
        text="Используйте команду\n"
        + "> /search\n\nдля поиска по группе или по имени преподавателя\n",
    )


@dp.message_created(Command(["search", "s"]))
async def searchbar_summoner(event: MessageCreated | MessageCallback):
    await enter_search_mode(event)


@dp.message_created()
async def search_handler(event: MessageCreated):
    prune_expired_user_contexts()

    send_message = pick_message_sender(event)
    user_id = get_user_id(event)
    text = event.message.body.text if event.message.body else ""

    # Служебные команды обрабатываются отдельными хендлерами
    if text.startswith("/"):  # ty: ignore[unresolved-attribute]
        return

    context = user_context.get(user_id, {})

    if context.get("listening"):
        try:
            if not text:
                raise Exception("Пустой запрос")

            matches = find_search_matches(text, SEARCH_RESULTS_SHOWN)  # ty: ignore[invalid-argument-type]
            if not matches:
                raise Exception("Ничего не найдено")

            search_results = InlineKeyboardBuilder()
            for term in matches:
                search_results.row(CallbackButton(text=term, payload=term))
            search_results.row(SEARCH_BUTTON)

            await send_message(
                text="Найдено:",
                attachments=[search_results.as_markup()],
            )
        except Exception as e:
            await send_message(text=f"{e}\n\nПопробуйте еще раз")
        else:
            if user_id in user_context:
                user_context[user_id]["listening"] = False
        finally:
            if user_id in user_context:
                user_context[user_id]["updated_at"] = datetime.now(TZ)
    elif text:
        await send_message(text="⚠️ Сессия поиска истекла! Начните заново: /search")


@dp.message_callback()
async def button_handler(event: MessageCallback):
    prune_expired_user_contexts()

    send_message = pick_message_sender(event)
    try:
        await load_tables()
    except Exception:
        logger.exception("Ошибка загрузки таблиц при нажатии кнопки")
        await send_message(text="⚠️ Ошибка загрузки таблиц")
        return

    button_pressed = str(event.callback.payload).strip()

    if button_pressed == NAV_BACK:
        await enter_search_mode(event)
    elif button_pressed.startswith("page:"):
        _, kind, str_idx, term = button_pressed.split(":", 3)
        await handle_navigation(event, kind, int(str_idx), term)
    elif button_pressed in codes:
        await serve(event, filter_by_code, button_pressed)
    elif button_pressed in names:
        await serve(event, filter_by_name, button_pressed)
    else:
        logger.error("Нераспознанный ключ: %s", button_pressed)


async def main():
    asyncio.create_task(maintenance_loop())
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
