"""会話に応じたフォローアップ選択肢。LLMは生成せず、定義済みセットだけを出す。

正本はこのモジュール。利用状況を見て人間がセットを直す。
ユーザーごとに学習して増やしたり、AIがUI定義を書き換えたりしない。
"""
from __future__ import annotations

import re

from karin_chat_booking import (
    PHASE_ALT,
    PHASE_COMPLETED,
    PHASE_CONFIRMING,
    PHASE_GUEST,
    BookingDraft,
    draft_missing_for_lookup,
)
from karin_chat_intent import (
    INTENT_CONSULTATION,
    INTENT_HEALTH,
    INTENT_RESERVATION,
    INTENT_TREATMENT,
    INQUIRY_REQUIRED_INTENTS,
    IntentResult,
    is_inquiry_required_intent,
)

FREE_OTHER = "その他・自由に相談"

CHOICE_SETS: dict[str, list[str]] = {
    "treatment_goal": [
        "痛みを軽減したい",
        "疲労を取りたい",
        "姿勢を改善したい",
        "身体のバランスを整えたい",
    ],
    "sleep": [
        "寝つきを改善したい",
        "夜中に目が覚める",
        "朝すっきり起きたい",
        "睡眠の質を高めたい",
    ],
    "conditioning": [
        "パフォーマンスを高めたい",
        "疲労を取りたい",
        "ケガを予防したい",
        "身体の動きを改善したい",
    ],
    "pain_area": [
        "首・肩",
        "腰",
        "背中",
    ],
    "booking_area": [
        "東京",
        "福岡",
    ],
    "booking_duration": [
        "60分",
        "90分",
        "120分",
    ],
    "booking_window": [
        "直近で空いているところ",
        "平日の夜",
        "土日で空いている日",
    ],
}

_ASK_RE = re.compile(
    r"教えて|どちら|どっち|どんな|どのあたり|どのへ|希望|"
    r"どうでしょう|いかが|改善したいか|[？?]"
)
_TREATMENT_COMPARE_RE = re.compile(
    r"(鍼|整体|美容鍼).{0,24}(どっち|どちら|合い)|鍼と整体|整体と鍼"
)
_SLEEP_RE = re.compile(r"睡眠|寝つき|眠れ|眠気|寝不足|就寝|起床|夜中に目")
_CONDITIONING_RE = re.compile(
    r"運動|パフォーマンス|ケガ|怪我|コンディショニング|トレーニング"
)
_PAIN_GOAL_RE = re.compile(r"痛みを軽減したい")
_LOCATION_RE = re.compile(r"首|肩|腰|背中|膝|肘|股関節")
_CONFIRM_RE = re.compile(r"予約内容をご確認|この日時でご予約を進めますか|予約を確定")
_SLOT_LIST_RE = re.compile(r"空きが確認でき|空き状況を確認|以下の日付に空き|空きがあります")


def with_other(items: list[str]) -> list[str]:
    out = [x for x in items if x]
    if FREE_OTHER not in out:
        out.append(FREE_OTHER)
    return out


def choice_set(name: str) -> list[str]:
    return with_other(list(CHOICE_SETS.get(name) or []))


def _has(pattern: str | re.Pattern, text: str) -> bool:
    raw = text or ""
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(raw))
    return bool(re.search(pattern, raw))


def _joined(current: str, priors: list[str] | None) -> str:
    parts = [p for p in (priors or []) if p] + [current or ""]
    return " ".join(parts)


def _reply_asks(reply: str) -> bool:
    return bool(_ASK_RE.search(reply or ""))


def _in_booking_flow(draft: BookingDraft | None, intent: IntentResult | None) -> bool:
    if draft is None:
        return False
    if draft.reservation_intent:
        return True
    if intent is not None and INTENT_RESERVATION in intent.all_intents:
        return True
    return False


def _booking_set(
    draft: BookingDraft | None,
    reply: str,
) -> list[str]:
    if draft is None:
        return []
    if draft.phase in (PHASE_GUEST, PHASE_CONFIRMING, PHASE_COMPLETED, PHASE_ALT):
        return []
    if _CONFIRM_RE.search(reply or "") or _SLOT_LIST_RE.search(reply or ""):
        return []
    missing = draft_missing_for_lookup(draft)
    if draft.area not in ("tokyo", "fukuoka") and (
        "area" in missing or _has(r"東京|福岡", reply)
    ):
        return choice_set("booking_area")
    if draft.duration_minutes not in (60, 90, 120) and (
        "duration" in missing or _has(r"60分・90分・120分", reply)
    ):
        return choice_set("booking_duration")
    if not draft.date and not draft.date_candidates and (
        "date" in missing or _has(r"直近で空いているところ", reply)
    ):
        return choice_set("booking_window")
    return []


def _consult_topic(current: str, priors: list[str] | None, reply: str) -> str | None:
    blob = _joined(current, priors)
    if _PAIN_GOAL_RE.search(current or "") and _has(r"どこ|どのあたり|部位", reply):
        if not _LOCATION_RE.search(current or "") and not any(
            _LOCATION_RE.search(p or "") for p in (priors or [])
        ):
            return "pain_area"
    if _SLEEP_RE.search(blob):
        return "sleep"
    if _CONDITIONING_RE.search(blob):
        return "conditioning"
    if _TREATMENT_COMPARE_RE.search(current or "") or _TREATMENT_COMPARE_RE.search(blob):
        return "treatment_goal"
    return "treatment_goal"


def select_followup_choices(
    *,
    user_text: str,
    reply: str,
    emergency: bool = False,
    intent: IntentResult | None = None,
    draft: BookingDraft | None = None,
    prior_user_texts: list[str] | None = None,
) -> list[str]:
    """次ターン用のチップ。不要なら空。"""
    if emergency:
        return []
    if (user_text or "").strip() == FREE_OTHER:
        return []
    if intent is not None and is_inquiry_required_intent(intent):
        return []
    if intent is not None and intent.primary_intent in INQUIRY_REQUIRED_INTENTS:
        return []
    if draft is not None and draft.phase in (
        PHASE_GUEST,
        PHASE_CONFIRMING,
        PHASE_COMPLETED,
        PHASE_ALT,
    ):
        return []
    if _CONFIRM_RE.search(reply or ""):
        return []

    if _in_booking_flow(draft, intent):
        return _booking_set(draft, reply or "")

    consultish = False
    if intent is not None:
        consultish = any(
            x in intent.all_intents
            for x in (INTENT_TREATMENT, INTENT_CONSULTATION, INTENT_HEALTH)
        )
    compare = bool(_TREATMENT_COMPARE_RE.search(user_text or ""))
    if not consultish and not compare:
        return []
    if not compare and not _reply_asks(reply or ""):
        return []
    topic = _consult_topic(user_text or "", prior_user_texts, reply or "")
    if not topic:
        return []
    return choice_set(topic)
