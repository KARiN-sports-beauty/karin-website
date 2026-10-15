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
    appmod.fetch_staff_field_blocks_in_range = lambda name, start_date, end_date: {}
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

    def entry(mode, area, start_hm, end_hm, fields):
        row = {
            "work_mode": mode,
            "area": area,
            "is_off": mode == "off",
            "start_time": start_hm,
            "end_time": end_hm,
        }
        return appmod.make_public_schedule_entry(date(2026, 10, 5), row, fields)

    tokyo_then_field = entry("clinic", "tokyo", "12:00", "16:00", [(17 * 60, 22 * 60)])
    report(
        tokyo_then_field["place"] == "東京（代々木上原）"
        and tokyo_then_field["detail_place"] == "東京（代々木上原）/トレーナー帯同"
        and tokyo_then_field["badge"] == "東/帯"
        and tokyo_then_field["status"] == "tokyo",
        "昼東京・夕方帯同は東京が前",
        str(tokyo_then_field),
    )
    field_then_tokyo = entry("clinic", "tokyo", "13:00", "19:00", [(10 * 60, 13 * 60)])
    report(
        field_then_tokyo["place"] == "東京（代々木上原）"
        and field_then_tokyo["detail_place"] == "トレーナー帯同/東京（代々木上原）"
        and field_then_tokyo["badge"] == "帯/東",
        "朝帯同・午後東京は帯同が前、トップは東京",
        str(field_then_tokyo),
    )
    fukuoka_then_field = entry("clinic", "fukuoka", "10:00", "15:00", [(16 * 60, 20 * 60)])
    report(
        fukuoka_then_field["place"] == "福岡（薬院）"
        and fukuoka_then_field["detail_place"] == "福岡（薬院）/トレーナー帯同"
        and fukuoka_then_field["badge"] == "福/帯",
        "福岡のあとに帯同",
        str(fukuoka_then_field),
    )
    field_then_fukuoka = entry("clinic", "fukuoka", "14:00", "19:00", [(9 * 60, 12 * 60)])
    report(
        field_then_fukuoka["place"] == "福岡（薬院）"
        and field_then_fukuoka["detail_place"] == "トレーナー帯同/福岡（薬院）"
        and field_then_fukuoka["badge"] == "帯/福",
        "帯同のあとに福岡、トップは福岡",
        str(field_then_fukuoka),
    )
    split_tokyo = entry("clinic", "tokyo", "10:00", "19:00", [(12 * 60, 14 * 60)])
    report(
        split_tokyo["detail_place"] == "東京（代々木上原）/トレーナー帯同/東京（代々木上原）"
        and split_tokyo["badge"] == "東/帯/東"
        and split_tokyo["place"] == "東京（代々木上原）",
        "勤務時間の途中の帯同は前後に東京",
        str(split_tokyo),
    )
    field_day = entry("field", None, "10:00", "19:00", [(17 * 60, 22 * 60)])
    report(
        field_day["place"] == "休" and field_day["detail_place"] == "トレーナー帯同" and field_day["badge"] == "帯",
        "帯同だけの日は組み合わせない",
        str(field_day),
    )
    off_day = entry("off", None, "10:00", "19:00", [(10 * 60, 12 * 60)])
    report(
        off_day["place"] == "休" and off_day["detail_place"] == "休業" and off_day["badge"] == "休",
        "休みの日は帯同予定があっても休業",
        str(off_day),
    )
    clinic_only = entry("clinic", "tokyo", "12:00", "19:00", None)
    report(
        clinic_only["place"] == "東京（代々木上原）" and clinic_only["detail_place"] == "東京（代々木上原）" and clinic_only["badge"] == "東",
        "帯同予定がなければ東京だけ",
        str(clinic_only),
    )

    blocks = appmod.field_blocks_by_day(
        [
            {"place_type": "field", "status": "reserved", "reserved_at": "2026-10-05T08:00:00+09:00", "duration_minutes": 180},
            {"place_type": "field", "status": "canceled", "reserved_at": "2026-10-05T17:00:00+09:00", "duration_minutes": 120},
            {"place_type": "in_house", "status": "reserved", "reserved_at": "2026-10-05T12:00:00+09:00", "duration_minutes": 60},
            {"place_type": "field", "status": "reserved", "reserved_at": "2026-10-06T10:00:00+09:00", "duration_minutes": 60},
        ],
        date(2026, 10, 5),
        date(2026, 10, 6),
    )
    report(blocks.get("2026-10-05") == [(8 * 60, 11 * 60)], "キャンセルと帯同以外は除く", str(blocks))
    report(blocks.get("2026-10-06") == [(10 * 60, 11 * 60)], "翌日の帯同は別の日", str(blocks))

    appmod.fetch_staff_shifts_in_range = lambda name, start_date, end_date: {
        "2026-10-05": {"work_mode": "clinic", "area": "tokyo", "is_off": False, "start_time": "12:00", "end_time": "16:00"},
    }
    appmod.fetch_staff_field_blocks_in_range = lambda name, start_date, end_date: {
        "2026-10-05": [(17 * 60, 22 * 60)],
    }
    status_map, badge_map = appmod.build_calendar_shift_marks(2026, 10)
    report(status_map["2026-10-05"] == "tokyo" and badge_map["2026-10-05"] == "東/帯", "管理カレンダーは東/帯", f"{badge_map.get('2026-10-05')}")
    report(status_map["2026-10-01"] == "unset" and badge_map["2026-10-01"] == "", "未登録日のバッジは空")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
