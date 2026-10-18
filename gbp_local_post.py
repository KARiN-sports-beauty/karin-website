"""Google Business Profile のローカル投稿。

作成・更新・取得のリクエストを組み立て、応答から状態を決める。
このモジュールを読み込んだだけでは Google へ送信しない。
削除は扱わない。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

LOCAL_POSTS_URL = "https://mybusiness.googleapis.com/v4/{parent}/localPosts"
LOCAL_POST_URL = "https://mybusiness.googleapis.com/v4/{name}"
SUMMARY_LIMIT = 1500
TOPIC_TYPE = "STANDARD"
LANGUAGE_CODE = "ja"
CTA_TYPE = "LEARN_MORE"

_ACCOUNT_NAME = re.compile(r"^accounts/[A-Za-z0-9_-]+$")
_LOCATION_NAME = re.compile(r"^locations/[A-Za-z0-9_-]+$")
_POST_NAME = re.compile(
    r"^accounts/[A-Za-z0-9_-]+/locations/[A-Za-z0-9_-]+/localPosts/[A-Za-z0-9_-]+$"
)

FUKUOKA_TRIAL_SUMMARY = (
    "KARiN.の投稿接続を確認するための試験です。"
    "福岡（薬院）の出張施術について、詳しくはウェブサイトをご覧ください。"
)
FUKUOKA_TRIAL_URL = "https://karin-sb.jp/"


class GbpPostTimeout(Exception):
    """応答がなく、作成されたかどうかが分からない。"""


class GbpPostRefused(Exception):
    """送信しない。detail に秘密情報は入れない。"""

    def __init__(self, detail):
        self.detail = detail
        super().__init__(detail)


def build_standard_post(body, link_url, image_url=""):
    """STANDARD 投稿のペイロード。不合格なら payload は None。"""
    errors = []
    summary = (body or "").replace("\r\n", "\n").strip()
    if not summary:
        errors.append("投稿文を入力してください")
    elif len(summary) > SUMMARY_LIMIT:
        errors.append(f"投稿文は{SUMMARY_LIMIT}文字以内にしてください")
    url = (link_url or "").strip()
    if not url.startswith("https://") or " " in url:
        errors.append("リンク先は https のURLにしてください")
    image = (image_url or "").strip()
    if image and not image.startswith("https://"):
        errors.append("画像を添える場合は、公開された https のURLにしてください")
    if errors:
        return {"ok": False, "errors": errors, "payload": None}
    payload = {
        "languageCode": LANGUAGE_CODE,
        "summary": summary,
        "topicType": TOPIC_TYPE,
        "callToAction": {"actionType": CTA_TYPE, "url": url},
    }
    return {"ok": True, "errors": [], "payload": payload}


def build_fukuoka_trial_payload():
    """福岡向け試験投稿。組み立てるだけで送信しない。"""
    return build_standard_post(FUKUOKA_TRIAL_SUMMARY, FUKUOKA_TRIAL_URL)


def payload_text(payload):
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def require_single_account(accounts):
    """1件と確認できたアカウント名だけ返す。それ以外は送信しない。"""
    if not isinstance(accounts, list) or len(accounts) != 1 or not isinstance(accounts[0], dict):
        raise GbpPostRefused("アカウントが1件であることを確認できないため、送信しません")
    name = accounts[0].get("name")
    if not isinstance(name, str) or not _ACCOUNT_NAME.fullmatch(name):
        raise GbpPostRefused("アカウントが1件であることを確認できないため、送信しません")
    return name


def location_parent(account_name, location_name):
    if not _ACCOUNT_NAME.fullmatch(account_name or ""):
        raise GbpPostRefused("アカウント名が不正なため、送信しません")
    if not _LOCATION_NAME.fullmatch(location_name or ""):
        raise GbpPostRefused("ロケーション名が不正なため、送信しません")
    location_id = location_name.split("/", 1)[1]
    return f"{account_name}/locations/{location_id}"


def plan_request(record, account_name):
    """POST か PATCH のリクエスト。通信はしない。external_id がある場合は PATCH。"""
    built = build_standard_post(
        record.get("body"),
        record.get("link_url"),
        record.get("image_url") or "",
    )
    if not built["ok"]:
        raise GbpPostRefused(built["errors"][0])
    parent = location_parent(account_name, record.get("location_name"))
    external_id = (record.get("external_id") or "").strip()
    if external_id:
        if not external_id.startswith(parent + "/localPosts/"):
            raise GbpPostRefused("保存済みの投稿IDがこのロケーションの投稿ではないため、送信しません")
        if not _POST_NAME.fullmatch(external_id):
            raise GbpPostRefused("保存済みの投稿IDが不正なため、送信しません")
        return {
            "method": "PATCH",
            "url": LOCAL_POST_URL.format(name=external_id) + "?updateMask=summary,callToAction",
            "body": built["payload"],
            "parent": parent,
        }
    return {
        "method": "POST",
        "url": LOCAL_POSTS_URL.format(parent=parent),
        "body": built["payload"],
        "parent": parent,
    }


def get_request(external_id):
    if not _POST_NAME.fullmatch(external_id or ""):
        raise GbpPostRefused("確認する投稿IDが不正なため、取得しません")
    return {"method": "GET", "url": LOCAL_POST_URL.format(name=external_id), "body": None}


def begin_notes_gbp_submit(record, now):
    """送信開始。ready だけが新規POST、external_id 付きの ready は PATCH。"""
    if not record or not record.get("id"):
        return None, "保存して確認してから送信します。"
    status = record.get("status")
    if status == "unknown":
        return None, "結果が未確認です。再送せず、Google側の投稿を確認してください。"
    if status == "posting":
        return None, "送信中です。重なって送信しません。"
    external_id = (record.get("external_id") or "").strip()
    if status != "ready":
        return None, "確認済みの内容だけ送信できます。"
    fields = {
        "status": "posting",
        "external_id": external_id or None,
        "posted_at": record.get("posted_at") or None,
        "error_message": None,
        "updated_at": now,
    }
    event = {
        "event": "submit_started",
        "body_snapshot": record.get("body") or "",
        "link_url": record.get("link_url") or None,
        "image_url": record.get("image_url") or None,
        "detail": "送信を開始しました。成功を確認するまで投稿済にはしません。",
        "created_at": now,
    }
    return {"fields": fields, "event": event}, None


def finish_notes_gbp_submit(record, *, http_status, body, timed_out, now, parent):
    """応答から状態を決める。成功の name がない限り posted にしない。"""
    external_id = (record.get("external_id") or "").strip() or None
    posted_at = record.get("posted_at") or None
    if timed_out or http_status is None or http_status >= 500:
        return _outcome(
            record,
            status="unknown",
            external_id=external_id,
            posted_at=posted_at,
            error_message="結果不明。自動再送しません。",
            event="unknown",
            detail="結果不明。自動再送しません。Google側の投稿を確認してください。",
            now=now,
        )
    if http_status == 200 and isinstance(body, dict):
        name = body.get("name") if isinstance(body.get("name"), str) else ""
        if _POST_NAME.fullmatch(name) and name.startswith(parent + "/localPosts/"):
            summary = body.get("summary") if isinstance(body.get("summary"), str) else ""
            expected = (record.get("body") or "").replace("\r\n", "\n").strip()
            if summary != expected:
                return _outcome(
                    record,
                    status="unknown",
                    external_id=external_id,
                    posted_at=posted_at,
                    error_message="応答の本文が送信内容と一致しません。",
                    event="unknown",
                    detail="応答の本文が送信内容と一致しないため、投稿済にしていません。",
                    now=now,
                )
            return _outcome(
                record,
                status="posted",
                external_id=name,
                posted_at=now,
                error_message=None,
                event="succeeded",
                detail="投稿成功を確認しました。",
                now=now,
            )
        return _outcome(
            record,
            status="unknown",
            external_id=external_id,
            posted_at=posted_at,
            error_message="応答にこのロケーションの投稿IDがありません。",
            event="unknown",
            detail="投稿IDを確認できないため、投稿済にしていません。",
            now=now,
        )
    code = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = str(body["error"].get("status") or "")[:80]
    return _outcome(
        record,
        status="failed",
        external_id=external_id,
        posted_at=posted_at,
        error_message=f"投稿失敗 HTTP {http_status} {code}".strip(),
        event="failed",
        detail=f"投稿失敗 HTTP {http_status} {code}".strip(),
        now=now,
    )


def execute_notes_gbp_submit(record, account_name, exchange, now):
    """テスト用の1回送信。exchange が Timeout を出しても再送しない。"""
    begun, reason = begin_notes_gbp_submit(record, now)
    if reason:
        return None, reason
    inflight = dict(record)
    inflight.update(begun["fields"])
    request = plan_request(inflight, account_name)
    try:
        http_status, response = exchange(request["method"], request["url"], body=request["body"])
        timed_out = False
    except GbpPostTimeout:
        http_status, response, timed_out = None, {}, True
    finished = finish_notes_gbp_submit(
        inflight,
        http_status=http_status,
        body=response,
        timed_out=timed_out,
        now=now,
        parent=request["parent"],
    )
    finished["events"] = [begun["event"], finished["event"]]
    return finished, None


def reconcile_unknown(record, listed_posts, *, submitted_summary, submitted_at, parent):
    """unknown または送信中の記録を、一覧から確認する。古い投稿は採用しない。再送しない。"""
    if not record or record.get("status") not in {"unknown", "posting"}:
        raise GbpPostRefused("成否未確認、または送信中の記録だけ確認します。")
    expected = (submitted_summary or "").strip()
    started = _parse_time(submitted_at)
    if not expected or started is None:
        raise GbpPostRefused("送信時の本文と時刻がないため、確認できません。")
    existing_name = (record.get("external_id") or "").strip()
    if existing_name:
        return _outcome(
            record,
            status="unknown",
            external_id=existing_name,
            posted_at=record.get("posted_at") or None,
            error_message="既存の投稿IDがあるため、一覧からは確定しません。",
            event="unknown",
            detail="既存の投稿IDは残しています。その投稿を取得して確認してください。",
            now=submitted_at,
        )
    candidates = []
    unreadable = False
    for item in listed_posts or []:
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), str) else ""
        name = item.get("name") if isinstance(item.get("name"), str) else ""
        if summary != expected or not name.startswith(parent + "/localPosts/"):
            continue
        created = _parse_time(item.get("createTime"))
        if created is None:
            unreadable = True
            continue
        if created >= started:
            candidates.append(name)
    if unreadable or len(candidates) > 1:
        return _outcome(
            record,
            status="unknown",
            external_id=(record.get("external_id") or "").strip() or None,
            posted_at=record.get("posted_at") or None,
            error_message="確認できない投稿があるため、自動では確定しません。",
            event="unknown",
            detail="一覧だけでは確定できないため、投稿済にしていません。",
            now=submitted_at,
        )
    if len(candidates) == 1:
        return {
            "fields": {
                "status": "unknown",
                "external_id": candidates[0],
                "posted_at": record.get("posted_at") or None,
                "error_message": "候補は1件です。取得して本文が一致するまで投稿済にしません。",
                "updated_at": submitted_at,
            },
            "event": {
                "event": "unknown",
                "body_snapshot": expected,
                "detail": "候補の投稿IDを保持しました。取得確認前なので投稿済にしていません。",
                "created_at": submitted_at,
            },
            "candidate_name": candidates[0],
        }
    return _outcome(
        record,
        status="failed",
        external_id=None,
        posted_at=None,
        error_message="送信後に作成された投稿は見つかりませんでした。",
        event="failed",
        detail="作成された投稿は見つかりませんでした。自動では再送しません。",
        now=submitted_at,
    )


POSTING_HOLD_SECONDS = 120


def google_exchange(method, url, *, access_token, body=None, timeout=20):
    """POST / PATCH / GET を1回送る。失敗しても再送しない。認証情報は残さない。"""
    if method not in {"POST", "PATCH", "GET"}:
        raise GbpPostRefused("この操作は送信しません")
    import requests

    headers = {"Authorization": f"Bearer {access_token}"}
    kwargs = {"headers": headers, "timeout": timeout}
    if body is not None:
        headers["Content-Type"] = "application/json"
        kwargs["json"] = body
    try:
        response = requests.request(method, url, **kwargs)
    except requests.RequestException:
        raise GbpPostTimeout()
    try:
        parsed = response.json()
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    return response.status_code, parsed


def local_post_list_request(parent):
    return {"method": "GET", "url": LOCAL_POSTS_URL.format(parent=parent) + "?pageSize=100", "body": None}


def read_local_post_page(body):
    posts = body.get("localPosts") if isinstance(body, dict) else None
    if not isinstance(posts, list):
        posts = []
    incomplete = bool(isinstance(body, dict) and body.get("nextPageToken"))
    return posts, incomplete


def latest_submit_marker(record, events):
    """直近の送信開始。履歴がなければ、その行の本文と更新時刻を使う。"""
    for event in events or []:
        if event.get("event") == "submit_started" and event.get("created_at"):
            summary = event.get("body_snapshot") or record.get("body") or ""
            return summary, event.get("created_at")
    return record.get("body") or "", record.get("updated_at")


def perform_notes_gbp_send(client, record, *, config, token_exchange, post_exchange, now, staff_id=None):
    """ready を posting にしてから1回だけ送る。条件付き更新に失敗したら送らない。"""
    import external_posts
    import gbp_read

    refused = _prepare_send(record, config)
    if refused:
        return _flow(False, record, refused)
    _begun, reason = begin_notes_gbp_submit(record, now)
    if reason:
        return _flow(False, record, reason)
    try:
        account_name, location_name, access_token = _account_and_location(record, config, token_exchange)
    except (GbpPostRefused, gbp_read.GbpReadError) as exc:
        return _flow(False, record, exc.detail)
    try:
        claimed = external_posts.update_notes_post_if_status(
            client,
            record["id"],
            ("ready",),
            {"status": "posting", "error_message": None, "updated_at": now},
        )
    except Exception:
        return _flow(False, record, "送信開始を保存できなかったため、Googleへは送っていません。")
    if not claimed:
        return _flow(False, record, "他の操作が先に状態を変えたため、送信しません。")
    outgoing = dict(claimed)
    outgoing["location_name"] = location_name
    try:
        external_posts.insert_post_event(client, claimed["id"], _started_event(outgoing, staff_id, now))
    except Exception:
        return _flow(False, claimed, "送信開始の記録に失敗したため、Googleへは送っていません。再送せず、結果を確認してください。")
    try:
        request = plan_request(outgoing, account_name)
    except GbpPostRefused as exc:
        return _store_outcome(client, outgoing, _local_failure(outgoing, exc.detail, now), now, staff_id=staff_id)
    if outgoing.get("external_id") and request["method"] != "PATCH":
        return _store_outcome(
            client, outgoing, _local_failure(outgoing, "投稿IDがあるため、新規投稿はしません。", now), now, staff_id=staff_id
        )
    try:
        http_status, response = post_exchange(
            request["method"], request["url"], body=request["body"], access_token=access_token
        )
        timed_out = False
    except GbpPostTimeout:
        http_status, response, timed_out = None, {}, True
    except Exception:
        http_status, response, timed_out = None, {}, True
    finished = finish_notes_gbp_submit(
        outgoing,
        http_status=http_status,
        body=response,
        timed_out=timed_out,
        now=now,
        parent=request["parent"],
    )
    return _store_outcome(client, outgoing, finished, now, staff_id=staff_id)


def perform_notes_gbp_check(client, record, *, config, token_exchange, post_exchange, now, events=None, staff_id=None):
    """unknown または送信中を GET で確認する。新規投稿は作らない。"""
    import gbp_read

    if not record or record.get("status") not in {"unknown", "posting"}:
        return _flow(False, record, "成否未確認、または送信中の記録だけ確認します。")
    try:
        account_name, location_name, access_token = _account_and_location(record, config, token_exchange)
    except (GbpPostRefused, gbp_read.GbpReadError) as exc:
        return _flow(False, record, exc.detail)
    parent = location_parent(account_name, location_name)
    summary, submitted_at = latest_submit_marker(record, events)
    external_id = (record.get("external_id") or "").strip()
    try:
        if external_id:
            request = get_request(external_id)
            http_status, response = _call_exchange(
                post_exchange, request["method"], request["url"], access_token
            )
            if http_status != 200:
                outcome = _outcome(
                    record,
                    status="unknown",
                    external_id=external_id,
                    posted_at=record.get("posted_at") or None,
                    error_message="投稿の取得で確認できませんでした。",
                    event="unknown",
                    detail="投稿の取得で確認できませんでした。新規投稿はしていません。",
                    now=now,
                )
            else:
                outcome = confirm_fetched_post(record, response, summary, now)
        else:
            request = local_post_list_request(parent)
            http_status, response = _call_exchange(
                post_exchange, request["method"], request["url"], access_token
            )
            if http_status != 200:
                return _flow(False, record, "投稿一覧を取得できなかったため、状態は変えていません。")
            posts, incomplete = read_local_post_page(response)
            if incomplete:
                outcome = _outcome(
                    record,
                    status="unknown",
                    external_id=None,
                    posted_at=record.get("posted_at") or None,
                    error_message="投稿一覧が途中までしか取得できないため、確定しません。",
                    event="unknown",
                    detail="投稿一覧が途中までしか取得できないため、投稿済にしていません。",
                    now=now,
                )
            else:
                outcome = reconcile_unknown(
                    record,
                    posts,
                    submitted_summary=summary,
                    submitted_at=submitted_at,
                    parent=parent,
                )
                if outcome["fields"]["status"] == "failed" and _posting_hold(record.get("status"), submitted_at, now):
                    return _flow(False, record, "送信中のため、見つからなくても失敗にはしません。自動では再送しません。")
                candidate = outcome.get("candidate_name")
                if candidate:
                    fetched = get_request(candidate)
                    get_status, get_body = _call_exchange(post_exchange, fetched["method"], fetched["url"], access_token)
                    provisional = dict(record)
                    provisional["status"] = "unknown"
                    provisional["external_id"] = candidate
                    if get_status != 200:
                        keep_name = candidate if get_status >= 500 else None
                        outcome = _outcome(
                            provisional,
                            status="unknown",
                            external_id=keep_name,
                            posted_at=record.get("posted_at") or None,
                            error_message="候補の投稿を取得できなかったため、投稿済にしていません。",
                            event="unknown",
                            detail="取得できるまで投稿済にしません。新規投稿はしていません。",
                            now=now,
                        )
                    else:
                        outcome = confirm_fetched_post(provisional, get_body, summary, now)
                        if outcome["fields"]["status"] != "posted":
                            outcome["fields"]["external_id"] = None
    except GbpPostTimeout:
        return _flow(False, record, "確認の通信結果が不明です。自動では再送しません。")
    except GbpPostRefused as exc:
        return _flow(False, record, exc.detail)
    return _store_outcome(client, record, outcome, now, from_statuses=("posting", "unknown"), staff_id=staff_id)


def _prepare_send(record, config):
    if not record or not record.get("id"):
        return "保存して確認してから送信します。"
    if record.get("gbp_profile") not in {"tokyo", "fukuoka"}:
        return "東京か福岡の投稿だけ送信できます。"
    if record.get("status") != "ready":
        if record.get("status") in {"unknown", "posting"}:
            return "結果が未確認です。再送せず、Google側の投稿を確認してください。"
        return "確認済みの内容だけ送信できます。"
    built = build_standard_post(record.get("body"), record.get("link_url"), record.get("image_url") or "")
    if not built["ok"]:
        return built["errors"][0]
    return None


def _account_and_location(record, config, token_exchange):
    import gbp_read

    problems = gbp_read.location_config_error(config)
    profile = record.get("gbp_profile")
    if profile in problems:
        raise GbpPostRefused(problems[profile].detail)
    location_name = (config.get("locations") or {}).get(profile) or ""
    token = gbp_read.fetch_access_token(config, token_exchange)
    listed = gbp_read.list_accounts(token_exchange, token)
    if listed.get("has_more"):
        raise GbpPostRefused("アカウントが1件であることを確認できないため、送信しません")
    account_name = require_single_account(listed.get("accounts"))
    return account_name, location_name, token


def _call_exchange(post_exchange, method, url, access_token, body=None):
    return post_exchange(method, url, body=body, access_token=access_token)


def _started_event(record, staff_id, now):
    return {
        "event": "submit_started",
        "body_snapshot": (record.get("body") or "").replace("\r\n", "\n").strip(),
        "link_url": record.get("link_url") or None,
        "image_url": record.get("image_url") or None,
        "detail": "送信を開始しました。成功を確認するまで投稿済にはしません。",
        "actor_staff_id": staff_id or None,
        "created_at": now,
    }


def _local_failure(record, detail, now):
    return _outcome(
        record,
        status="failed",
        external_id=(record.get("external_id") or "").strip() or None,
        posted_at=record.get("posted_at") or None,
        error_message=detail,
        event="failed",
        detail=detail + " Googleへは送っていません。",
        now=now,
    )


def _store_outcome(client, record, outcome, now, from_statuses=("posting",), staff_id=None):
    import external_posts

    event = dict(outcome["event"])
    event["actor_staff_id"] = staff_id or None
    try:
        saved = external_posts.update_notes_post_if_status(
            client, record["id"], from_statuses, outcome["fields"]
        )
    except Exception:
        return _flow(False, record, "通信後に状態を保存できませんでした。自動では再送しません。結果を確認してください。")
    if not saved:
        return _flow(False, record, "通信後に状態を保存できませんでした。自動では再送しません。結果を確認してください。")
    try:
        external_posts.insert_post_event(client, saved["id"], event)
    except Exception:
        return _flow(True, saved, "状態は保存しました。履歴の記録に失敗しました。自動では再送しません。")
    status = saved.get("status")
    if status == "posted":
        message = "投稿成功を確認しました。"
    elif status == "unknown":
        message = "結果が未確認です。自動では再送しません。Google側の投稿を確認してください。"
    elif status == "failed":
        message = saved.get("error_message") or "投稿に失敗しました。自動では再送しません。"
    else:
        message = "状態を保存しました。自動では再送しません。"
    return _flow(status == "posted", saved, message)


def _flow(ok, record, message):
    return {"ok": ok, "record": record, "message": message}


def _posting_hold(status, submitted_at, now):
    if status != "posting":
        return False
    started = _parse_time(submitted_at)
    current = _parse_time(now)
    if started is None or current is None:
        return True
    return (current - started).total_seconds() < POSTING_HOLD_SECONDS


def confirm_fetched_post(record, post_body, submitted_summary, now):
    """GET の結果が送信内容と一致したときだけ posted にする。"""
    if not record or record.get("status") not in {"unknown", "posting"}:
        raise GbpPostRefused("成否未確認、または送信中の記録だけ確定します。")
    expected_name = (record.get("external_id") or "").strip()
    name = post_body.get("name") if isinstance(post_body, dict) else ""
    summary = post_body.get("summary") if isinstance(post_body, dict) else ""
    expected_summary = (submitted_summary or "").replace("\r\n", "\n").strip()
    if name != expected_name or summary != expected_summary or not _POST_NAME.fullmatch(name or ""):
        return _outcome(
            record,
            status="unknown",
            external_id=expected_name or None,
            posted_at=record.get("posted_at") or None,
            error_message="取得した投稿が送信内容と一致しません。",
            event="unknown",
            detail="取得した投稿が送信内容と一致しないため、投稿済にしていません。",
            now=now,
        )
    return _outcome(
        record,
        status="posted",
        external_id=name,
        posted_at=now,
        error_message=None,
        event="succeeded",
        detail="取得した投稿が送信内容と一致したため、投稿成功にしました。",
        now=now,
    )


def _outcome(record, *, status, external_id, posted_at, error_message, event, detail, now):
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


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
