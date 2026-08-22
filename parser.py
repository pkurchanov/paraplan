import logging
from datetime import date, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from python_calamine import CalamineWorkbook, SheetVisibleEnum, ZipError

# Между днями по 12 строк, между занятиями по 2
DAY_OFFSET = 13
CLASS_OFFSET = 3
# Координаты первого (потенциального) преподавателя на листе
INST_Y_BASELINE = 9
INST_X_BASELINE = 2

# Особые значения и часовой пояс
EMPTY = ""
DAY_OFF = "выходной день"
TZ = ZoneInfo("Asia/Krasnoyarsk")

type FullClass = tuple[str, str, str, str, str, str]
type UnfullClass = Literal["", "выходной день"]
type Timeslot = FullClass | UnfullClass
type Workday = list[Timeslot]
type Workweek = list[Workday]
type Table = tuple[date, str, Workweek]


def normalize(x) -> str:
    """Чистит текстовые данные перед использованием"""
    if type(x) is float:
        x = int(x)
    return str(x).lower().strip()


def get_cell(sheet, y: int, x: int):
    """Достает ячейку без падения на границах листа"""
    try:
        return sheet[y][x]
    except (IndexError, TypeError):
        return None


def parse_week_start(value) -> date:
    """Разбирает дату начала недели из ячейки"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=TZ)
        return value.astimezone(TZ).date()

    if isinstance(value, date):
        return value

    text = normalize(value)[:10]
    return datetime.strptime(text, "%d.%m.%Y").astimezone(TZ).date()


def parse_sheet(sheet) -> Table:
    """Разбирает один лист и возвращает Table"""
    # Начало недели
    week_start = parse_week_start(get_cell(sheet, 3, 3))

    # Код группы
    code = normalize(get_cell(sheet, 6, 2))

    # Сама рабочая неделя
    workweek: Workweek = []

    for i in range(6):
        # Полный рабочий день
        workday: Workday = []

        for j in range(4):
            inst_y = INST_Y_BASELINE + i * DAY_OFFSET + j * CLASS_OFFSET
            inst_x = INST_X_BASELINE

            # Имя преподавателя либо один из двух особых случаев
            instr_slot: str = normalize(get_cell(sheet, inst_y, inst_x))

            if instr_slot == EMPTY:
                workday.append(EMPTY)
                continue

            if instr_slot == DAY_OFF:
                workday = [DAY_OFF]
                break

            # Название предмета, включая пометы в скобках
            subject = str(get_cell(sheet, inst_y - 1, inst_x) or "").strip()

            # Форма проведения занятия
            form = normalize(get_cell(sheet, inst_y + 1, inst_x))

            # Кабинет
            classroom = normalize(get_cell(sheet, inst_y, inst_x + 2))
            if classroom == "эиос":
                corner_num = get_cell(sheet, inst_y + 1, inst_x + 2)
                if corner_num:
                    classroom = normalize(corner_num)

            # Ссылка, если есть
            link = ""
            link_slot = get_cell(sheet, inst_y - 1, inst_x + 3)
            if link_slot:
                link = str(link_slot).strip()

            # Время занятия
            time = str(get_cell(sheet, inst_y, inst_x - 1) or "").strip()

            workday.append((instr_slot.title(), subject, form, classroom, link, time))

        workweek.append(workday)

    return week_start, code.upper(), workweek


def parse_all(src_dir: Path) -> list[Table]:
    """Принимает путь к каталогу таблиц и упаковывает в список Table-ов данные всех листов"""
    time_tables: list[Table] = []

    if not src_dir.is_dir():
        return time_tables

    for file in src_dir.rglob("*"):
        # Отбираются экселевские файлы, а из них нескрытые листы
        if not file.is_file():
            continue

        # Временные файлы Excel
        if file.name.startswith("~$"):
            continue

        if file.suffix.lower()[:4] != ".xls":
            continue

        try:
            book = CalamineWorkbook.from_path(file)
        except Exception:
            logging.exception("Не удалось открыть файл: %s", file)
            continue

        sheet_names = [
            sheetmd.name
            for sheetmd in book.sheets_metadata
            if sheetmd.visible == SheetVisibleEnum.Visible
        ]

        for sheet_name in sheet_names:
            try:
                sheet = book.get_sheet_by_name(sheet_name).to_python()
                time_tables.append(parse_sheet(sheet))
            except Exception:
                logging.exception("Пропускаем лист %s в файле %s", sheet_name, file)
                continue

    return time_tables


def main() -> list[Table]:
    try:
        src_dir = Path(__file__).resolve().parent / "raw"
    except NameError:
        src_dir = Path.cwd() / "src"
    try:
        return parse_all(src_dir)
    except Exception as e:
        if isinstance(e, ZipError):
            e.add_note(
                "Все таблицы должны быть сохранены и закрыты перед началом работы"
            )
        logging.exception("Ошибка загрузки расписания")
        raise


if __name__ == "__main__":
    main()
