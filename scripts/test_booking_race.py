#!/usr/bin/env python3
"""Web予約の二重予約防止テスト。

既定では DB へ予約を書き込まない。
本番相当の同時 INSERT テストは TEST_BOOK_LIVE=1 と DATABASE_URL が必要。

  python scripts/test_booking_race.py
  TEST_BOOK_LIVE=1 python scripts/test_booking_race.py
"""
from __future__ import annotations

import concurrent.futures
import os
import sys
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

JST = timezone(timedelta(hours=9))
FAILED = 0
PASSED = 0


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


def sample_payload(**overrides):
    now = datetime.now(JST)
    day = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    payload = {
        "area": "tokyo",
        "place_type": "in_house",
        "date": day,
        "time": "14:00",
        "staff_name": "テストスタッフ",
        "last_name": "安全",
        "first_name": "確認",
        "phone": "09000000001",
        "email": "safety@example.com",
        "duration_minutes": 60,
        "course_type": "total_conditioning",
    }
    payload.update(overrides)
    return payload


def test_url_and_lock_helpers():
    from app import (
        booking_lock_dates,
        booking_lock_keys,
        resolve_booking_postgres_url,
        web_booking_lock_config_error,
    )

    old = os.environ.get("DATABASE_URL")
    old2 = os.environ.get("SUPABASE_DB_URL")
    try:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("SUPABASE_DB_URL", None)
        url, err = resolve_booking_postgres_url()
        report(url is None and err, "未設定URLは拒否")

        os.environ["DATABASE_URL"] = "postgresql://u:p@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
        url, err = resolve_booking_postgres_url()
        report(url is None and err and "6543" in err, "Transaction pooler (6543) を拒否")

        os.environ.pop("DATABASE_URL", None)
        os.environ["SUPABASE_DB_URL"] = "postgresql://u:p@host:5432/postgres?pgbouncer=true"
        url, err = resolve_booking_postgres_url()
        report(url is None and err and "pgbouncer" in err, "pgbouncer=true を拒否")

        os.environ["SUPABASE_DB_URL"] = "postgresql://u:p@db.xxx.supabase.co:5432/postgres"
        os.environ["DATABASE_URL"] = "postgresql://u:p@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
        url, err = resolve_booking_postgres_url()
        report(err is None and url and "sslmode=require" in url and "6543" not in url, "SUPABASE_DB_URL を DATABASE_URL より優先")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        if old2 is None:
            os.environ.pop("SUPABASE_DB_URL", None)
        else:
            os.environ["SUPABASE_DB_URL"] = old2

    start = datetime(2026, 8, 29, 14, 0, tzinfo=JST)
    end = start + timedelta(minutes=60)
    dates = booking_lock_dates(start, end)
    keys = booking_lock_keys(["山田", "青木"], dates, "in_house")
    bed = [k for k in keys if k.startswith("karin.web_book.bed:")]
    staff = [k for k in keys if k.startswith("karin.web_book.staff:")]
    report(bed and keys[: len(bed)] == bed, "院内ロックは bed を先に取得")
    report(staff == sorted(staff), "staff ロックは名前・日付順")
    visit_keys = booking_lock_keys(["山田"], dates, "visit")
    report(all(not k.startswith("karin.web_book.bed:") for k in visit_keys), "出張は bed ロックを取らない")
    _ = web_booking_lock_config_error()


