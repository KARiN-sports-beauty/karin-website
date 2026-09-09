"""chatbot_usage_logs の DDL を適用する。会話・予約データは変更しない。

  python scripts/apply_chatbot_usage_logs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)


def main() -> int:
    sql_path = ROOT / "add_chatbot_usage_logs.sql"
    sql = sql_path.read_text(encoding="utf-8")
    from app import resolve_booking_postgres_url
    import psycopg2

    url, err = resolve_booking_postgres_url()
    if err or not url:
        print("postgres url:", err or "missing")
        return 1
    conn = psycopg2.connect(url, connect_timeout=15, application_name="karin-usage-ddl")
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='chatbot_usage_logs' "
                "ORDER BY ordinal_position"
            )
            cols = [r[0] for r in cur.fetchall()]
            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='chatbot_usage_logs' ORDER BY indexname"
            )
            idxs = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    print("chatbot_usage_logs columns:", cols)
    print("indexes:", idxs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
