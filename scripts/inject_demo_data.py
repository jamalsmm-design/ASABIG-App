# scripts/inject_demo_data.py
# ----------------------------------
# ASABIG – Demo Data Injector
# Populates SQLite DB from existing CSV files
# ----------------------------------

import sqlite3
import pandas as pd
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "asabig.db"

DATA_FILES = {
    "athletes": "athletes.csv",
    "athlete_tests": "athlete_tests.csv",
    "generic_talent_data": "generic_talent_data.csv",
    "field_tests": "field_tests.csv",
    "medical_data": "medical_data.csv",
    "sport_specific_kpis": "sport_specific_kpis.csv",
}

def inject():
    if not DB_PATH.exists():
        raise FileNotFoundError("asabig.db not found")

    conn = sqlite3.connect(DB_PATH)

    for table, file in DATA_FILES.items():
        file_path = BASE_DIR / file
        if not file_path.exists():
            print(f"⚠️ Missing file: {file}")
            continue

        df = pd.read_csv(file_path)
        df["injected_at"] = datetime.utcnow().isoformat()
        df.to_sql(table, conn, if_exists="replace", index=False)
        print(f"✅ Injected: {table} ({len(df)} rows)")

    conn.close()
    print("🎯 Demo data injection completed")

if __name__ == "__main__":
    inject()

