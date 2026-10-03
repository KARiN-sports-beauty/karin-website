#!/usr/bin/env python3
"""GBP用予定データの振り分け。DBもGoogle APIも使わない。"""
from __future__ import annotations

import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import app as appmod

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


def row(mode, area, start="10:00", end="19:00"):
    return {
        "work_mode": mode,
        "area": area,
        "is_off": mode == "off",
        "start_time": start,
        "end_time": end,
    }


def install_shifts(shifts):
    captured = {}

    def fake_fetch(name, start_date, end_date):
        captured["name"] = name
        captured["start"] = start_date
        captured["end"] = end_date
        return shifts

    appmod.fetch_staff_shifts_in_range = fake_fetch
    return captured


def dates_for(start, end, profile):
    return [item["date"] for item in appmod.build_gbp_schedule_entries(start, end, profile)]


def main():
    start = date(2026, 10, 1)
    end = date(2026, 10, 15)
    shifts = {
        "2026-10-03": row("clinic", "tokyo"),
        "2026-10-04": row("clinic", "fukuoka"),
        "2026-10-05": row("field", None),
        "2026-10-06": row("off", None),
        "2026-10-07": row("unset", None),
        "2026-10-08": row("clinic", None),
        "2026-10-09": row("field", "tokyo"),
        "2026-10-10": row("off", "fukuoka"),
    }
    captured = install_shifts(shifts)

    tokyo = {item["date"]: item for item in appmod.build_gbp_schedule_entries(start, end, "tokyo")}
    fukuoka = {item["date"]: item for item in appmod.build_gbp_schedule_entries(start, end, "fukuoka")}

    report("2026-10-03" in tokyo and "2026-10-03" not in fukuoka, "① clinic+tokyo は東京のみ")
    report(tokyo["2026-10-03"]["label"] == "東京（代々木上原）" and tokyo["2026-10-03"]["area"] == "tokyo", "① 東京ラベル")
    report("2026-10-04" in fukuoka and "2026-10-04" not in tokyo, "② clinic+fukuoka は福岡のみ")
    report(fukuoka["2026-10-04"]["label"] == "福岡（薬院）" and fukuoka["2026-10-04"]["area"] == "fukuoka", "② 福岡ラベル")
    report("2026-10-05" in tokyo and "2026-10-05" in fukuoka, "③ field は両方")
    report(tokyo["2026-10-05"]["label"] == "トレーナー帯同" and tokyo["2026-10-05"]["area"] is None, "③ 帯同ラベルと area")
    report(fukuoka["2026-10-05"]["work_mode"] == "field" and fukuoka["2026-10-05"]["label"] == "トレーナー帯同", "③ 福岡側の帯同")
    report("2026-10-06" in tokyo and "2026-10-06" in fukuoka, "④ off は両方")
    report(tokyo["2026-10-06"]["label"] == "休業" and tokyo["2026-10-06"]["area"] is None, "④ 休業ラベル")
    report("休" not in tokyo["2026-10-05"]["label"] and "休" != tokyo["2026-10-06"]["label"], "⑭ GBPは「休」を使わない")
    report("2026-10-07" not in tokyo and "2026-10-07" not in fukuoka, "⑤ unset は両方に含めない")
    report("2026-10-02" not in tokyo and "2026-10-02" not in fukuoka, "⑥ レコードなしは両方に含めない")
    report("2026-10-08" not in tokyo and "2026-10-08" not in fukuoka, "⑦ clinic+areaなしは両方に含めない")
    report("2026-10-04" not in tokyo and "2026-10-03" not in fukuoka, "⑧ 他都市の clinic は含めない")
    report("2026-10-09" in tokyo and "2026-10-09" in fukuoka and tokyo["2026-10-09"]["area"] is None, "⑨ field+areaありでも両方、areaは空")
    report("2026-10-10" in tokyo and "2026-10-10" in fukuoka and fukuoka["2026-10-10"]["area"] is None, "⑨ off+areaありでも両方、areaは空")

    report(
        captured["start"] == date(2026, 10, 1) and captured["end"] == date(2026, 10, 15),
        "⑩ 過去を含んでも取得範囲を切り詰めない",
        f"{captured}",
    )
    report(captured["name"] == appmod.PUBLIC_SCHEDULE_STAFF_NAME, "公開オーナーのシフトだけを読む")
    report("2026-10-01" not in dates_for(start, end, "tokyo"), "⑩ 行がない過去日は結果に出ない")

    past_only = {
        "2026-10-01": row("clinic", "tokyo"),
        "2026-10-02": row("off", None),
    }
    install_shifts(past_only)
    past_tokyo = appmod.build_gbp_schedule_entries(date(2026, 10, 1), date(2026, 10, 2), "tokyo")
    report(
        [item["date"] for item in past_tokyo] == ["2026-10-01", "2026-10-02"],
        "⑩ 今日より前の対象日も残す",
        str(past_tokyo),
    )

    ordered = appmod.build_gbp_schedule_entries(date(2026, 10, 1), date(2026, 10, 2), "fukuoka")
    report([item["date"] for item in ordered] == ["2026-10-02"], "日付順")
    report(past_tokyo[0]["weekday"] == "木" and past_tokyo[1]["weekday"] == "金", "曜日")

    h1 = appmod.get_gbp_period_range(2026, 10, "H1")
    h2 = appmod.get_gbp_period_range(2026, 10, "H2")
    report(h1 == (date(2026, 10, 1), date(2026, 10, 15)), "⑪ 10月H1", str(h1))
    report(h2 == (date(2026, 10, 16), date(2026, 10, 31)), "⑫ 10月H2", str(h2))
    report(appmod.gbp_period_key(2026, 10, "h1") == "2026-10-H1", "period_key H1")
    report(appmod.gbp_period_key(2026, 10, "H2") == "2026-10-H2", "period_key H2")
    report(appmod.get_gbp_period_range(2026, 2, "H2")[1] == date(2026, 2, 28), "⑬ 2026年2月H2は28日")
    report(appmod.get_gbp_period_range(2024, 2, "H2")[1] == date(2024, 2, 29), "⑬ 閏年2月H2は29日")
    report(appmod.get_gbp_period_range(2026, 4, "H2")[1] == date(2026, 4, 30), "⑬ 4月H2は30日")
    report(appmod.get_gbp_period_range(2026, 10, "H2")[1] == date(2026, 10, 31), "⑬ 10月H2は31日")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
