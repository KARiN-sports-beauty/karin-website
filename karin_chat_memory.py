"""KARiN.chatbot C3: 短期の会話状態。Flask session とは独立。永続DBへは保存しない。"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from karin_chat_booking import BookingDraft

# 直近の相談をつなぐための上限。長期記憶ではない。
MAX_USER_TURNS = 8
TTL_SECONDS = 45 * 60
MAX_CONVERSATIONS = 200
_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_LOCK = threading.Lock()
_STORE: dict[str, "ConversationState"] = {}


@dataclass
class ConversationState:
    conversation_id: str
    messages: list[dict] = field(default_factory=list)
    updated_at: float = field(default_factory=time.time)
    booking_draft: BookingDraft = field(default_factory=BookingDraft)

    @property
    def user_turn_count(self) -> int:
        return sum(1 for m in self.messages if m.get("role") == "user")

    def prior_user_texts(self) -> list[str]:
        return [
            (m.get("content") or "").strip()
            for m in self.messages
            if m.get("role") == "user" and (m.get("content") or "").strip()
        ]


def new_conversation_id() -> str:
    return str(uuid.uuid4())


def normalize_conversation_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or not _ID_RE.match(text):
        return None
    return text.lower()


def _purge_locked(now: float) -> None:
    expired = [
        cid
        for cid, state in _STORE.items()
        if now - state.updated_at > TTL_SECONDS
    ]
    for cid in expired:
        _STORE.pop(cid, None)
    if len(_STORE) <= MAX_CONVERSATIONS:
        return
    oldest = sorted(_STORE.items(), key=lambda item: item[1].updated_at)
    overflow = len(_STORE) - MAX_CONVERSATIONS
    for cid, _state in oldest[:overflow]:
        _STORE.pop(cid, None)


def get_or_create_conversation(conversation_id: str | None) -> ConversationState:
    cid = normalize_conversation_id(conversation_id)
    now = time.time()
    with _LOCK:
        if cid and cid in _STORE:
            state = _STORE[cid]
            if now - state.updated_at <= TTL_SECONDS:
                state.updated_at = now
                _purge_locked(now)
                return state
            _STORE.pop(cid, None)
        state = ConversationState(conversation_id=cid or new_conversation_id(), updated_at=now)
        _STORE[state.conversation_id] = state
        _purge_locked(now)
        return state


def append_turn(state: ConversationState, user_text: str, assistant_text: str) -> None:
    now = time.time()
    with _LOCK:
        state.messages.append({"role": "user", "content": user_text})
        state.messages.append({"role": "assistant", "content": assistant_text})
        extra = state.user_turn_count - MAX_USER_TURNS
        if extra > 0:
            drop = extra * 2
            state.messages = state.messages[drop:]
        state.updated_at = now
        _STORE[state.conversation_id] = state


def history_messages(state: ConversationState) -> list[dict]:
    """OpenAIへ渡す直近履歴。現在ターンのuserは含まない。"""
    return list(state.messages[-MAX_USER_TURNS * 2 :])


def reset_store_for_tests() -> None:
    with _LOCK:
        _STORE.clear()
