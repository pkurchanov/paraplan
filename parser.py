from python_calamine import CalamineWorkbook, SheetVisibleEnum, ZipError
from datetime import datetime
from pathlib import Path


def wash(string):
    """Моет строку перед использованием"""
    return str(string).lower().strip()


def kabinyetify(x):
    """Устраняет кабинеты в духе 302.0"""
    return wash(int(x)) if type(x) is float else wash(x)


def parse_all(raw_dir):
    """Принимает путь к директории с таблицами, парсит и упаковывает в общий массив все листы"""
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
            date = datetime.strptime(wash(sheet[3][3])[:10], "%d.%m.%Y").date()
            # Курс
            year = wash(sheet[4][2])
            # Код группы
            code = wash(sheet[6][2])
            # Сама рабочая неделя
            workweek = []
            for i in range(6):
                # Полный рабочий день
                workday = []
                for j in range(4):
                    # Между днями по 12 строк, между занятиями по 2
                    inst_y = 9 + i * 13 + j * 3
                    inst_x = 2
                    instructor_maybe = wash(sheet[inst_y][inst_x])
                    if instructor_maybe == "":
                        workday.append((instructor_maybe,))
                        continue
                    if instructor_maybe == "выходной день":
                        workday = [(instructor_maybe.upper(),)]
                        break
                    # Название предмета (включая пометы в скобках)
                    subject: str = sheet[inst_y - 1][inst_x]  # ty:ignore[invalid-assignment]
                    # Форма проведения занятия
                    form = wash(sheet[inst_y + 1][inst_x])
                    # Кабинет
                    if form == "асинхронно":
                        corner_num = kabinyetify(sheet[inst_y + 1][inst_x + 2])
                        if corner_num:
                            classroom = corner_num
                    else:
                        classroom = kabinyetify(sheet[inst_y][inst_x + 2])
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


def main() -> list[tuple] | None:
    try:
        raw_dir = Path(__file__).resolve().parent / "raw"
    except NameError:
        raw_dir = Path.cwd() / "raw"
    try:
        return parse_all(raw_dir)
    except ZipError:
        print("ОШИБКА: сохраните и закройте все таблицы перед началом работы!")


if __name__ == "__main__":
    main()
