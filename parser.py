import logging
from datetime import date, datetime
from pathlib import Path
from typing import TypeAlias

from python_calamine import CalamineWorkbook, SheetVisibleEnum, ZipError

# Между днями по 12 строк, между занятиями по 2
DAY_OFFSET = 13
CLASS_OFFSET = 3
# Координаты первого (потенциального) преподавателя на листе
INST_Y_BASELINE = 9
INST_X_BASELINE = 2

Timeslot: TypeAlias = tuple[str, str, str, str, str]
Workday: TypeAlias = list[Timeslot]
Workweek: TypeAlias = list[Workday]
Table: TypeAlias = tuple[date, str, Workweek]

# Потенциальные улучшения:
# - Явно хранить время


def normalize(x) -> str:
    """Чистит текстовые данные перед использованием"""
    if type(x) is float:
        x = int(x)
    return str(x).lower().strip()


def parse_all(src_dir: Path) -> list[Table]:
    """Принимает путь к директории с таблицами, упаковывает в общий вложенный массив данные всех листов"""
    time_tables: list[Table] = []
    for file in src_dir.iterdir():
        # Отбираются экселевские файлы, а из них нескрытые листы
        if file.suffix[:4] != ".xls":
            continue
        book = CalamineWorkbook.from_path(file)
        sheet_names = [
            sheetmd.name
            for sheetmd in book.sheets_metadata
            if sheetmd.visible == SheetVisibleEnum.Visible
        ]
        sheets = [book.get_sheet_by_name(name).to_python() for name in sheet_names]

        for sheet in sheets:
            # Начало недели
            date = datetime.strptime(normalize(sheet[3][3])[:10], "%d.%m.%Y").date()

            # Код группы
            code = normalize(sheet[6][2])

            # Сама рабочая неделя
            workweek: Workweek = []

            for i in range(6):
                # Полный рабочий день
                workday: Workday = []

                for j in range(4):
                    inst_y = INST_Y_BASELINE + i * DAY_OFFSET + j * CLASS_OFFSET
                    inst_x = INST_X_BASELINE

                    # Имя преподавателя либо один из двух особых случаев
                    instr_slot: str = normalize(sheet[inst_y][inst_x])
                    if instr_slot == "":
                        workday.append((instr_slot, "", "", "", ""))
                        continue
                    if instr_slot == "выходной день":
                        workday = [(instr_slot.upper(), "", "", "", "")]
                        break

                    # Название предмета, включая пометы в скобках
                    # нет оснований полагать, что здесь возможно что-то помимо строки
                    subject: str = sheet[inst_y - 1][inst_x]  # ty:ignore[invalid-assignment]

                    # Форма проведения занятия
                    form: str = normalize(sheet[inst_y + 1][inst_x])

                    # Кабинет
                    classroom: str
                    if form == "асинхронно":
                        corner_num = sheet[inst_y + 1][inst_x + 2]
                        if corner_num:
                            classroom = normalize(corner_num)
                    else:
                        classroom = normalize(sheet[inst_y][inst_x + 2])

                    # Ссылка, если есть
                    link: str = ""
                    try:
                        link_slot = sheet[inst_y - 1][inst_x + 3]
                        # здесь тоже было бы странным что-то кроме строки
                        if link_slot:
                            link: str = link_slot  # ty:ignore[invalid-assignment]
                    except IndexError:
                        pass

                    workday.append((instr_slot.title(), subject, form, classroom, link))
                workweek.append(workday)
            time_tables.append((date, code.upper(), workweek))
    return time_tables


def main() -> list[Table]:
    try:
        src_dir = Path(__file__).resolve().parent / "src"
    except NameError:
        src_dir = Path.cwd() / "src"
    try:
        return parse_all(src_dir)
    except Exception as e:
        if type(e) is ZipError:
            e.add_note(
                "Все таблицы должны быть сохранены и закрыты перед началом работы"
            )
        logging.log(logging.ERROR, e)
        raise


if __name__ == "__main__":
    main()
