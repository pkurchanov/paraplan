import logging
from python_calamine import CalamineWorkbook, SheetVisibleEnum, ZipError
from datetime import datetime
from pathlib import Path


# Между днями по 12 строк, между занятиями по 2
DAY_OFFSET = 13
CLASS_OFFSET = 3
# Координаты первого (потенциального) преподавателя на листе
INST_Y_BASELINE = 9
INST_X_BASELINE = 2


def normalize(x) -> str:
    """Чистит текстовые данные перед использованием"""
    if type(x) is float:
        x = int(x)
    return str(x).lower().strip()


def parse_all(raw_dir):
    """Принимает путь к директории с таблицами, упаковывает в общий вложенный массив данные всех листов"""
    time_tables = []
    for file in raw_dir.iterdir():
        if file.suffix != ".xlsx":
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
            # Курс
            year = normalize(sheet[4][2])
            # Код группы
            code = normalize(sheet[6][2])
            # Сама рабочая неделя
            workweek = []
            for i in range(6):
                # Полный рабочий день
                workday = []
                for j in range(4):
                    inst_y = INST_Y_BASELINE + i * DAY_OFFSET + j * CLASS_OFFSET
                    inst_x = INST_X_BASELINE
                    instructor_maybe = normalize(sheet[inst_y][inst_x])
                    if instructor_maybe == "":
                        workday.append((instructor_maybe,))
                        continue
                    if instructor_maybe == "выходной день":
                        workday = [(instructor_maybe.upper(),)]
                        break
                    # Название предмета (включая пометы в скобках)
                    subject: str = sheet[inst_y - 1][inst_x]  # ty:ignore[invalid-assignment]
                    # Форма проведения занятия
                    form = normalize(sheet[inst_y + 1][inst_x])
                    # Кабинет
                    if form == "асинхронно":
                        corner_num = normalize(sheet[inst_y + 1][inst_x + 2])
                        if corner_num:
                            classroom = corner_num
                    else:
                        classroom = normalize(sheet[inst_y][inst_x + 2])
                    # Ссылка, если есть
                    link = ""
                    try:
                        linkspot = sheet[inst_y - 1][inst_x + 3]
                        if linkspot:
                            link = linkspot
                    except IndexError:
                        pass
                    workday.append(
                        (instructor_maybe.title(), subject, form, classroom, link)
                    )
                workweek.append(workday)
            time_tables.append((date, year, code.upper(), workweek))
    return time_tables


def main() -> list[tuple] | int:
    try:
        raw_dir = Path(__file__).resolve().parent / "raw"
    except NameError:
        raw_dir = Path.cwd() / "raw"
    try:
        return parse_all(raw_dir)
    except ZipError:
        logging.log(
            logging.ERROR,
            "Сохраните и закройте все таблицы перед началом работы!",
        )
        return 1


if __name__ == "__main__":
    main()
