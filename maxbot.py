from parser import main as parse
from keys import TEST_TOKEN
import maxapi


def main():
    try:
        tables = parse()
    except Exception as e:
        print(f"Произошла ошибка при обработке таблиц: {e}")


if __name__ == "__main__":
    main()