def test_availability_rules():
    from app import is_booking_slot_available

    now = datetime.now(JST)
    start = (now + timedelta(hours=13)).replace(second=0, microsecond=0)
    # シフトは開始〜終了を十分広く（同日の hour 計算に収まる範囲）
    if start.hour >= 22:
        start = start.replace(hour=14, minute=0)
        start = start + timedelta(days=1)
    shift_s, shift_e = 0, 26 * 60

    too_soon = now + timedelta(hours=11)
    report(
        not is_booking_slot_available("A", too_soon, 60, shift_s, shift_e, [], now, "visit", []),
        "12時間以内は予約不可",
    )

    existing = {
        "id": "e1",
        "staff_name": "A",
        "reserved_at": start.isoformat(),
        "duration_minutes": 60,
        "place_type": "visit",
        "status": "reserved",
    }
    report(
        not is_booking_slot_available("A", start, 60, shift_s, shift_e, [existing], now, "visit", []),
        "同一スタッフ同一開始は衝突",
    )
    gap_ok = start + timedelta(minutes=120)
    report(
        is_booking_slot_available("A", gap_ok, 60, shift_s, shift_e, [existing], now, "visit", []),
        "出張終了後60分空けば予約可",
    )
    gap_ng = start + timedelta(minutes=119)
    report(
        not is_booking_slot_available("A", gap_ng, 60, shift_s, shift_e, [existing], now, "visit", []),
        "出張終了後59分では予約不可",
    )

    in_house = dict(existing, place_type="in_house")
    ih_ok = start + timedelta(minutes=90)
    report(
        is_booking_slot_available("A", ih_ok, 60, shift_s, shift_e, [in_house], now, "in_house", [in_house]),
        "院内→院内は終了後30分で予約可",
    )
    ih_ng = start + timedelta(minutes=89)
    report(
        not is_booking_slot_available("A", ih_ng, 60, shift_s, shift_e, [in_house], now, "in_house", [in_house]),
        "院内→院内は終了後29分では予約不可",
    )

    other_staff_bed = dict(in_house, staff_name="B")
    report(
        not is_booking_slot_available("A", start, 60, shift_s, shift_e, [], now, "in_house", [other_staff_bed]),
        "院内1床は別スタッフでも衝突",
    )
    report(
        is_booking_slot_available("A", start, 60, shift_s, shift_e, [other_staff_bed], now, "visit", [other_staff_bed]),
        "出張は別スタッフの院内枠と同時間でも可（1床対象外）",
    )

    existing90 = dict(existing, duration_minutes=90, place_type="visit")
    after90 = start + timedelta(minutes=150)
    report(
        is_booking_slot_available("A", after90, 60, shift_s, shift_e, [existing90], now, "visit", []),
        "90分施術の終了+60分後は予約可",
    )
    report(
        not is_booking_slot_available("A", start + timedelta(minutes=149), 60, shift_s, shift_e, [existing90], now, "visit", []),
        "90分施術の終了+59分は予約不可",
    )
    existing120 = dict(existing, duration_minutes=120, place_type="visit")
    report(
        is_booking_slot_available("A", start + timedelta(minutes=180), 60, shift_s, shift_e, [existing120], now, "visit", []),
        "120分施術の終了+60分後は予約可",
    )
    report(
        not is_booking_slot_available("A", start, 120, shift_s, shift_e, [existing], now, "visit", []),
        "既存60分枠に重なる120分は予約不可",
    )


def test_http_fail_closed_and_lead_time():
    from app import app, BOOKING_LEAD_TIME_MESSAGE, BOOKING_LOCK_UNAVAILABLE_USER_MESSAGE

    client = app.test_client()
    soon = datetime.now(JST) + timedelta(hours=2)
    res = client.post("/api/book", json=sample_payload(
        date=soon.strftime("%Y-%m-%d"),
        time=soon.strftime("%H:%M"),
        place_type="visit",
        place_name="渋谷",
    ))
    body = res.get_json(silent=True) or {}
    report(
        res.status_code == 409 and BOOKING_LEAD_TIME_MESSAGE in (body.get("message") or ""),
        "12時間以内のHTTP予約は409",
        f"got {res.status_code} {body}",
    )

    old = os.environ.get("DATABASE_URL")
    old2 = os.environ.get("SUPABASE_DB_URL")
    try:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("SUPABASE_DB_URL", None)
        res = client.post("/api/book", json=sample_payload(place_type="visit", place_name="渋谷"))
        body = res.get_json(silent=True) or {}
        report(
            res.status_code == 503
            and body.get("success") is False
            and body.get("message") == BOOKING_LOCK_UNAVAILABLE_USER_MESSAGE,
            "DATABASE_URL未設定では確定せず503",
            f"got {res.status_code} {body}",
        )
        report(body.get("booking_id") in (None, ""), "未設定時に booking_id を返さない")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        if old2 is None:
            os.environ.pop("SUPABASE_DB_URL", None)
        else:
            os.environ["SUPABASE_DB_URL"] = old2


