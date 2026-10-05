"""external_posts / external_post_events の DDL を適用する。

  python scripts/apply_external_posts.py
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
    sql_path = ROOT / "add_external_posts.sql"
    sql = sql_path.read_text(encoding="utf-8")
    from app import resolve_booking_postgres_url
    import psycopg2

    url, err = resolve_booking_postgres_url()
    if err or not url:
        print("postgres url:", err or "missing")
        return 1
    conn = psycopg2.connect(url, connect_timeout=15, application_name="karin-external-posts-ddl")
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name IN "
                "('external_posts', 'external_post_events') ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='external_posts' "
                "ORDER BY ordinal_position"
            )
            cols = [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
    print("tables:", tables)
    print("external_posts columns:", cols)
    if tables != ["external_post_events", "external_posts"]:
        print("error: expected both tables")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
