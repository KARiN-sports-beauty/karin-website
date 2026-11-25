#!/usr/bin/env python3
"""管理画面の新規予定・編集の予約日時。"""
from __future__ import annotations

import os
import sys

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


def main():
    date_s, time_s, combined = appmod.admin_reservation_form_datetime_parts(
        "2026-11-25", "14:00"
    )
    report(
        date_s == "2026-11-25" and time_s == "14:00" and combined == "2026-11-25T14:00",
        "クリックした日時を初期値にする",
        f"{date_s} {time_s} {combined}",
    )

    date_only, time_only, combined_only = appmod.admin_reservation_form_datetime_parts(
        "2026-11-25", ""
    )
    report(
        date_only == "2026-11-25" and time_only == "09:00",
        "日付だけの新規予定は9:00を入れる",
        f"{date_only} {time_only}",
    )

    late_date, late_time, late_combined = appmod.admin_reservation_form_datetime_parts(
        "2026-11-25", "25:00"
    )
    report(
        late_date == "2026-11-25" and late_time == "25:00" and late_combined == "2026-11-25T25:00",
        "24時超のクリック時刻も初期値にする",
        f"{late_date} {late_time} {late_combined}",
    )

    parsed = appmod.parse_admin_reservation_form_datetime("2026-11-25T14:07")
    report(
        parsed is not None and parsed.strftime("%Y-%m-%d %H:%M") == "2026-11-25 14:00",
        "手入力の時刻を15分刻みに丸める",
        str(parsed),
    )

    typed = appmod.parse_admin_reservation_form_datetime("2026-11-26T18:30")
    report(
        typed is not None and typed.strftime("%Y-%m-%d %H:%M") == "2026-11-26 18:30",
        "編集画面で打ち直した日時を保存できる",
        str(typed),
    )

    overnight = appmod.parse_admin_reservation_form_datetime("2026-11-25T25:00")
    report(
        overnight is not None and overnight.strftime("%Y-%m-%d %H:%M") == "2026-11-26 01:00",
        "25:00は翌日1:00として保存する",
        str(overnight),
    )

    report(
        appmod.admin_reservation_default_end_clock("14:00") == "15:00",
        "予定の終了は開始の1時間後を初期値にする",
    )
    report(
        appmod.admin_reservation_default_end_clock("25:30") == "26:00",
        "終了が26:00を超えない",
    )

    new_html = open(os.path.join(ROOT, "templates/admin_reservations_new.html"), encoding="utf-8").read()
    edit_html = open(os.path.join(ROOT, "templates/admin_reservations_edit.html"), encoding="utf-8").read()
    report("initial_date_part" in new_html and "initial_time_part" in new_html, "新規画面は日付と時刻を分けて表示する")
    report("reserved_at_date_part" in edit_html and "reserved_at_time_part" in edit_html, "編集画面は保存済み日時を表示する")
    report('type="hidden" name="reserved_at"' in new_html and 'type="hidden" name="reserved_at"' in edit_html, "送信値はhiddenで日付・時刻入力と同期する")
    report("datetime-local" not in new_html and "datetime-local" not in edit_html, "datetime-local非表示欄に依存しない")
    report('id="field_end_time"' in new_html and 'type="text"' in new_html, "新規の予定終了も手入力できる")
    report('id="field_end_hour"' not in new_html and 'id="field_end_hour"' not in edit_html, "終了時刻のプルダウンにしない")
    report("field_end_time_display" in edit_html, "編集画面は保存済みの終了時刻を表示する")
    report("initial_end_time" in new_html, "新規予定の終了もクリック時刻から初期表示する")

    datetime_idx = new_html.find('id="reservation_datetime_section"')
    patient_idx = new_html.find('id="patient_selection_section"')
    report(
        datetime_idx != -1 and patient_idx != -1 and datetime_idx < patient_idx,
        "新規画面は区分の直後に開始日時を置く",
        f"datetime={datetime_idx} patient={patient_idx}",
    )
    report(
        'id="reserved_at_label"' in new_html
        and "開始日時" in new_html
        and "予約日時" not in new_html.split("updatePlaceTypeFields")[0],
        "新規の開始ラベルは全区分で開始日時",
    )
    report(
        'id="reserved_at_label"' in edit_html and ">開始日時<" in edit_html,
        "編集の開始ラベルは全区分で開始日時",
    )
    report(
        "reservedAtLabel.textContent = '開始日時'" in new_html
        and "reservedAtLabel.textContent = '予約日時'" not in new_html
        and "reservedAtLabel.textContent = '帯同日時'" not in new_html
        and "予定時間（開始）" not in new_html
        and "休憩時間（開始）" not in new_html,
        "区分切替でも開始ラベルを変えない",
    )
    report(
        "reservedAtLabel.textContent = '開始日時'" in edit_html
        and "reservedAtLabel.textContent = '予約日時'" not in edit_html
        and "reservedAtLabel.textContent = '帯同日時'" not in edit_html,
        "編集の区分切替でも開始ラベルを変えない",
    )
    menus_js = open(os.path.join(ROOT, "static/js/admin_reservation_menus.js"), encoding="utf-8").read()
    report(
        "selectReservationFieldOnFocus" in menus_js
        and "dateEl.addEventListener('input'" not in menus_js
        and "timeEl.addEventListener('input'" not in menus_js,
        "編集中は入力のたびに値を作り直さない",
    )
    report('maxlength="8"' in edit_html and 'maxlength="5"' not in edit_html, "編集の時刻欄は5文字で打ち直せなくしない")
    css = open(os.path.join(ROOT, "static/css/admin_dashboard.css"), encoding="utf-8").read()
    wrap_css = css.split(".admin-reservation-start-pickers .admin-reservation-native-input-wrap", 1)[-1][:500]
    report(
        "flex: 1 1 0" not in wrap_css and "min-height: 44px" in css,
        "狭い画面でも開始・終了欄の高さを0にしない",
        wrap_css[:120],
    )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
