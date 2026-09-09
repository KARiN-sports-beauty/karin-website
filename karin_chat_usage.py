"""KARiN.chatbot 利用分析ログ。会話・RAG・予約とは独立した非クリティカル処理。

会話全文・氏名・電話・メール・住所は保存しない。
INSERT 失敗は chatbot の応答・予約確定へ伝播させない。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from karin_chat_choices import CHOICE_SETS, with_other

logger = logging.getLogger("karin_chat")

INPUT_CHOICE = "choice"
INPUT_FREE_TEXT = "free_text"
INPUT_OTHER = "other"
_ALLOWED_INPUT = frozenset({INPUT_CHOICE, INPUT_FREE_TEXT, INPUT_OTHER})

# 直前ターンで出したチップ。会話本文は持たない。C3 の messages とは別。
_TURN_META: dict[str, dict[str, Any]] = {}
_MAX_TURN_META = 200

# None=本番INSERT / callable=テスト用 / False=INSERTしない
_sink: Callable[[dict], None] | bool | None = None


def set_usage_log_sink(fn: Callable[[dict], None] | bool | None) -> None:
    global _sink
    _sink = fn


def reset_usage_state_for_tests() -> None:
    global _sink
    _TURN_META.clear()
    _sink = False


def identify_choice_set(shown: list[str] | None) -> str | None:
    items = [str(x) for x in (shown or []) if str(x).strip()]
    if not items:
        return None
    for name, labels in CHOICE_SETS.items():
        if with_other(list(labels)) == items:
            return name
    return None


def classify_input_type(
    user_text: str,
    previous_shown: list[str] | None,
    *,
    emergency: bool = False,
) -> tuple[str, str | None]:
    """選択肢クリックなら chip 文言のみ返す。自由入力本文は返さない。"""
    if emergency:
        return INPUT_OTHER, None
    shown = [str(x) for x in (previous_shown or []) if str(x).strip()]
    raw = (user_text or "").strip()
    if raw and shown and raw in shown:
        return INPUT_CHOICE, raw
    return INPUT_FREE_TEXT, None


def _sanitize_shown(values: list[str] | None) -> list[str] | None:
    out: list[str] = []
    for item in values or []:
        label = str(item).strip()
        if not label:
            continue
        out.append(label[:80])
        if len(out) >= 8:
            break
    return out or None


def _build_row(
    *,
    conversation_id: str,
    intent: str | None = None,
    choice_set: str | None = None,
    shown_choices: list[str] | None = None,
    selected_choice: str | None = None,
    input_type: str | None = None,
    next_intent: str | None = None,
    booking_started: bool = False,
    booking_completed: bool = False,
) -> dict:
    cid = (conversation_id or "").strip()
    if not cid:
        raise ValueError("conversation_id required")
    itype = input_type if input_type in _ALLOWED_INPUT else None
    shown = _sanitize_shown(shown_choices)
    selected = None
    if itype == INPUT_CHOICE and selected_choice:
        label = str(selected_choice).strip()[:80]
        selected = label or None
    return {
        "conversation_id": cid,
        "intent": (intent or "").strip() or None,
        "choice_set": (choice_set or "").strip() or None,
        "shown_choices": shown,
        "selected_choice": selected,
        "input_type": itype,
        "next_intent": (next_intent or "").strip() or None,
        "booking_started": bool(booking_started),
        "booking_completed": bool(booking_completed),
    }


def _insert_row(row: dict) -> None:
    from ai_knowledge import get_admin_client

    get_admin_client().table("chatbot_usage_logs").insert(row).execute()


def log_chatbot_usage(
    conversation_id: str,
    intent: str | None = None,
    choice_set: str | None = None,
    shown_choices: list[str] | None = None,
    selected_choice: str | None = None,
    input_type: str | None = None,
    next_intent: str | None = None,
    booking_started: bool = False,
    booking_completed: bool = False,
) -> None:
    try:
        row = _build_row(
            conversation_id=conversation_id,
            intent=intent,
            choice_set=choice_set,
            shown_choices=shown_choices,
            selected_choice=selected_choice,
            input_type=input_type,
            next_intent=next_intent,
            booking_started=booking_started,
            booking_completed=booking_completed,
        )
        sink = _sink
        if sink is False:
            return
        if callable(sink):
            sink(row)
            return
        _insert_row(row)
    except Exception:
        logger.exception("chatbot usage log failed")


def record_chat_usage(
    *,
    conversation_id: str,
    user_text: str,
    primary_intent: str | None,
    followup_choices: list[str],
    reservation_intent: bool,
    booking_completed: bool,
    emergency: bool,
) -> None:
    """1ターン分を記録する。user_text はチップ照合のみに使い、DBへは出さない。"""
    cid = (conversation_id or "").strip()
    if not cid:
        return
    prev = _TURN_META.get(cid) or {}
    prev_shown = list(prev.get("shown") or [])
    prev_intent = prev.get("intent")
    was_booking = bool(prev.get("reservation"))
    input_type, selected_choice = classify_input_type(
        user_text,
        prev_shown,
        emergency=emergency,
    )
    shown = _sanitize_shown(followup_choices) or []
    log_chatbot_usage(
        conversation_id=cid,
        intent=prev_intent,
        choice_set=identify_choice_set(shown),
        shown_choices=shown,
        selected_choice=selected_choice,
        input_type=input_type,
        next_intent=primary_intent,
        booking_started=bool(reservation_intent and not was_booking),
        booking_completed=bool(booking_completed),
    )
    _TURN_META.pop(cid, None)
    _TURN_META[cid] = {
        "shown": shown,
        "intent": primary_intent,
        "reservation": bool(reservation_intent),
    }
    overflow = len(_TURN_META) - _MAX_TURN_META
    if overflow > 0:
        for key in list(_TURN_META.keys())[:overflow]:
            _TURN_META.pop(key, None)
