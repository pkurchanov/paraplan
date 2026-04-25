from python_calamine import CalamineWorkbook, SheetVisibleEnum
from pathlib import Path

# TODO:
# Parse the XML
# Start talking to Max about it


def main():
    raw_dir = Path(__file__).resolve().parent / "raw"
    week_dir = raw_dir / input("vn или nn? ").lower().strip()
    book_path = week_dir / (input("ff, fmf или pip? ").lower().strip() + ".xlsx")
    book = CalamineWorkbook.from_path(book_path)
    sheet_names = [
        sheet.name
        for sheet in book.sheets_metadata
        if sheet.visible == SheetVisibleEnum.Visible
    ]
    print(*sheet_names)


if __name__ == "__main__":
    main()
