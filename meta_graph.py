"""KARiN.NOTES の Facebook ページ投稿。

Instagram と GBP は扱わない。このモジュールを読み込んだだけでは Meta へ送信しない。
トークンは Authorization ヘッダーだけに置き、URL・ログ・例外文言には出さない。
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import requests

GRAPH_VERSION = "v27.0"
GRAPH_HOST = "https://graph.facebook.com"
FEED_TIMEOUT_SECONDS = 30
FACEBOOK_SEND_STATUSES = frozenset({"draft", "ready", "failed"})
_PAGE_ID = re.compile(r"^[0-9]{1,32}$")
_POST_ID = re.compile(r"^[0-9]+_[0-9]+$")
_HTML_TAG = re.compile(r"<[^>]{0,200}>")
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+", re.I)
_BEARER_IN_TEXT = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+=/]+")
_TOKEN_ASSIGN = re.compile(
    r"(?i)\b(access_token|refresh_token|client_secret|authorization)\s*[:=]\s*[^\s,;]+"
)
_EAA_TOKEN = re.compile(r"\bEAA[A-Za-z0-9]+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{24,}\b")


class MetaGraphTimeout(Exception):
    """応答がなく、作成されたかどうかが分からない。"""


class MetaGraphRefused(Exception):
    """送信しない。detail に秘密情報は入れない。"""

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


def load_facebook_config(env=None):
    """Facebook投稿に使う値だけ読む。値は返すが、呼び出し側はログに出さない。"""
    source = env if env is not None else os.environ
    return {
        "access_token": (source.get("FACEBOOK_SYSTEM_USER_ACCESS_TOKEN") or "").strip(),
        "page_id": (source.get("FACEBOOK_PAGE_ID") or "").strip(),
    }


def missing_facebook_env(config):
    missing = []
    if not (config.get("access_token") or "").strip():
        missing.append("FACEBOOK_SYSTEM_USER_ACCESS_TOKEN")
    if not (config.get("page_id") or "").strip():
        missing.append("FACEBOOK_PAGE_ID")
    return missing


def sanitize_meta_error_message(text):
    """ログ・DB用。トークン・URL・長い秘密らしき文字列は残さない。"""
    if not isinstance(text, str):
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    lowered = cleaned.lstrip().lower()
    if lowered.startswith("<!doctype") or lowered.startswith("<html"):
        return None
    cleaned = _HTML_TAG.sub(" ", cleaned)
    cleaned = _BEARER_IN_TEXT.sub("[redacted]", cleaned)
    cleaned = _TOKEN_ASSIGN.sub(r"\1=[redacted]", cleaned)
    cleaned = _EAA_TOKEN.sub("[redacted]", cleaned)
    cleaned = _URL_IN_TEXT.sub("[url]", cleaned)
    cleaned = _LONG_TOKEN.sub("[redacted]", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > 240:
        cleaned = cleaned[:240]
    lowered = cleaned.lower()
    if any(
        marker in lowered
        for marker in ("bearer ", "access_token=", "authorization", "eaa")
    ) and "[redacted]" not in lowered:
        return "redacted"
    return cleaned or None


def facebook_feed_url(page_id):
    page = (page_id or "").strip()
    if not _PAGE_ID.fullmatch(page):
        raise MetaGraphRefused("FacebookページIDが不正なため、送信しません。")
    return f"{GRAPH_HOST}/{GRAPH_VERSION}/{page}/feed"


def facebook_preview(body, link_url):
    """送信JSONは作らない。画面確認用。Metaへは送らない。"""
    errors = []
    message = (body or "").replace("\r\n", "\n").strip()
    if not message:
        errors.append("投稿文を入力してください")
    elif len(message) > 5000:
        errors.append("投稿文が長すぎます")
    link = _require_https_link(link_url)
    if not link:
        errors.append("リンクは https の記事URLにしてください")
    if errors:
        return {"ok": False, "errors": errors, "payload_text": "", "message": message, "link": link}
    payload_text = f"message:\n{message}\n\nlink:\n{link}"
    return {
        "ok": True,
        "errors": [],
        "payload_text": payload_text,
        "message": message,
        "link": link,
    }


def build_facebook_feed_payload(body, link_url):
    preview = facebook_preview(body, link_url)
    if not preview["ok"]:
        raise MetaGraphRefused(preview["errors"][0])
    return {"message": preview["message"], "link": preview["link"]}


def can_send_facebook_record(record):
    if not record or not record.get("id"):
        return False, "保存したFacebookだけ送信できます。"
    if record.get("channel") != "facebook":
        return False, "Facebookの保存内容だけ送信できます。"
    status = record.get("status")
    if status == "posting":
        return False, "送信中です。重なって送信しません。"
    if status == "posted":
        return False, "投稿済みの記録は再送しません。"
    if status == "unknown":
        return False, "結果が未確認です。自動では再送しません。"
    if status not in FACEBOOK_SEND_STATUSES:
        return False, "この状態からは投稿できません。"
    return True, None


def begin_notes_facebook_create(record, now):
    allowed, reason = can_send_facebook_record(record)
    if not allowed:
        return None, reason
    return {
        "fields": {
            "status": "posting",
            "error_message": None,
            "updated_at": now,
        },
        "event": {
            "event": "submit_started",
            "body_snapshot": record.get("body") or "",
            "link_url": record.get("link_url") or None,
            "image_url": record.get("image_url") or None,
            "detail": "送信を開始しました。成功を確認するまで投稿済にはしません。",
            "created_at": now,
        },
    }, None


def finish_notes_facebook_create(record, *, http_status, body, timed_out, now):
    """投稿IDがある200だけ posted。4xxは failed。5xx・タイムアウト・IDなしは unknown。"""
    if timed_out or http_status is None or http_status >= 500:
        return _outcome(
            record,
            status="unknown",
            error_message="結果不明。自動再送しません。",
            event="unknown",
            detail="結果不明。自動再送しません。Facebook側で投稿の有無を確認してください。",
            now=now,
        )
    if http_status == 200:
        post_id = _facebook_post_id(body)
        if post_id:
            return _outcome(
                record,
                status="posted",
                external_id=post_id,
                posted_at=now,
                error_message=None,
                event="succeeded",
                detail=f"投稿成功を確認しました。Facebook投稿ID: {post_id}",
                now=now,
            )
        return _outcome(
            record,
            status="unknown",
            error_message="応答に投稿IDがありません。",
            event="unknown",
            detail="投稿IDを確認できないため、投稿済にしていません。自動では再送しません。",
            now=now,
        )
    if 400 <= http_status < 500:
        message = _facebook_error_text(body, http_status)
        return _outcome(
            record,
            status="failed",
            error_message=message,
            event="failed",
            detail=message,
            now=now,
        )
    return _outcome(
        record,
        status="unknown",
        error_message="結果不明。自動再送しません。",
        event="unknown",
        detail="結果不明。自動再送しません。",
        now=now,
    )


def perform_notes_facebook_create(
    client, record, *, config, post_exchange, now, staff_id=None, post_store=None
):
    """保存済みFacebookだけPOSTする。成功するまで posted にしない。自動再送しない。"""
    store = _post_store(post_store)
    allowed, reason = can_send_facebook_record(record)
    if not allowed:
        return _flow(False, record, reason)
    missing = missing_facebook_env(config)
    if missing:
        return _flow(False, record, "Facebook投稿の設定が不足しているため、送信しません。")
    try:
        url = facebook_feed_url(config.get("page_id"))
        payload = build_facebook_feed_payload(record.get("body"), record.get("link_url"))
        access_token = (config.get("access_token") or "").strip()
        if not access_token:
            return _flow(False, record, "Facebook投稿の設定が不足しているため、送信しません。")
    except MetaGraphRefused as exc:
        return _flow(False, record, exc.detail)

    begun, reason = begin_notes_facebook_create(record, now)
    if reason:
        return _flow(False, record, reason)
    try:
        claimed = store["update_if_status"](
            client,
            record["id"],
            tuple(FACEBOOK_SEND_STATUSES),
            begun["fields"],
        )
    except Exception:
        return _flow(False, record, "送信開始を保存できなかったため、Facebookへは送っていません。")
    if not claimed:
        return _flow(False, record, "他の操作が先に状態を変えたため、送信しません。")
    outgoing = dict(claimed)
    outgoing["body"] = record.get("body")
    outgoing["link_url"] = record.get("link_url")
    outgoing["image_url"] = record.get("image_url")
    try:
        event = dict(begun["event"])
        event["actor_staff_id"] = staff_id or None
        store["insert_event"](client, claimed["id"], event)
    except Exception:
        return _flow(
            False,
            claimed,
            "送信開始の記録に失敗したため、Facebookへは送っていません。再送せず、結果を確認してください。",
        )
    try:
        http_status, response = post_exchange(url, access_token=access_token, body=payload)
        timed_out = False
    except MetaGraphTimeout:
        http_status, response, timed_out = None, {}, True
    except Exception:
        print("Facebook投稿 error=Exception")
        http_status, response, timed_out = None, {}, True
    finished = finish_notes_facebook_create(
        outgoing,
        http_status=http_status,
        body=response,
        timed_out=timed_out,
        now=now,
    )
    _log_facebook_outcome(http_status, finished)
    return _store_outcome(client, outgoing, finished, now, staff_id=staff_id, post_store=store)


def facebook_feed_exchange(url, *, access_token, body, timeout=FEED_TIMEOUT_SECONDS):
    """トークンはヘッダーだけ。クエリにも本文にも入れない。"""
    token = (access_token or "").strip()
    if not token:
        raise MetaGraphRefused("Facebook投稿の設定が不足しているため、送信しません。")
    if "access_token=" in (url or "").lower():
        raise MetaGraphRefused("送信先が不正なため、Facebookへは送りません。")
    try:
        response = requests.post(
            url,
            data=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.Timeout:
        raise MetaGraphTimeout() from None
    except requests.RequestException:
        raise MetaGraphTimeout() from None
    parsed = {}
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return response.status_code, parsed


def _require_https_link(value):
    text = (value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        return ""
    return text


def _facebook_post_id(body):
    if not isinstance(body, dict):
        return None
    value = body.get("id")
    if isinstance(value, str) and _POST_ID.fullmatch(value.strip()):
        return value.strip()
    return None


def _facebook_error_text(body, http_status):
    raw = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        raw = body["error"].get("message") or ""
    cleaned = sanitize_meta_error_message(raw) if raw else None
    if cleaned:
        return f"投稿失敗 HTTP {http_status} {cleaned}".strip()
    return f"投稿失敗 HTTP {http_status}"


def _log_facebook_outcome(http_status, finished):
    fields = (finished or {}).get("fields") or {}
    status = fields.get("status") or ""
    error_message = sanitize_meta_error_message(fields.get("error_message") or "")
    parts = [f"Facebook投稿 HTTP {http_status}", f"status={status}"]
    if error_message:
        parts.append(f"error_message={error_message}")
    print(" ".join(parts))


def _outcome(record, *, status, error_message, event, detail, now, external_id=None, posted_at=None):
    return {
        "fields": {
            "status": status,
            "external_id": external_id,
            "posted_at": posted_at,
            "error_message": error_message,
            "updated_at": now,
        },
        "event": {
            "event": event,
            "body_snapshot": record.get("body") or "",
            "link_url": record.get("link_url") or None,
            "image_url": record.get("image_url") or None,
            "detail": detail,
            "created_at": now,
        },
    }


def _flow(ok, record, message):
    return {"ok": ok, "record": record, "message": message}


def _post_store(store):
    if store:
        return store
    import external_posts

    return {
        "update_if_status": external_posts.update_notes_post_if_status,
        "insert_event": external_posts.insert_post_event,
    }


def _store_outcome(client, record, outcome, now, from_statuses=("posting",), staff_id=None, post_store=None):
    store = _post_store(post_store)
    event = dict(outcome["event"])
    event["actor_staff_id"] = staff_id or None
    try:
        saved = store["update_if_status"](
            client, record["id"], from_statuses, outcome["fields"]
        )
    except Exception:
        return _flow(False, record, "通信後に状態を保存できませんでした。自動では再送しません。結果を確認してください。")
    if not saved:
        return _flow(False, record, "通信後に状態を保存できませんでした。自動では再送しません。結果を確認してください。")
    try:
        store["insert_event"](client, saved["id"], event)
    except Exception:
        return _flow(True, saved, "状態は保存しました。履歴の記録に失敗しました。自動では再送しません。")
    status = saved.get("status")
    if status == "posted":
        message = "投稿成功を確認しました。"
    elif status == "unknown":
        message = "結果不明。自動再送しません。"
    elif status == "failed":
        message = saved.get("error_message") or "投稿に失敗しました。自動では再送しません。"
    else:
        message = "状態を保存しました。自動では再送しません。"
    return _flow(status == "posted", saved, message)
