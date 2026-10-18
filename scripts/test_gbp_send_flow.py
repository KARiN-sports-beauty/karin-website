#!/usr/bin/env python3
"""GBPの送信と結果確認。Googleへは送らない。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gbp_local_post
from gbp_local_post import GbpPostRefused, GbpPostTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-01T10:00:00+09:00"
LATER = "2026-11-01T10:05:00+09:00"
EARLIER = "2026-11-01T09:00:00+09:00"
ACCOUNT = "accounts/111554120993304611204"
FUKUOKA = "locations/9653834603317620900"
TOKYO = "locations/8877844916727282076"
PARENT = f"{ACCOUNT}/locations/{FUKUOKA.split('/')[1]}"
CREATED = f"{PARENT}/localPosts/created1"
OLD_TOKYO = f"{ACCOUNT}/locations/{TOKYO.split('/')[1]}/localPosts/existing1"
TOKEN = "access-secret"
REFRESH = "refresh-secret"


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, db):
        self.db = db
        self.filters = []
        self.op = None
        self.payload = None

    def update(self, fields):
        self.op = "update"
        self.payload = dict(fields)
        return self

    def insert(self, fields):
        self.op = "insert"
        self.payload = dict(fields)
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def in_(self, key, values):
        self.filters.append(("in", key, list(values)))
        return self

    def execute(self):
        if self.op == "insert":
            self.db.event_attempts += 1
            if self.db.fail_event_at and self.db.event_attempts == self.db.fail_event_at:
                raise RuntimeError("event failed")
            self.db.events.append(dict(self.payload))
            return Result([dict(self.payload)])
        if self.op != "update":
            raise AssertionError(self.op)
        for kind, key, value in self.filters:
            current = self.db.row.get(key)
            if kind == "eq" and current != value:
                return Result([])
            if kind == "in" and current not in value:
                return Result([])
        if self.db.fail_update_after is not None and self.db.update_count >= self.db.fail_update_after:
            raise RuntimeError("update failed")
        self.db.row.update(self.payload)
        self.db.update_count += 1
        self.db.updates.append(dict(self.payload))
        return Result([dict(self.db.row)])


class FakeDB:
    def __init__(self, row):
        self.row = dict(row)
        self.events = []
        self.updates = []
        self.update_count = 0
        self.event_attempts = 0
        self.fail_update_after = None
        self.fail_event_at = 0

    def table(self, name):
        return Query(self)


class Http:
    def __init__(self, mode="ok", posts=None, summary="本文"):
        self.mode = mode
        self.posts = posts or []
        self.summary = summary
        self.calls = []

    def __call__(self, method, url, body=None, access_token=None):
        self.calls.append({"method": method, "url": url})
        if access_token != TOKEN or TOKEN in url or REFRESH in url:
            raise AssertionError("secret in request")
        if method not in {"POST", "PATCH", "GET"}:
            raise AssertionError(method)
        if self.mode == "timeout":
            raise GbpPostTimeout()
        if self.mode == "boom":
            raise RuntimeError("socket")
        if self.mode == "server":
            return 503, {"error": {"status": "UNAVAILABLE"}}
        if self.mode == "denied":
            return 404, {"error": {"status": "NOT_FOUND"}}
        if "pageSize=" in url:
            return 200, {"localPosts": self.posts}
        if method == "GET":
            name = url.split("/v4/", 1)[1]
            return 200, {"name": name, "summary": self.summary}
        name = CREATED if method == "POST" else url.split("/v4/", 1)[1].split("?", 1)[0]
        return 200, {"name": name, "summary": body["summary"]}


def config():
    return {
        "client_id": "client",
        "client_secret": "client-secret",
        "refresh_token": REFRESH,
        "locations": {"tokyo": TOKYO, "fukuoka": FUKUOKA},
    }


def token_exchange(accounts=None, more=False):
    def exchange(method, url, headers=None, body=None):
        if "oauth2.googleapis.com" in url:
            return 200, {"access_token": TOKEN}
        payload = {"accounts": accounts if accounts is not None else [{"name": ACCOUNT, "type": "PERSONAL"}]}
        if more:
            payload["nextPageToken"] = "next"
        return 200, payload
    return exchange


def ready(**extra):
    record = {
        "id": "row-1",
        "status": "ready",
        "gbp_profile": "fukuoka",
        "body": "本文",
        "link_url": "https://karin-sb.jp/blog/kata",
        "image_url": "",
        "external_id": None,
        "posted_at": None,
        "updated_at": EARLIER,
    }
    record.update(extra)
    return record


def send(db, http, record=None, accounts=None, more=False, now=NOW):
    return gbp_local_post.perform_notes_gbp_send(
        db,
        record or ready(),
        config=config(),
        token_exchange=token_exchange(accounts, more),
        post_exchange=http,
        now=now,
        staff_id="staff-1",
    )


def check(db, http, record, events, now=LATER):
    return gbp_local_post.perform_notes_gbp_check(
        db,
        record,
        config=config(),
        token_exchange=token_exchange(),
        post_exchange=http,
        now=now,
        events=events,
        staff_id="staff-1",
    )


def secret_free(result):
    text = str(result["message"])
    return TOKEN not in text and REFRESH not in text and "client-secret" not in text


def main():
    http = Http()
    db = FakeDB(ready())
    created = send(db, http)
    report(created["ok"] and db.row["status"] == "posted", "新規投稿の成功後だけ投稿済", created["message"])
    report(db.row["external_id"] == CREATED and db.row["posted_at"] == NOW, "投稿IDと投稿日時を保存する")
    report(http.calls[0]["method"] == "POST" and db.updates[0]["status"] == "posting", "送る前に送信中を保存する")
    report(secret_free(created), "成功結果に認証情報を出さない")

    again = Http()
    blocked = send(db, again, record=dict(db.row))
    report(not blocked["ok"] and again.calls == [], "投稿済のままでは再送しない", blocked["message"])

    updated_row = ready(external_id=CREATED, posted_at=EARLIER)
    patch_http = Http()
    patch_db = FakeDB(updated_row)
    patched = send(patch_db, patch_http)
    report(patched["ok"] and patch_http.calls[0]["method"] == "PATCH", "投稿IDがあるときはPATCH", patched["message"])
    report(all(call["method"] != "POST" for call in patch_http.calls), "PATCHが失敗してもPOSTに戻さない")

    lost = Http("denied")
    lost_db = FakeDB(ready(external_id=CREATED))
    denied = send(lost_db, lost)
    report(lost_db.row["status"] == "failed" and lost_db.row["external_id"] == CREATED, "更新の404でも投稿IDを残す")
    lost_db.row["status"] = "ready"
    retry = Http()
    send(lost_db, retry, record=dict(lost_db.row))
    report(retry.calls and retry.calls[0]["method"] == "PATCH", "失敗後に確認し直してもPATCHのまま")

    stale_db = FakeDB(ready(external_id=CREATED))
    stale_http = Http()
    send(stale_db, stale_http, record=ready())
    report(stale_http.calls[0]["method"] == "PATCH", "画面側の記録が古くてもDBの投稿IDでPATCHする")

    timed = Http("timeout")
    timed_db = FakeDB(ready())
    unknown = send(timed_db, timed)
    report(timed_db.row["status"] == "unknown" and not unknown["ok"], "タイムアウトは成否不明")
    report(len(timed.calls) == 1, "タイムアウトでは1回しか送らない")
    second = Http()
    send(timed_db, second, record=dict(timed_db.row))
    report(second.calls == [], "成否不明からは自動再送しない")

    server = Http("server")
    server_db = FakeDB(ready(external_id=CREATED))
    send(server_db, server)
    report(server_db.row["status"] == "unknown" and server_db.row["external_id"] == CREATED, "5xxは成否不明で投稿IDを残す")

    boom = Http("boom")
    boom_db = FakeDB(ready())
    send(boom_db, boom)
    report(boom_db.row["status"] == "unknown" and len(boom.calls) == 1, "通信例外も1回で成否不明")

    shared = FakeDB(ready())
    shared_http = Http()
    first = send(shared, shared_http)
    stale = ready()
    second_click = send(shared, shared_http, record=stale)
    report(first["ok"] and not second_click["ok"] and len(shared_http.calls) == 1, "先に状態を変えた方だけ送る", second_click["message"])

    posting_db = FakeDB(ready(status="posting"))
    posting_http = Http()
    raced = send(posting_db, posting_http, record=ready())
    report(not raced["ok"] and posting_http.calls == [] and posting_db.row["status"] == "posting", "送信中の行には重ねて送らない")

    claim_db = FakeDB(ready())
    claim_db.fail_update_after = 0
    claim_http = Http()
    claim_failed = send(claim_db, claim_http)
    report(not claim_failed["ok"] and claim_http.calls == [] and claim_db.row["status"] == "ready", "送信開始の保存に失敗したら送らない")
    report(secret_free(claim_failed), "保存失敗の文言に認証情報を出さない")

    outcome_db = FakeDB(ready())
    outcome_db.fail_update_after = 1
    outcome_http = Http()
    outcome = send(outcome_db, outcome_http)
    report(not outcome["ok"] and len(outcome_http.calls) == 1 and outcome_db.row["status"] == "posting", "成功応答の保存に失敗しても再送しない")

    event_db = FakeDB(ready())
    event_db.fail_event_at = 1
    event_http = Http()
    event_failed = send(event_db, event_http)
    report(not event_failed["ok"] and event_http.calls == [] and event_db.row["status"] == "posting", "送信開始の履歴に失敗したら送らない")

    none_db = FakeDB(ready())
    none_http = Http()
    refused = send(none_db, none_http, accounts=[])
    report(not refused["ok"] and none_http.calls == [] and none_db.update_count == 0, "アカウント0件では送らない")
    two_http = Http()
    two = send(FakeDB(ready()), two_http, accounts=[{"name": ACCOUNT}, {"name": "accounts/2"}])
    report(not two["ok"] and two_http.calls == [], "アカウント2件では送らない")
    more_http = Http()
    more = send(FakeDB(ready()), more_http, more=True)
    report(not more["ok"] and more_http.calls == [], "続きがあるアカウント一覧では送らない")

    started = [{"event": "submit_started", "body_snapshot": "本文", "created_at": NOW}]
    none_found = Http(posts=[{"name": OLD_TOKYO, "summary": "本文", "createTime": "2026-10-01T00:00:00Z"}])
    none_row = FakeDB(ready(status="unknown", updated_at=NOW))
    missed = check(none_row, none_found, dict(none_row.row), started)
    report(missed["record"]["status"] == "failed" and all(call["method"] == "GET" for call in none_found.calls), "古い東京投稿は採用せず、新規POSTもしない")

    one = Http(posts=[{"name": CREATED, "summary": "本文", "createTime": "2026-11-01T01:00:02Z"}])
    one_row = FakeDB(ready(status="unknown", updated_at=NOW))
    found = check(one_row, one, dict(one_row.row), started)
    report(found["ok"] and one_row.row["status"] == "posted" and one_row.row["external_id"] == CREATED, "候補1件は取得一致のあと投稿済")
    report([call["method"] for call in one.calls] == ["GET", "GET"], "候補の確認はGETだけ")

    many = Http(posts=[
        {"name": CREATED, "summary": "本文", "createTime": "2026-11-01T01:00:02Z"},
        {"name": PARENT + "/localPosts/created2", "summary": "本文", "createTime": "2026-11-01T01:00:03Z"},
    ])
    many_row = FakeDB(ready(status="unknown", updated_at=NOW))
    ambiguous = check(many_row, many, dict(many_row.row), started)
    report(many_row.row["status"] == "unknown" and len(many.calls) == 1, "候補が複数なら確定しない", ambiguous["message"])

    known = Http()
    known_row = FakeDB(ready(status="unknown", external_id=CREATED))
    confirmed = check(known_row, known, dict(known_row.row), started)
    report(confirmed["ok"] and known.calls[0]["method"] == "GET" and "pageSize=" not in known.calls[0]["url"], "投稿IDがある確認は同じ投稿のGET")
    report(all(call["method"] != "POST" for call in known.calls), "確認で新規投稿しない")

    young = Http(posts=[])
    young_row = FakeDB(ready(status="posting", updated_at=NOW))
    held = check(young_row, young, dict(young_row.row), started, now=NOW)
    report(not held["ok"] and young_row.row["status"] == "posting", "送信直後に見つからなくても失敗にしない")

    old_events = [{"event": "submit_started", "body_snapshot": "本文", "created_at": EARLIER}]
    old = Http(posts=[])
    old_row = FakeDB(ready(status="posting", updated_at=EARLIER))
    aged = check(old_row, old, dict(old_row.row), old_events, now=NOW)
    report(old_row.row["status"] == "failed" and all(call["method"] == "GET" for call in old.calls), "送信から時間が経って見つからなければ失敗にする")

    import requests
    original = requests.request
    called = {"value": False}

    def boom(method, url, **kwargs):
        called["value"] = True
        raise requests.ConnectionError("boom")

    requests.request = boom
    try:
        raised = False
        try:
            gbp_local_post.google_exchange("POST", "https://example.invalid/post", access_token=TOKEN)
        except GbpPostTimeout:
            raised = True
        report(raised and called["value"], "実通信の失敗はタイムアウト扱いで再送しない")
        called["value"] = False
        blocked_delete = False
        try:
            gbp_local_post.google_exchange("DELETE", "https://example.invalid/post", access_token=TOKEN)
        except GbpPostRefused:
            blocked_delete = True
        report(blocked_delete and not called["value"], "削除は通信しない")
    finally:
        requests.request = original

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
