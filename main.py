from python_calamine import CalamineWorkbook, SheetVisibleEnum
from pathlib import Path


def main():
    raw_dir = Path(__file__).resolve().parent / "raw"
    for week in ["vn", "nn"]:
        week_dir = raw_dir / week
        for wb in ["ff", "fmf", "pip"]:
            book_path = week_dir / (wb + ".xlsx")
            book = CalamineWorkbook.from_path(book_path)
            sheet_names = [
                sheet.name
                for sheet in book.sheets_metadata
                if sheet.visible == SheetVisibleEnum.Visible
            ]
            print(f"{week.upper() + '-' + wb.upper():>6}:", *sheet_names)
            sheets = [book.get_sheet_by_name(name) for name in sheet_names]
            # table[
            #   date, year, code, workweek
            # ]
            # workweek[
            #   day1..day6
            # ]
            # day[
            #   class1..class4
            # ]
            # class[
            #   reader, subj, form, room
            # ]


if __name__ == "__main__":
    main()
