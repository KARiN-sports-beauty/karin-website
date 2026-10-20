#!/usr/bin/env python3
"""GBPスケジュール判定と営業時間ペイロード。Googleへは送らない。"""
from __future__ import annotations

import json
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

    google_tokyo = {"periods": []}
    for day in ("SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"):
        google_tokyo["periods"].append({"openDay": day, "openTime": {}, "closeDay": day, "closeTime": {"hours": 2}})
        google_tokyo["periods"].append(
            {"openDay": day, "openTime": {"hours": 12}, "closeDay": day, "closeTime": {"hours": 24}}
        )
    report(sync.regular_hours_match(tokyo_hours, google_tokyo), "東京の送信7件とGoogleの14件は同じ営業時間")
    different_close = {"periods": [dict(item) for item in google_tokyo["periods"]]}
    different_close["periods"][0] = {
        "openDay": "SUNDAY",
        "openTime": {},
        "closeDay": "SUNDAY",
        "closeTime": {"hours": 3},
    }
    report(not sync.regular_hours_match(tokyo_hours, different_close), "終了時刻が違う通常営業時間は不一致")
    different_open = {"periods": [dict(item) for item in tokyo_hours["periods"]]}
    different_open["periods"][0] = {
        "openDay": "MONDAY",
        "openTime": {"hours": 11, "minutes": 0},
        "closeDay": "TUESDAY",
        "closeTime": {"hours": 2, "minutes": 0},
    }
    report(not sync.regular_hours_match(tokyo_hours, different_open), "開始時刻が違う通常営業時間は不一致")
    fukuoka_google = {
        "periods": [
            {"openDay": item["openDay"], "openTime": {"hours": 10}, "closeDay": item["closeDay"], "closeTime": {"hours": 19}}
            for item in fukuoka_hours["periods"]
        ]
    }
    report(sync.regular_hours_match(fukuoka_hours, fukuoka_google), "minutes省略の福岡通常時間は一致")

    special_sent = {
        "specialHourPeriods": [
            {"startDate": {"year": 2026, "month": 10, "day": 29}, "closed": True},
            {"startDate": {"year": 2026, "month": 10, "day": 30}, "closed": True},
        ]
    }
    special_got = {
        "specialHourPeriods": [
            {
                "startDate": {"year": 2026, "month": 10, "day": 29},
                "endDate": {"year": 2026, "month": 10, "day": 29},
                "closed": True,
            },
            {
                "startDate": {"year": 2026, "month": 10, "day": 30},
                "endDate": {"year": 2026, "month": 10, "day": 30},
                "closed": True,
            },
        ]
    }
    report(
        sync.window_specials_match(special_sent, special_got, date(2026, 10, 19), date(2026, 10, 31)),
        "10/29・10/30の終日休業は引き続き一致する",
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

    preview_days = sync.describe_days(
        [
            fact("2026-10-20", "clinic", "tokyo"),
            fact("2026-10-21", "clinic", "fukuoka"),
            fact("2026-10-22", "field"),
        ]
    )
    hours_span = (date(2026, 10, 19), date(2026, 10, 31))
    tokyo_closed = sync.closed_dates_for(preview_days, "tokyo", hours_span[0], hours_span[1])
    fukuoka_closed = sync.closed_dates_for(preview_days, "fukuoka", hours_span[0], hours_span[1])
    report(
        date(2026, 10, 20) not in tokyo_closed and date(2026, 10, 20) in fukuoka_closed,
        "東京のみの日は東京の営業時間対象で、福岡は休業",
    )
    report(
        date(2026, 10, 21) not in fukuoka_closed and date(2026, 10, 21) in tokyo_closed,
        "福岡のみの日は福岡の営業時間対象で、東京は休業",
    )
    report(
        date(2026, 10, 22) in tokyo_closed and date(2026, 10, 22) in fukuoka_closed,
        "トレーナー帯同日は両拠点とも通常営業の対象外",
    )

    applied_payload = json.dumps(
        {
            "regularHours": sync.regular_hours_for("tokyo"),
            "specialHours": {
                "specialHourPeriods": [
                    {"startDate": {"year": 2026, "month": 10, "day": 21}, "closed": True},
                    {"startDate": {"year": 2026, "month": 10, "day": 22}, "closed": True},
                ]
            },
            "window_start": "2026-10-19",
            "window_end": "2026-10-31",
        },
        ensure_ascii=False,
    )
    applied = {"status": "applied", "payload": applied_payload}
    report(
        sync.hours_content_unchanged(applied, "tokyo", tokyo_closed, hours_span[0], hours_span[1]),
        "appliedで同じ休業日なら再送不要",
    )
    report(
        sync.hours_screen_action(applied, "tokyo", tokyo_closed, hours_span) is None,
        "appliedで同じ内容なら更新ボタンを出さない",
    )

    changed_days = sync.describe_days(
        [
            fact("2026-10-20", "clinic", "tokyo"),
            fact("2026-10-21", "clinic", "tokyo"),
            fact("2026-10-22", "field"),
        ]
    )
    changed_closed = sync.closed_dates_for(changed_days, "tokyo", hours_span[0], hours_span[1])
    report(
        not sync.hours_content_unchanged(applied, "tokyo", changed_closed, hours_span[0], hours_span[1]),
        "予定変更後は同じ内容ではない",
    )
    report(
        sync.hours_screen_action(applied, "tokyo", changed_closed, hours_span) == "apply",
        "予定変更後は必要な営業時間更新ができる",
    )
    report(
        sync.hours_screen_action({"status": "unknown", "payload": applied_payload}, "tokyo", tokyo_closed, hours_span)
        == "check",
        "unknownは確認のみ",
    )
    report(sync.hours_screen_action(None, "tokyo", tokyo_closed, hours_span) == "apply", "未更新なら更新できる")

    http_calls = []

    def refuse_http(*args, **kwargs):
        http_calls.append((args, kwargs))
        raise AssertionError("Googleへ送ってはいけない")

    same_result = sync.perform_hours_apply(
        None,
        period_key="2026-10-h2",
        profile="tokyo",
        config={"locations": {"tokyo": "locations/tokyo1", "fukuoka": "locations/fukuoka1"}},
        token_exchange=refuse_http,
        hours_http=refuse_http,
        closed_dates=tokyo_closed,
        window_start=hours_span[0],
        window_end=hours_span[1],
        now="2026-10-20T00:00:00+09:00",
        existing=applied,
    )
    report(same_result["ok"] is False and same_result["status"] == "applied", "同じ内容の再送信はGoogle前に止める")
    report(http_calls == [], "同じ内容の再送信ではtokenも営業時間APIも呼ばない")

    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    report("def build_gbp_schedule_entries" in src, "予定組み立て関数は残っている")
    report("/admin/gbp/schedule" in src and "perform_schedule_gbp_send" in src, "管理画面から既存の送信処理を使う")
    report("hours_content_unchanged" in src and "hours_screen_action" in src, "管理画面は同じ内容の再送信を止める")
    report("publish_external_post" not in open(os.path.join(ROOT, "gbp_schedule_sync.py"), encoding="utf-8").read(), "スケジュール投稿は未接続口を使わない")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