def test_advisory_lock_on_live_db():
    from app import connect_postgres_for_booking, resolve_booking_postgres_url, web_booking_lock_config_error

    err = web_booking_lock_config_error()
    if err:
        print(f"SKIP: advisory lock 接続テスト（{err}）")
        return

    url, uerr = resolve_booking_postgres_url()
    if uerr or not url:
        print("SKIP: advisory lock 接続テスト（URL不正）")
        return

    started = []
    finished = []
    lock_key = f"karin.web_book.test:{uuid.uuid4().hex}"

    def worker(i):
        conn = connect_postgres_for_booking()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
                started.append((i, time.monotonic()))
                time.sleep(0.35)
            conn.commit()
            finished.append((i, time.monotonic()))
        finally:
            conn.close()

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(worker, i) for i in range(2)]
            for f in futs:
                f.result(timeout=30)
    except Exception as e:
        print(f"SKIP: advisory lock 接続テスト（接続失敗: {e}）")
        return

    first_done = min(t for _, t in finished)
    second_start = max(t for _, t in started)
    report(second_start >= first_done - 0.02, "pg_advisory_xact_lock が接続上で直列化する")


def test_live_double_book():
    if os.getenv("TEST_BOOK_LIVE", "").strip() not in ("1", "true", "yes"):
        print("SKIP: 同時予約INSERTテスト（TEST_BOOK_LIVE=1 で実行）")
        return

    from app import (
        app,
        fetch_booking_day_reservations,
        fetch_booking_day_shifts,
        load_approved_staff_entries_for_booking,
        supabase_admin,
        web_booking_lock_config_error,
        working_staff_for_booking_day,
    )

    err = web_booking_lock_config_error()
    if err:
        print(f"SKIP: 同時予約INSERTテスト（{err}）")
        return

    now = datetime.now(JST)
    day_str = os.getenv("TEST_BOOK_DATE") or (now + timedelta(days=2)).strftime("%Y-%m-%d")
    time_hm = os.getenv("TEST_BOOK_TIME") or "14:00"
    area = os.getenv("TEST_BOOK_AREA") or "tokyo"
    place_type = os.getenv("TEST_BOOK_PLACE") or "in_house"
    staff = os.getenv("TEST_BOOK_STAFF")
    if not staff:
        entries = load_approved_staff_entries_for_booking()
        shifts = fetch_booking_day_shifts(day_str, [s["name"] for s in entries])
        day_res = fetch_booking_day_reservations(day_str)
        working = working_staff_for_booking_day(area, day_str, entries, shifts, day_res)
        if not working:
            print(f"SKIP: {area} {day_str} に出勤スタッフがいません")
            return
        staff = working[0]["name"]

    suffix = uuid.uuid4().hex[:8]

    def attempt(i):
        payload = sample_payload(
            area=area,
            place_type=place_type,
            place_name="テスト区1-1-1" if place_type == "visit" else None,
            date=day_str,
            time=time_hm,
            staff_name=staff,
            last_name="同時",
            first_name=f"試験{suffix}{i}",
            phone=f"090{2000000 + i:07d}",
            email=f"race-{suffix}-{i}@example.com",
            duration_minutes=60,
        )
        if not payload.get("place_name"):
            payload.pop("place_name", None)
        client = app.test_client()
        resp = client.post("/api/book", json=payload)
        return resp.status_code, resp.get_json(silent=True) or {}

    print(f"同時予約INSERT: staff={staff!r} {day_str} {time_hm} {place_type}")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        results = [f.result() for f in [ex.submit(attempt, i) for i in range(2)]]

    for idx, (code, body) in enumerate(results):
        print(f"  request {idx + 1}: HTTP {code} -> {body}")

    successes = [r for r in results if r[0] == 200 and r[1].get("success")]
    conflicts = [r for r in results if r[0] == 409]
    ids = [r[1].get("booking_id") for r in successes if r[1].get("booking_id")]
    report(len(successes) == 1, "同時2件のうち成功は1件", f"successes={len(successes)}")
    report(len(conflicts) == 1, "同時2件のうち競合は1件", f"conflicts={len(conflicts)} other={[r[0] for r in results]}")
    report(len(set(ids)) == len(ids) and len(ids) == 1, "reservations は1件のみ")

    for bid in ids:
        try:
            supabase_admin.table("reservations").delete().eq("id", bid).execute()
            print(f"  cleanup: deleted {bid}")
        except Exception as e:
            print(f"  cleanup warning: {e}")


def main():
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))

    print("=== Web予約 二重予約防止テスト ===")
    try:
        test_url_and_lock_helpers()
        test_availability_rules()
        test_http_fail_closed_and_lead_time()
        test_advisory_lock_on_live_db()
        test_live_double_book()
    except Exception:
        traceback.print_exc()
        report(False, "テスト実行中の例外")

    print(f"--- {PASSED} passed, {FAILED} failed ---")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
