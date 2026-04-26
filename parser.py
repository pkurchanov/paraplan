from python_calamine import CalamineWorkbook, SheetVisibleEnum
from pathlib import Path

# На подумать: кэширование


def wash(string):
    """Помыть строку перед использованием"""
    return str(string).lower().strip()


def kabinyetify(x):
    """Избежать кабинетов в духе 302.0"""
    return wash(int(x)) if type(x) is float else wash(x)


def parse():
    # Каталог исходников
    try:
        raw_dir = Path(__file__).resolve().parent / "raw"
    except NameError:
        raw_dir = Path.cwd() / "raw"
    # Сформированные недельные расписания
    time_tables = []
    for week_tag in raw_dir.iterdir():
        week_dir = raw_dir / week_tag
        for book_file in week_dir.iterdir():
            book = CalamineWorkbook.from_path(book_file)
            sheet_names = [
                sheetmd.name
                for sheetmd in book.sheets_metadata
                if sheetmd.visible == SheetVisibleEnum.Visible
            ]
            sheets = [
                book.get_sheet_by_name(name).to_python(skip_empty_area=False)
                for name in sheet_names
            ]
            for sheet in sheets:
                # Начало недели
                date = wash(sheet[3][3])[:10]
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
                            workday.append((instructor_maybe, "", "", ""))
                            break
                        if instructor_maybe == "выходной день":
                            workday.append((instructor_maybe.upper(), "", "", ""))
                            break
                        # Название предмета (включая пометы в скобках)
                        subject: str = sheet[inst_y - 1][inst_x]  # ty:ignore[invalid-assignment]
                        # Форма проведения занятия
                        form = wash(sheet[inst_y + 1][inst_x])
                        # Кабинет
                        classroom = ""
                        if form == "асинхронно":
                            corner_num = kabinyetify(sheet[inst_y + 1][inst_x + 2])
                            if corner_num != "":
                                classroom = corner_num
                        else:
                            classroom = kabinyetify(sheet[inst_y][inst_x + 2])
                        workday.append(
                            (instructor_maybe.title(), subject, form, classroom)
                        )
                    workweek.append(workday)
                time_tables.append((date, year, code.upper(), workweek))
    return time_tables


if __name__ == "__main__":
    parse()
