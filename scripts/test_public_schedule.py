#!/usr/bin/env python3
"""公開スケジュールの日付範囲と表示ラベル。DBは使わない。"""
from __future__ import annotations

import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app as appmod
from flask import render_template

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


def main():
    today = date(2026, 10, 3)
    start, end = appmod.public_schedule_span(appmod.PUBLIC_SCHEDULE_DAYS, today=today)
    report(start == date(2026, 10, 3) and end == date(2026, 10, 16), "今日を含む14日は10/3〜10/16", f"{start} {end}")
    report(appmod.PUBLIC_SCHEDULE_DAYS == 14, "公開日数は14")

    captured = {}

    def fake_fetch(name, start_date, end_date):
        captured["name"] = name
        captured["start"] = start_date
        captured["end"] = end_date
        return {
            "2026-10-05": {"work_mode": "clinic", "area": "tokyo", "is_off": False, "start_time": "12:00", "end_time": "19:00"},
            "2026-10-06": {"work_mode": "clinic", "area": "fukuoka", "is_off": False, "start_time": "10:00", "end_time": "19:00"},
            "2026-10-07": {"work_mode": "field", "area": None, "is_off": False, "start_time": "10:00", "end_time": "19:00"},
            "2026-10-08": {"work_mode": "off", "area": None, "is_off": True, "start_time": "10:00", "end_time": "19:00"},
        }

    appmod.fetch_staff_shifts_in_range = fake_fetch
    entries = appmod.build_public_schedule_entries(start, end, today=today)
    dates = [e["date"] for e in entries]
    report(len(entries) == 14 and dates[0] == "2026-10-03" and dates[-1] == "2026-10-16", "14件で10/3開始・10/16終了", str(dates))
    report("2026-10-02" not in dates and "2026-10-17" not in dates, "10/2と10/17は含まれない")
    report(captured["start"] == date(2026, 10, 3) and captured["end"] == date(2026, 10, 16), "取得範囲は指定期間だけ", f"{captured}")
    report(captured["name"] == appmod.PUBLIC_SCHEDULE_STAFF_NAME, "公開スタッフ名を使う")

    by = {e["date"]: e for e in entries}
    report(by["2026-10-05"]["place"] == "東京（代々木上原）" and by["2026-10-05"]["detail_place"] == "東京（代々木上原）", "東京ラベル")
    report(by["2026-10-06"]["place"] == "福岡（薬院）" and by["2026-10-06"]["detail_place"] == "福岡（薬院）", "福岡ラベル")
    report(by["2026-10-07"]["place"] == "休" and by["2026-10-07"]["detail_place"] == "トレーナー帯同" and by["2026-10-07"]["status"] == "field", "帯同はトップが休、専用ページがトレーナー帯同")
    report(by["2026-10-08"]["place"] == "休" and by["2026-10-08"]["detail_place"] == "休業" and by["2026-10-08"]["status"] == "off", "休業はトップが休、専用ページが休業")
    report(by["2026-10-03"]["place"] == "—" and by["2026-10-03"]["detail_place"] == "—" and by["2026-10-03"]["status"] == "unset", "未設定は—")
    report(appmod.public_place_label_for_mode("field") == "休" and appmod.public_place_label_for_mode("off") == "休", "既存のトップ用ラベルは帯同も休")

    clamped = appmod.build_public_schedule_entries(date(2026, 10, 1), date(2026, 10, 16), today=today)
    report(clamped and clamped[0]["date"] == "2026-10-03" and captured["start"] == date(2026, 10, 3), "開始日が過去でも今日から")
    empty = appmod.build_public_schedule_entries(date(2026, 9, 1), date(2026, 10, 2), today=today)
    report(empty == [], "期間が今日より前だけなら空")

    with appmod.app.test_request_context("/schedule"):
        html = render_template(
            "schedule.html",
            schedule=entries,
            today="2026-10-03",
            range_start=start,
            range_end=end,
        )
    report("10月3日" in html and "10月16日" in html and "10月17日" not in html and "10月2日" not in html, "ページは10/3〜10/16だけ")
    report("トレーナー帯同" in html and "休業" in html and "東京（代々木上原）" in html and "福岡（薬院）" in html, "専用ページの区分表示")
    report(html.count("public-schedule-day") == 14, "日付行は14")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
