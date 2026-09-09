"""KARiN.chatbot 利用分析ダッシュボード。予約INSERTなし。Knowledgeは変更しない。

  python scripts/test_karin_chat_analytics.py
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"), override=True)

from karin_chat_analytics import (  # noqa: E402
    JST,
    aggregate_usage_rows,
    empty_usage_report,
    format_rate,
    load_usage_analytics,
    rate_percent,
    resolve_period,
    set_analytics_fetch_for_tests,
)
from karin_chat_choices import FREE_OTHER, choice_set  # noqa: E402
from karin_chat_intent import INTENT_HEALTH, INTENT_RESERVATION, INTENT_TREATMENT  # noqa: E402


NOW = datetime(2026, 9, 9, 16, 0, tzinfo=JST)
GOAL = choice_set("treatment_goal")
PAIN = choice_set("pain_area")
ANALYTICS_PATH = Path(ROOT) / "karin_chat_analytics.py"
SECRET = "夜中に腰が痛くて眠れません。氏名は記録しないでください。"


def iso(day: int, hour: int = 12, minute: int = 0) -> str:
    return datetime(2026, 9, day, hour, minute, tzinfo=JST).isoformat()


def row(
    cid: str,
    day: int,
    *,
    hour: int = 12,
    next_intent: str | None = None,
    choice_set_name: str | None = None,
    shown: list[str] | None = None,
    selected: str | None = None,
    started: bool = False,
    completed: bool = False,
    row_id: str = "",
) -> dict:
    return {
        "id": row_id or f"{cid}-{day}-{hour}",
        "conversation_id": cid,
        "created_at": iso(day, hour),
        "next_intent": next_intent,
        "choice_set": choice_set_name,
        "shown_choices": list(shown or []),
        "selected_choice": selected,
        "booking_started": started,
        "booking_completed": completed,
    }


def report_for(rows: list[dict], preset: str = "7d"):
    period = resolve_period(preset, now=NOW)
    return aggregate_usage_rows(rows, period)


def banned_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    banned = {"karin_chat", "karin_chat_booking", "karin_chat_usage", "app"}
    found: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            root_name = name.split(".")[0]
            if root_name in banned:
                found.append(name)
    return found


def main() -> int:
    print("mode: chatbot analytics / 読み取り専用 / 予約INSERTなし")
    failures: list[str] = []
    set_analytics_fetch_for_tests(lambda **_k: [])

    print("\n===== Test 1 0件でも表示 =====")
    empty = report_for([])
    if empty["conversation_count"] != 0:
        failures.append(f"1: 会話数 {empty['conversation_count']}")
    if empty["booking_started_count"] != 0 or empty["booking_completed_count"] != 0:
        failures.append("1: 予約数が0でない")
    if empty["booking_complete_rate"] != "—":
        failures.append(f"1: 0件の完了率が {empty['booking_complete_rate']}")
    blank = empty_usage_report(resolve_period("7d", now=NOW))
    if SECRET in str(blank) or "090-" in str(blank):
        failures.append("1: 空レポートに個人情報がある")
    try:
        from flask import render_template

        from app import app

        with app.test_request_context("/admin/chatbot-analytics"):
            html = render_template("admin_chatbot_analytics.html", report=empty)
        if "KARiN.chatbot 利用分析" not in html:
            failures.append("1: ダッシュボードタイトルがない")
        if "総会話数" not in html:
            failures.append("1: 基本指標がない")
        if SECRET in html:
            failures.append("1: HTMLに本文がある")
    except Exception as exc:
        failures.append(f"1: テンプレート表示に失敗 {exc}")

    print("\n===== Test 2 1件のログ =====")
    one = report_for(
        [
            row(
                "c1",
                8,
                next_intent=INTENT_TREATMENT,
                choice_set_name="treatment_goal",
                shown=GOAL,
            )
        ]
    )
    if one["conversation_count"] != 1:
        failures.append(f"2: 会話数 {one['conversation_count']}")
    if one["row_count"] != 1:
        failures.append(f"2: 行数 {one['row_count']}")
    treatment = next(x for x in one["intents"] if x["name"] == INTENT_TREATMENT)
    if treatment["count"] != 1:
        failures.append(f"2: intent件数 {treatment['count']}")
    goal = next(x for x in one["choice_sets"] if x["key"] == "treatment_goal")
    if goal["displays"] != 1 or goal["selections"] != 0:
        failures.append(f"2: choice_set {goal}")

    print("\n===== Test 3 複数conversation =====")
    multi = report_for(
        [
            row("c1", 8, hour=10, next_intent=INTENT_TREATMENT),
            row("c2", 8, hour=11, next_intent=INTENT_HEALTH),
            row("c1", 8, hour=12, next_intent=INTENT_TREATMENT),
        ]
    )
    if multi["conversation_count"] != 2:
        failures.append(f"3: 会話数 {multi['conversation_count']}")
    if multi["row_count"] != 3:
        failures.append(f"3: 行数 {multi['row_count']}")

    print("\n===== Test 4 期間フィルタ =====")
    mixed = [
        row("old", 1, next_intent=INTENT_HEALTH, choice_set_name="sleep", shown=choice_set("sleep")),
        row("new", 8, next_intent=INTENT_TREATMENT),
        row("todayc", 9, next_intent=INTENT_HEALTH),
    ]
    filtered = report_for(mixed, "7d")
    if filtered["conversation_count"] != 2:
        failures.append(f"4: 7日の会話数 {filtered['conversation_count']}")
    today_only = report_for(mixed, "today")
    if today_only["conversation_count"] != 1:
        failures.append(f"4: 今日の会話数 {today_only['conversation_count']}")
    all_period = report_for(mixed, "all")
    if all_period["conversation_count"] != 3:
        failures.append(f"4: 全期間の会話数 {all_period['conversation_count']}")
    custom_period = resolve_period("custom", "2026-09-01", "2026-09-01", now=NOW)
    custom = aggregate_usage_rows(mixed, custom_period)
    if custom["conversation_count"] != 1:
        failures.append(f"4: カスタム期間の会話数 {custom['conversation_count']}")

    print("\n===== Test 5 intent別 =====")
    intent_report = report_for(
        [
            row("a", 8, hour=10, next_intent=INTENT_TREATMENT),
            row("b", 8, hour=11, next_intent=INTENT_RESERVATION),
            row("c", 8, hour=12, next_intent=INTENT_TREATMENT),
        ]
    )
    by_intent = {item["name"]: item["count"] for item in intent_report["intents"]}
    if by_intent.get(INTENT_TREATMENT) != 2:
        failures.append(f"5: treatment {by_intent.get(INTENT_TREATMENT)}")
    if by_intent.get(INTENT_RESERVATION) != 1:
        failures.append(f"5: reservation {by_intent.get(INTENT_RESERVATION)}")
    if INTENT_TREATMENT not in by_intent:
        failures.append("5: コード上のintent名がない")

    print("\n===== Test 6/7 choice_set と selected_choice =====")
    click_rows = [
        row(
            "c1",
            8,
            hour=10,
            next_intent=INTENT_TREATMENT,
            choice_set_name="treatment_goal",
            shown=GOAL,
        ),
        row(
            "c1",
            8,
            hour=11,
            next_intent=INTENT_TREATMENT,
            choice_set_name="pain_area",
            shown=PAIN,
            selected="痛みを軽減したい",
        ),
        row(
            "c2",
            8,
            hour=12,
            next_intent=INTENT_TREATMENT,
            choice_set_name="treatment_goal",
            shown=GOAL,
            selected=None,
        ),
    ]
    choices = report_for(click_rows)
    sets = {item["key"]: item for item in choices["choice_sets"]}
    if sets["treatment_goal"]["displays"] != 2:
        failures.append(f"6: treatment_goal 表示 {sets['treatment_goal']}")
    if sets["treatment_goal"]["selections"] != 1:
        failures.append("6: 同じ行JOINだと treatment_goal 選択が取れない")
    if sets["pain_area"]["displays"] != 1:
        failures.append(f"6: pain_area 表示 {sets['pain_area']}")
    if sets["pain_area"]["selections"] != 0:
        failures.append("7: 同じ行の selected_choice を pain_area に誤集計している")
    goal_options = next(g for g in choices["choice_options"] if g["choice_set"] == "treatment_goal")
    pain_options = next(g for g in choices["choice_options"] if g["choice_set"] == "pain_area")
    goal_map = {item["label"]: item["count"] for item in goal_options["options"]}
    pain_map = {item["label"]: item["count"] for item in pain_options["options"]}
    if goal_map.get("痛みを軽減したい") != 1:
        failures.append(f"7: 選択ラベル {goal_map}")
    if pain_map.get("痛みを軽減したい"):
        failures.append("7: pain_area に誤って選択が入っている")
    if FREE_OTHER not in goal_map:
        failures.append("7: その他・自由に相談が選択肢別から欠けている")
    if SECRET in str(choices):
        failures.append("7: 集計結果に自由入力本文がある")

    print("\n===== Test 8 予約開始数 =====")
    start_rows = [
        row("s1", 8, hour=10, next_intent=INTENT_RESERVATION, started=True),
        row("s1", 8, hour=11, next_intent=INTENT_RESERVATION, started=False),
        row("s2", 8, hour=12, next_intent=INTENT_TREATMENT, started=False),
        row("s3", 8, hour=13, next_intent=INTENT_RESERVATION, started=True),
    ]
    started = report_for(start_rows)
    if started["conversation_count"] != 3:
        failures.append(f"8: 会話数 {started['conversation_count']}")
    if started["booking_started_count"] != 2:
        failures.append(f"8: 予約開始 {started['booking_started_count']}")

    print("\n===== Test 9 予約完了数 =====")
    complete_rows = [
        row("b1", 8, hour=10, started=True),
        row("b1", 8, hour=11, completed=True),
        row("b2", 8, hour=12, started=True),
    ]
    completed = report_for(complete_rows)
    if completed["booking_started_count"] != 2:
        failures.append(f"9: 予約開始 {completed['booking_started_count']}")
    if completed["booking_completed_count"] != 1:
        failures.append(f"9: 予約完了 {completed['booking_completed_count']}")
    if completed["booking_complete_rate"] != "50.0%":
        failures.append(f"9: 開始→完了率 {completed['booking_complete_rate']}")
    if completed["booking_overall_rate"] != "50.0%":
        failures.append(f"9: 総会話→完了率 {completed['booking_overall_rate']}")

    print("\n===== Test 10 0件除算 =====")
    if rate_percent(1, 0) is not None:
        failures.append("10: rate_percent が 0 除算している")
    if format_rate(0, 0) != "—":
        failures.append(f"10: format_rate {format_rate(0, 0)}")
    zero = report_for([])
    if zero["booking_start_rate"] != "—" or zero["booking_complete_rate"] != "—":
        failures.append("10: 空データで率が数値になっている")

    print("\n===== Test 11 chatbot本体をimportしない =====")
    imported = banned_imports(ANALYTICS_PATH)
    if imported:
        failures.append(f"11: 禁止import {imported}")
    if "karin_chat.py" in ANALYTICS_PATH.read_text(encoding="utf-8"):
        failures.append("11: analytics が karin_chat.py を参照している")

    print("\n===== Test 12 予約処理に触れない =====")
    analytics_src = ANALYTICS_PATH.read_text(encoding="utf-8")
    for needle in (
        "atomic_create_web_reservation",
        "complete_chat_booking",
        "reservations",
        "send_line_message",
        "send_booking_confirmation_email",
        "insert(",
        "upsert",
        "delete(",
    ):
        if needle in analytics_src:
            failures.append(f"12: 分析コードに予約/書き込み処理 {needle}")
    if "chatbot_usage_logs" not in analytics_src:
        failures.append("12: chatbot_usage_logs を読んでいない")

    print("\n===== 認証 =====")
    try:
        from app import app

        with app.test_client() as client:
            res = client.get("/admin/chatbot-analytics")
            if res.status_code != 403:
                failures.append(f"auth: 未ログインが {res.status_code}")
    except Exception as exc:
        failures.append(f"auth: {exc}")

    print("\n===== load 失敗しても例外を出さない =====")
    def boom(**_k):
        raise RuntimeError("analytics fetch failed on purpose")

    set_analytics_fetch_for_tests(boom)
    safe = load_usage_analytics(preset="7d", now=NOW)
    if not safe.get("error"):
        failures.append("load: 失敗時に error がない")
    if safe["conversation_count"] != 0:
        failures.append("load: 失敗時に数値が残っている")
    set_analytics_fetch_for_tests(lambda **_k: [])

    print("\n===== 日別推移 =====")
    daily = report_for(
        [
            row("d1", 8, started=True),
            row("d2", 9, completed=True),
        ],
        "7d",
    )
    by_day = {item["date"]: item for item in daily["daily"]}
    if len(daily["daily"]) != 7:
        failures.append(f"daily: 7日分でない {len(daily['daily'])}")
    if by_day.get("2026-09-08", {}).get("conversations") != 1:
        failures.append("daily: 9/8 の会話数")
    if by_day.get("2026-09-08", {}).get("started") != 1:
        failures.append("daily: 9/8 の予約開始")
    if by_day.get("2026-09-09", {}).get("completed") != 1:
        failures.append("daily: 9/9 の予約完了")

    print("\n===== 境界の前ターン選択 =====")
    boundary = report_for(
        [
            row(
                "edge",
                2,
                hour=23,
                choice_set_name="treatment_goal",
                shown=GOAL,
                next_intent=INTENT_TREATMENT,
            ),
            row(
                "edge",
                3,
                hour=1,
                selected="姿勢を改善したい",
                choice_set_name="pain_area",
                shown=PAIN,
                next_intent=INTENT_TREATMENT,
            ),
        ],
        "7d",
    )
    edge_sets = {item["key"]: item for item in boundary["choice_sets"]}
    if edge_sets["treatment_goal"]["selections"] != 1:
        failures.append("boundary: 期間外に出したセットへの選択が落ちている")
    if edge_sets["pain_area"]["selections"] != 0:
        failures.append("boundary: 同じ行の choice_set に誤って選択している")

    if failures:
        print("\nFAIL")
        for item in failures:
            print("-", item)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
