from app.csv_import import import_feedings_from_csv
from app.database import create_db_and_tables, engine
from sqlmodel import Session


def main() -> None:
    create_db_and_tables()

    with Session(engine) as session:
        with open("feedings.csv", newline="") as f:
            result = import_feedings_from_csv(session, f, skip_existing=True)

        if result["skipped"]:
            print("Feedings already exist in the database. Skipping import.")
        else:
            print(f"Import complete. {result['imported']} feedings imported.")


if __name__ == "__main__":
    main()
