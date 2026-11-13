#!/usr/bin/env python3
"""KARiN.NOTES の Facebook 投稿。Meta API へは送らない。"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import meta_graph
from meta_graph import MetaGraphTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-13T15:00:00+09:00"
TOKEN = "EAAtestsecretvalue000000000000"
PAGE_TOKEN = "EAApageaccesssecretvalue0000000"
PAGE_ID = "61595470022494"
POST_ID = "61595470022494_111222333"


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
        self.db.row.update(self.payload)
        self.db.updates.append(dict(self.payload))
        return Result([dict(self.db.row)])


class FakeDB:
    def __init__(self, row):
        self.row = dict(row)
        self.events = []
        self.updates = []

    def table(self, name):
        return Query(self)


def _assert_no_secret(url, body=None):
    text = url or ""
    if TOKEN in text or PAGE_TOKEN in text:
        raise AssertionError("secret in url")
    if "access_token=" in text.lower():
        raise AssertionError("token query")
    if body and "access_token" in body:
        raise AssertionError("token in body")


class AccountsHttp:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []

    def __call__(self, url, *, access_token, params=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        _assert_no_secret(url)
        if access_token != TOKEN:
            raise AssertionError("unexpected system token")
        if self.mode == "timeout":
            raise MetaGraphTimeout()
        if self.mode == "denied":
            return 403, {"error": {"message": f"Bearer {TOKEN}", "code": 200}}
        if self.mode == "empty":
            return 200, {"data": []}
        if self.mode == "other_page":
            return 200, {"data": [{"id": "999999", "access_token": PAGE_TOKEN}]}
        if self.mode == "no_token":
            return 200, {"data": [{"id": PAGE_ID}]}
        if "/me/accounts" not in (url or ""):
            raise AssertionError("accounts url")
        return 200, {"data": [{"id": PAGE_ID, "access_token": PAGE_TOKEN}]}


class FeedHttp:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []
        self.last_body = None
        self.last_url = None
        self.last_token = None

    def __call__(self, url, *, access_token, body):
        self.calls.append({"url": url, "body": dict(body or {})})
        self.last_url = url
        self.last_body = body
        self.last_token = access_token
        _assert_no_secret(url, body)
        if access_token != PAGE_TOKEN:
            raise AssertionError("feed must use page token")
        if self.mode == "timeout":
            raise MetaGraphTimeout()
        if self.mode == "server":
            return 500, {"error": {"message": f"Bearer {PAGE_TOKEN}", "code": 1}}
        if self.mode == "denied":
            return 403, {"error": {"message": f"Invalid OAuth access token {PAGE_TOKEN}", "code": 190}}
        if self.mode == "noid":
            return 200, {"success": True}
        return 200, {"id": POST_ID}


def sample_record(**overrides):
    row = {
        "id": "fb-1",
        "source_kind": "notes_article",
        "blog_id": "12",
        "channel": "facebook",
        "gbp_profile": None,
        "status": "draft",
        "body": "KARiN.NOTESの記事です。",
        "link_url": "https://karin-sb.jp/blog/sample",
        "image_url": "/static/images/notes/a.jpg",
        "external_id": None,
        "posted_at": None,
        "error_message": None,
    }
    row.update(overrides)
    return row


def sample_config(**overrides):
    config = {"access_token": TOKEN, "page_id": PAGE_ID}
    config.update(overrides)
    return config


def secrets_absent(*texts):
    blob = "\n".join(text or "" for text in texts)
    return TOKEN not in blob and PAGE_TOKEN not in blob and "EAAtest" not in blob and "EAApage" not in blob


def run_create(record, http, config=None, get_http=None):
    db = FakeDB(record)
    accounts = get_http if get_http is not None else AccountsHttp("ok")
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        result = meta_graph.perform_notes_facebook_create(
            db,
            record,
            config=config or sample_config(),
            post_exchange=http,
            get_exchange=accounts,
            now=NOW,
            staff_id="staff-1",
        )
    log = stdout.getvalue()
    if not secrets_absent(log):
        raise AssertionError("secret in log")
    stored = " ".join(
        [
            str(db.row.get("error_message") or ""),
            " ".join(str(item.get("detail") or "") for item in db.events),
        ]
    )
    if not secrets_absent(stored):
        raise AssertionError("secret in db")
    return result, db, log, accounts


def main():
    preview = meta_graph.facebook_preview("本文", "https://karin-sb.jp/blog/a")
    report(preview["ok"] and "本文" in preview["payload_text"] and "https://karin-sb.jp/blog/a" in preview["payload_text"], "確認画面は本文とリンク")
    report("access_token" not in preview["payload_text"] and TOKEN not in preview["payload_text"], "確認画面にトークンを出さない")
    bad_link = meta_graph.facebook_preview("本文", "http://karin-sb.jp/blog/a")
    report(not bad_link["ok"], "httpリンクは送信確認できない")

    url = meta_graph.facebook_feed_url(PAGE_ID)
    report(
        url == f"https://graph.facebook.com/v27.0/{PAGE_ID}/feed" and "access_token" not in url,
        "投稿URLはv27.0でトークンを含まない",
        url,
    )

    missing = meta_graph.missing_facebook_env({"access_token": "", "page_id": ""})
    report(
        missing == ["FACEBOOK_SYSTEM_USER_ACCESS_TOKEN", "FACEBOOK_PAGE_ID"],
        "不足している環境変数名だけ返す",
        str(missing),
    )
    loaded = meta_graph.load_facebook_config(
        {
            "FACEBOOK_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FACEBOOK_PAGE_ID": PAGE_ID,
            "INSTAGRAM_BUSINESS_ACCOUNT_ID": "1784140000",
        }
    )
    report(
        loaded["page_id"] == PAGE_ID and "instagram" not in loaded and loaded["access_token"] == TOKEN,
        "Facebook設定はInstagramの値を使わない",
    )

    dirty = meta_graph.sanitize_meta_error_message(
        f"Invalid OAuth access token {TOKEN} https://graph.facebook.com/debug Bearer {TOKEN}"
    )
    report(
        dirty
        and TOKEN not in dirty
        and "https://" not in dirty
        and "Bearer" not in dirty
        and "[redacted]" in dirty,
        "エラー文からトークンとURLを除く",
        dirty or "",
    )

    picked = meta_graph.select_page_access_token(
        {"data": [{"id": "999", "access_token": PAGE_TOKEN}, {"id": PAGE_ID, "access_token": PAGE_TOKEN}]},
        PAGE_ID,
    )
    report(picked == PAGE_TOKEN, "対象ページIDのトークンだけ選ぶ")

    ok_http = FeedHttp("ok")
    ok_result, ok_db, ok_log, ok_accounts = run_create(sample_record(), ok_http)
    report(ok_result["ok"] and ok_db.row["status"] == "posted", "正常レスポンスで posted")
    report(ok_db.row["external_id"] == POST_ID and ok_db.row["posted_at"] == NOW, "投稿IDと投稿日時を保存")
    report(
        ok_http.last_body == {"message": "KARiN.NOTESの記事です。", "link": "https://karin-sb.jp/blog/sample"},
        "message と link だけ送る",
        str(ok_http.last_body),
    )
    report(
        ok_http.last_token == PAGE_TOKEN
        and len(ok_accounts.calls) == 1
        and ok_accounts.calls[0]["params"] == {"fields": "id,access_token"}
        and "/me/accounts" in ok_accounts.calls[0]["url"],
        "Page Access Token を使って feed にPOSTする",
    )
    report(secrets_absent(ok_log) and len(ok_http.calls) == 1, "成功時のログにトークンがない")
    events = [item.get("event") for item in ok_db.events]
    report(events == ["submit_started", "succeeded"], "成功時は開始と成功の履歴", str(events))

    denied_http = FeedHttp("denied")
    denied_result, denied_db, denied_log, _denied_acc = run_create(sample_record(), denied_http)
    report(not denied_result["ok"] and denied_db.row["status"] == "failed", "4xxで failed")
    report(denied_db.row.get("external_id") is None and denied_db.row.get("posted_at") is None, "失敗では投稿済にしない")
    report(secrets_absent(denied_db.row.get("error_message") or "", denied_log), "4xxの保存とログにトークンがない")

    server_http = FeedHttp("server")
    server_result, server_db, server_log, _server_acc = run_create(sample_record(), server_http)
    report(not server_result["ok"] and server_db.row["status"] == "unknown", "5xxで unknown")
    report("自動再送しません" in (server_result["message"] or ""), "5xxは自動再送しない")
    report(secrets_absent(server_log), "5xxのログにトークンがない")

    timeout_http = FeedHttp("timeout")
    timeout_result, timeout_db, _timeout_log, _timeout_acc = run_create(sample_record(), timeout_http)
    report(not timeout_result["ok"] and timeout_db.row["status"] == "unknown", "タイムアウトで unknown")
    report(timeout_db.row.get("external_id") is None, "タイムアウトでは投稿IDを書かない")

    noid_http = FeedHttp("noid")
    noid_result, noid_db, _noid_log, _noid_acc = run_create(sample_record(), noid_http)
    report(not noid_result["ok"] and noid_db.row["status"] == "unknown", "投稿IDがない200は unknown")

    mismatch_http = FeedHttp("ok")
    mismatch_acc = AccountsHttp("other_page")
    mismatch_result, mismatch_db, mismatch_log, _macc = run_create(
        sample_record(), mismatch_http, get_http=mismatch_acc
    )
    report(not mismatch_result["ok"] and mismatch_http.calls == [], "対象ページIDが違うときは投稿しない")
    report(mismatch_db.row["status"] == "failed", "対象ページ不一致は failed に記録する")
    report("FACEBOOK_PAGE_ID" in (mismatch_result["message"] or "") and secrets_absent(mismatch_log), "不一致の失敗文にトークンがない")

    denied_acc_http = FeedHttp("ok")
    denied_acc = AccountsHttp("denied")
    denied_acc_result, denied_acc_db, denied_acc_log, _dacc = run_create(
        sample_record(), denied_acc_http, get_http=denied_acc
    )
    report(not denied_acc_result["ok"] and denied_acc_http.calls == [], "トークン取得失敗では投稿しない")
    report(denied_acc_db.row["status"] == "failed", "トークン取得失敗は failed に記録する")
    report("pages_read_engagement" in (denied_acc_result["message"] or "") and secrets_absent(denied_acc_log), "取得失敗の記録にトークンがない")
    report(
        [item.get("event") for item in denied_acc_db.events] == ["failed"],
        "取得失敗では送信開始イベントを残さない",
    )

    empty_http = FeedHttp("ok")
    empty_result, empty_db, _empty_log, _empty_acc = run_create(
        sample_record(), empty_http, get_http=AccountsHttp("empty")
    )
    report(not empty_result["ok"] and empty_http.calls == [] and empty_db.row["status"] == "failed", "ページ一覧が空なら投稿しない")

    missing_http = FeedHttp("ok")
    missing_acc = AccountsHttp("ok")
    missing_result, missing_db, missing_log, _miss_acc = run_create(
        sample_record(),
        missing_http,
        config={"access_token": "", "page_id": ""},
        get_http=missing_acc,
    )
    report(not missing_result["ok"] and missing_http.calls == [] and missing_acc.calls == [], "環境変数不足では送信しない")
    report(missing_db.row["status"] == "draft" and not missing_db.updates, "設定不足では状態を変えない")
    report("設定が不足" in (missing_result["message"] or "") and secrets_absent(missing_log), "設定不足の文言にトークンがない")

    posted_http = FeedHttp("ok")
    posted_acc = AccountsHttp("ok")
    posted_result, posted_db, _posted_log, _posted_acc = run_create(
        sample_record(status="posted", external_id=POST_ID, posted_at=NOW),
        posted_http,
        get_http=posted_acc,
    )
    report(not posted_result["ok"] and posted_http.calls == [] and posted_acc.calls == [], "posted は再送できない")
    report(posted_db.row["status"] == "posted", "posted の状態は変えない")

    unknown_http = FeedHttp("ok")
    unknown_acc = AccountsHttp("ok")
    unknown_result, unknown_db, _unknown_log, _unknown_acc = run_create(
        sample_record(status="unknown"),
        unknown_http,
        get_http=unknown_acc,
    )
    report(not unknown_result["ok"] and unknown_http.calls == [] and unknown_acc.calls == [], "unknown は再送できない")
    report(unknown_db.row["status"] == "unknown", "unknown の状態は変えない")

    failed_http = FeedHttp("ok")
    failed_result, failed_db, _failed_log, _failed_acc = run_create(sample_record(status="failed"), failed_http)
    report(failed_result["ok"] and failed_db.row["status"] == "posted", "failed は再送できる")

    instagram_http = FeedHttp("ok")
    instagram_acc = AccountsHttp("ok")
    instagram_result, instagram_db, _ig_log, _ig_acc = run_create(
        sample_record(channel="instagram"),
        instagram_http,
        get_http=instagram_acc,
    )
    report(
        not instagram_result["ok"] and instagram_http.calls == [] and instagram_acc.calls == [],
        "Instagramの行はFacebook送信しない",
    )
    report(instagram_db.row["channel"] == "instagram" and instagram_db.row["status"] == "draft", "Instagramの状態は変えない")

    gbp_http = FeedHttp("ok")
    gbp_result, gbp_db, _gbp_log, gbp_acc = run_create(
        sample_record(channel="gbp", gbp_profile="tokyo"),
        gbp_http,
    )
    report(not gbp_result["ok"] and gbp_http.calls == [] and gbp_acc.calls == [], "GBPの行はFacebook送信しない")

    payload = meta_graph.build_facebook_feed_payload("本文", "https://karin-sb.jp/blog/a")
    report(payload == {"message": "本文", "link": "https://karin-sb.jp/blog/a"}, "送信ペイロードにトークンを入れない")

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"id": POST_ID}

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    original_post = meta_graph.requests.post
    meta_graph.requests.post = fake_post
    try:
        status, body = meta_graph.facebook_feed_exchange(
            meta_graph.facebook_feed_url(PAGE_ID),
            access_token=TOKEN,
            body=payload,
        )
    finally:
        meta_graph.requests.post = original_post
    header_auth = (captured.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and body == {"id": POST_ID}
        and TOKEN not in (captured.get("url") or "")
        and "access_token" not in (captured.get("data") or {})
        and header_auth.startswith("Bearer ")
        and captured.get("timeout") == 30,
        "実送信口はヘッダー認証で、クエリと本文にトークンを置かない",
    )

    captured_get = {}

    class FakeGetResponse:
        status_code = 200

        def json(self):
            return {"data": [{"id": PAGE_ID, "access_token": PAGE_TOKEN}]}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured_get["url"] = url
        captured_get["params"] = params
        captured_get["headers"] = headers
        captured_get["timeout"] = timeout
        return FakeGetResponse()

    original_get = meta_graph.requests.get
    meta_graph.requests.get = fake_get
    try:
        status, body = meta_graph.facebook_accounts_exchange(
            meta_graph.facebook_accounts_url(),
            access_token=TOKEN,
            params={"fields": "id,access_token"},
        )
    finally:
        meta_graph.requests.get = original_get
    get_auth = (captured_get.get("headers") or {}).get("Authorization") or ""
    report(
        status == 200
        and TOKEN not in (captured_get.get("url") or "")
        and "access_token" not in (captured_get.get("params") or {})
        and get_auth.startswith("Bearer ")
        and captured_get.get("params") == {"fields": "id,access_token"},
        "ページ一覧取得もヘッダー認証で、クエリにトークンを置かない",
    )

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
