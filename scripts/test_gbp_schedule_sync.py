#!/usr/bin/env python3
"""GBPスケジュール判定と営業時間ペイロード。Googleへは送らない。"""
from __future__ import annotations

import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gbp_schedule_sync as sync

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


def fact(day, mode, area=None, has_field=False):
    return {"date": day, "mode": mode, "area": area, "has_field": has_field}


def main():
    report(
        sync.hours_status("tokyo", "clinic", "tokyo", False) == ("open", "clinic_only"),
        "東京のみは東京が通常営業",
    )
    report(
        sync.hours_status("fukuoka", "clinic", "tokyo", False) == ("closed", "other_area"),
        "東京のみは福岡が休業",
    )
    report(
        sync.hours_status("fukuoka", "clinic", "fukuoka", False) == ("open", "clinic_only"),
        "福岡のみは福岡が通常営業",
    )
    report(
        sync.hours_status("tokyo", "clinic", "fukuoka", False) == ("closed", "other_area"),
        "福岡のみは東京が休業",
    )
    report(
        sync.hours_status("tokyo", "field", None, False) == ("closed", "field")
        and sync.hours_status("fukuoka", "field", None, False) == ("closed", "field"),
        "帯同日は両方休業",
    )
    report(
        sync.hours_status("tokyo", "clinic", "tokyo", True) == ("closed", "overlap")
        and sync.hours_status("fukuoka", "clinic", "tokyo", True) == ("closed", "overlap"),
        "東京勤務と帯同の重複は両方休業",
    )
    report(
        sync.hours_status("tokyo", "unset", None, False) == ("closed", "unset")
        and sync.hours_status("fukuoka", None, None, False)[0] == "closed",
        "予定なし・欠損は営業にしない",
    )
    report(
        sync.hours_status("tokyo", "off", None, False) == ("closed", "off")
        and sync.hours_status("tokyo", "clinic", None, False) == ("closed", "undetermined"),
        "休業日とエリア不明は営業にしない",
    )

    tokyo_open = sync.post_entry("tokyo", "clinic", "tokyo", False)
    tokyo_mix = sync.post_entry("tokyo", "clinic", "tokyo", True)
    fukuoka_from_tokyo_mix = sync.post_entry("fukuoka", "clinic", "tokyo", True)
    fukuoka_mix = sync.post_entry("fukuoka", "clinic", "fukuoka", True)
    report(tokyo_open["kind"] == "clinic" and tokyo_open["label"] == "東京（代々木上原）", "投稿の東京のみ")
    report(tokyo_mix == {"kind": "field", "label": "トレーナー帯同"}, "重複日の東京投稿は帯同だけ")
    report(fukuoka_from_tokyo_mix == {"kind": "field", "label": "トレーナー帯同"}, "重複日の福岡投稿も帯同だけ")
    report(fukuoka_mix["kind"] == "field" and "福岡" not in fukuoka_mix["label"], "福岡勤務＋帯同も対応日にしない")
    report(sync.post_entry("tokyo", "clinic", "fukuoka", False) is None, "福岡の院内日は東京投稿に載せない")
    report(sync.post_entry("tokyo", "unset", None, False) is None, "未登録日は投稿に時間も休業も作らない")

    tokyo_hours = sync.regular_hours_for("tokyo")
    monday = tokyo_hours["periods"][0]
    sunday = tokyo_hours["periods"][6]
    report(monday["openDay"] == "MONDAY" and monday["openTime"]["hours"] == 12, "東京の通常開始は12:00")
    report(monday["closeDay"] == "TUESDAY" and monday["closeTime"]["hours"] == 2, "東京は翌02:00で閉じる")
    report(sunday["openDay"] == "SUNDAY" and sunday["closeDay"] == "MONDAY", "日曜の日またぎは月曜閉じ")
    fukuoka_hours = sync.regular_hours_for("fukuoka")
    report(
        fukuoka_hours["periods"][0]["openTime"]["hours"] == 10
        and fukuoka_hours["periods"][0]["closeDay"] == "MONDAY"
        and fukuoka_hours["periods"][0]["closeTime"]["hours"] == 19,
        "福岡の通常は同日10:00-19:00",
    )

    today = date(2026, 10, 19)
    window = sync.hours_window(date(2026, 10, 16), date(2026, 10, 31), today)
    report(window == (date(2026, 10, 19), date(2026, 10, 31)), "特別営業時間は今日以降", str(window))
    report(sync.hours_window(date(2026, 10, 1), date(2026, 10, 15), today) is None, "すべて過去なら更新しない")

    existing = [
        {"startDate": {"year": 2026, "month": 10, "day": 18}, "closed": True},
        {"startDate": {"year": 2026, "month": 10, "day": 20}, "closed": True},
        {"startDate": {"year": 2026, "month": 11, "day": 3}, "closed": True},
    ]
    merged = sync.merge_special_hours(
        existing, date(2026, 10, 19), date(2026, 10, 31), [date(2026, 10, 21), date(2026, 10, 20)]
    )
    starts = [sync.payload_date(item.get("startDate")) for item in merged["specialHourPeriods"]]
    report(date(2026, 10, 18) in starts and date(2026, 11, 3) in starts, "窓の外の特別営業時間は残す")
    report(starts.count(date(2026, 10, 20)) == 1 and date(2026, 10, 21) in starts, "窓の中は置き換えて重複させない")
    report(all(item.get("closed") is True for item in merged["specialHourPeriods"] if sync.payload_date(item.get("startDate")) == date(2026, 10, 21)), "休業日は終日休業")

    days = [
        fact("2026-10-20", "clinic", "tokyo"),
        fact("2026-10-21", "clinic", "tokyo", True),
        fact("2026-10-22", "field"),
        fact("2026-10-23", "off"),
        fact("2026-10-24", "unset"),
        fact("2026-10-25", "clinic", "fukuoka"),
    ]
    tokyo_body = sync.build_schedule_body("tokyo", days)
    fukuoka_body = sync.build_schedule_body("fukuoka", days)
    report("10月20日（火） 東京（代々木上原）" in tokyo_body, "東京本文に東京の対応日")
    report("【対応日】" in tokyo_body and "10月21日" not in tokyo_body.split("【対応日】")[1].split("【")[0], "重複日は東京の対応日に載せない")
    report("10月21日（水）" in tokyo_body and "【トレーナー帯同】" in tokyo_body, "重複日は帯同として案内する")
    report("東京（代々木上原）／トレーナー帯同" not in tokyo_body, "投稿文で地域と帯同を併記しない")
    report("10月22日（木）" in tokyo_body and "【トレーナー帯同】" in tokyo_body, "東京本文に帯同日")
    report("10月23日（金）" in tokyo_body and "【休業】" in tokyo_body, "東京本文に休業日")
    report("12:00" not in tokyo_body and "02:00" not in tokyo_body and "19:00" not in tokyo_body, "投稿文に受付時間を書かない")
    report("福岡（薬院）" not in tokyo_body, "東京本文に福岡の院内日を載せない")
    report("10月25日（日） 福岡（薬院）" in fukuoka_body, "福岡本文に福岡の対応日")
    report("10月20日" not in fukuoka_body, "福岡本文に東京のみの日を載せない")
    report("10月21日（水）" in fukuoka_body, "重複日は福岡の帯同欄にも載せる")
    report(sync.SCHEDULE_URL in tokyo_body and sync.BOOK_URL in tokyo_body, "詳細確認先のリンクがある")
    report(sync.SCHEDULE_URL in fukuoka_body and sync.BOOK_URL in fukuoka_body, "福岡本文にも確認先リンクがある")
    report("karin-sb.jp/tokyo" not in fukuoka_body, "福岡本文のリンク先を取り違えない")

    refused = False
    try:
        sync.hours_exchange("POST", "https://example.invalid", access_token="token")
    except sync.GbpHoursRefused:
        refused = True
    report(refused, "営業時間クライアントはPOSTしない")
    report(sync.location_hours_patch_request("locations/abc", {}, {}).get("method") == "PATCH", "営業時間更新はPATCH")
    report("localPosts" not in sync.location_hours_get_request("locations/abc")["url"], "営業時間取得は投稿APIではない")

    config = {"locations": {"tokyo": "locations/tokyo1", "fukuoka": "locations/fukuoka1"}}
    planned = sync.plan_hours_update(
        "fukuoka",
        config,
        {"name": "locations/fukuoka1", "specialHours": {"specialHourPeriods": []}},
        [date(2026, 10, 21)],
        date(2026, 10, 19),
        date(2026, 10, 31),
    )
    report(planned["url"].endswith("locations/fukuoka1?updateMask=regularHours,specialHours"), "福岡のlocationだけを更新する")
    report("tokyo1" not in planned["url"], "東京のlocationを混ぜない")

    mixed = False
    try:
        sync.plan_hours_update(
            "tokyo",
            {"locations": {"tokyo": "locations/same", "fukuoka": "locations/same"}},
            {"name": "locations/same"},
            [],
            date(2026, 10, 19),
            date(2026, 10, 31),
        )
    except sync.GbpHoursRefused:
        mixed = True
    report(mixed, "東京と福岡のlocationが同じなら更新しない")

    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    report("def build_gbp_schedule_entries" in src, "予定組み立て関数は残っている")
    report("/admin/gbp/schedule" in src and "perform_schedule_gbp_send" in src, "管理画面から既存の送信処理を使う")
    report("publish_external_post" not in open(os.path.join(ROOT, "gbp_schedule_sync.py"), encoding="utf-8").read(), "スケジュール投稿は未接続口を使わない")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
