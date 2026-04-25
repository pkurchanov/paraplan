from python_calamine import CalamineWorkbook, SheetVisibleEnum
from pathlib import Path


def wash(string):
    """Помыть строку перед использованием"""
    return str(string).lower().strip()


def kabinyetify(x):
    """Избегать кабинетов в духе 302.0"""
    return wash(int(x)) if type(x) is float else wash(x)


def main():
    # Каталог исходников
    raw_dir = Path(__file__).resolve().parent / "raw"
    # Сформированные расписания на неделю
    time_tables = []
    for week_tag in raw_dir.iterdir():
        week_dir = raw_dir / week_tag
        for book_file in week_dir.iterdir():
            book = CalamineWorkbook.from_path(book_file)
            sheet_names = [
                sheet.name
                for sheet in book.sheets_metadata
                if sheet.visible == SheetVisibleEnum.Visible
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
                        ordinate = 9 + i * 13 + j * 3
                        abscissa = 2
                        instructor_maybe = wash(sheet[ordinate][abscissa])
                        if instructor_maybe == "выходной день":
                            workday.append((instructor_maybe.upper(), "", "", ""))
                            break
                        # Название предмета (включая пометы в скобках)
                        subject: str = sheet[ordinate - 1][abscissa]  # ty:ignore[invalid-assignment]
                        # Форма проведения занятия
                        form = wash(sheet[ordinate + 1][abscissa])
                        # Кабинет
                        classroom = ""
                        if form == "асинхронно":
                            corner_num = kabinyetify(sheet[ordinate + 1][abscissa + 2])
                            if corner_num != "":
                                classroom = corner_num
                        else:
                            classroom = kabinyetify(sheet[ordinate][abscissa + 2])
                        workday.append(
                            (instructor_maybe.title(), subject, form, classroom)
                        )
                    workweek.append(workday)
                time_tables.append((date, year, code.upper(), workweek))
    print(*time_tables, sep="\n\n")


if __name__ == "__main__":
    main()
