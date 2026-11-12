#!/usr/bin/env python3
"""KARiN.NOTES のGBPは毎回POSTする。Googleへは送らない。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gbp_local_post
from gbp_local_post import GbpPostTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-12T10:00:00+09:00"
LATER = "2026-11-12T10:05:00+09:00"
ACCOUNT = "accounts/111554120993304611204"
FUKUOKA = "locations/9653834603317620900"
TOKYO = "locations/8877844916727282076"
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


class CreateHttp:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.calls = []
        self.ids = []

    def __call__(self, method, url, body=None, access_token=None):
        self.calls.append({"method": method, "url": url})
        if access_token != TOKEN or TOKEN in url or REFRESH in url:
            raise AssertionError("secret in request")
        if method != "POST":
            raise AssertionError(method)
        if self.mode == "timeout":
            raise GbpPostTimeout()
        if self.mode == "server":
            return 503, {"error": {"status": "UNAVAILABLE"}}
        if self.mode == "denied":
            return 400, {"error": {"status": "INVALID_ARGUMENT"}}
        if self.mode == "no-name":
            return 200, {"summary": (body or {}).get("summary") or ""}
        parent = url.split("/v4/", 1)[1].rsplit("/localPosts", 1)[0]
        name = f"{parent}/localPosts/n{len(self.ids) + 1}"
        self.ids.append(name)
        return 200, {"name": name}


def config():
    return {
        "client_id": "client",
        "client_secret": "client-secret",
        "refresh_token": REFRESH,
        "locations": {"tokyo": TOKYO, "fukuoka": FUKUOKA},
    }


def token_exchange():
    def exchange(method, url, headers=None, body=None):
        if "oauth2.googleapis.com" in url:
            return 200, {"access_token": TOKEN}
        return 200, {"accounts": [{"name": ACCOUNT, "type": "PERSONAL"}]}

    return exchange


def record(profile="tokyo", **extra):
    row = {
        "id": f"row-{profile}",
        "status": "draft",
        "gbp_profile": profile,
        "body": "本文",
        "link_url": "https://karin-sb.jp/blog/kata",
        "image_url": "",
        "external_id": None,
        "posted_at": None,
        "updated_at": NOW,
    }
    row.update(extra)
    return row


def create(db, http, row=None, now=NOW):
    return gbp_local_post.perform_notes_gbp_create(
        db,
        row or record(),
        config=config(),
        token_exchange=token_exchange(),
        post_exchange=http,
        now=now,
        staff_id="staff-1",
    )


def main():
    tokyo_parent = f"{ACCOUNT}/locations/{TOKYO.split('/')[1]}"
    fukuoka_parent = f"{ACCOUNT}/locations/{FUKUOKA.split('/')[1]}"

    tokyo_http = CreateHttp()
    tokyo_db = FakeDB(record("tokyo"))
    tokyo_result = create(tokyo_db, tokyo_http, record("tokyo"))
    previous_tokyo = f"{tokyo_parent}/localPosts/n1"
    report(tokyo_result["ok"] is True and tokyo_db.row["status"] == "posted", "東京の初回POSTは投稿済になる")
    report(
        tokyo_http.calls[0]["method"] == "POST"
        and tokyo_parent in tokyo_http.calls[0]["url"]
        and tokyo_db.row["external_id"] == previous_tokyo,
        "東京の初回はPOSTで投稿IDを保存する",
        str(tokyo_http.calls),
    )
    report(all(item["method"] == "POST" for item in tokyo_http.calls), "東京の初回はLISTやGETを使わない")

    tokyo_repost = create(
        tokyo_db,
        tokyo_http,
        dict(tokyo_db.row, body="本文", link_url="https://karin-sb.jp/blog/kata", image_url=""),
        now=LATER,
    )
    report(tokyo_repost["ok"] is True and tokyo_db.row["status"] == "posted", "東京の投稿済からも再POSTできる")
    report(
        tokyo_http.calls[1]["method"] == "POST"
        and tokyo_db.row["external_id"] == f"{tokyo_parent}/localPosts/n2"
        and tokyo_db.row["external_id"] != previous_tokyo,
        "東京の再投稿もPOSTで新しい投稿IDを保存する",
        str(tokyo_db.row.get("external_id")),
    )
    report(
        any(
            event.get("event") == "submit_started"
            and "前回のGoogle投稿ID" in (event.get("detail") or "")
            and previous_tokyo in (event.get("detail") or "")
            for event in tokyo_db.events
        ),
        "東京の前回Google投稿IDは履歴に残る",
        str(tokyo_db.events),
    )

    fukuoka_http = CreateHttp()
    fukuoka_db = FakeDB(record("fukuoka"))
    fukuoka_result = create(fukuoka_db, fukuoka_http, record("fukuoka"))
    previous_fukuoka = f"{fukuoka_parent}/localPosts/n1"
    report(fukuoka_result["ok"] is True and fukuoka_db.row["status"] == "posted", "福岡の初回POSTは投稿済になる")
    report(
        fukuoka_parent in fukuoka_http.calls[0]["url"]
        and fukuoka_db.row["external_id"] == previous_fukuoka,
        "福岡の初回は福岡ロケーションへPOSTする",
    )

    create(
        fukuoka_db,
        fukuoka_http,
        dict(fukuoka_db.row, body="本文", link_url="https://karin-sb.jp/blog/kata", image_url=""),
        now=LATER,
    )
    report(
        fukuoka_db.row["external_id"] == f"{fukuoka_parent}/localPosts/n2"
        and any(
            event.get("event") == "submit_started"
            and "前回のGoogle投稿ID" in (event.get("detail") or "")
            and previous_fukuoka in (event.get("detail") or "")
            for event in fukuoka_db.events
        ),
        "福岡の前回Google投稿IDは履歴に残る",
    )
    report(
        tokyo_db.row["gbp_profile"] == "tokyo"
        and fukuoka_db.row["gbp_profile"] == "fukuoka"
        and tokyo_db.row["external_id"] != fukuoka_db.row["external_id"],
        "東京と福岡の投稿状態は独立している",
    )

    unknown_http = CreateHttp(mode="timeout")
    unknown_db = FakeDB(record("tokyo", status="draft"))
    unknown_result = create(unknown_db, unknown_http, record("tokyo"))
    report(
        unknown_result["ok"] is False
        and unknown_db.row["status"] == "unknown"
        and unknown_db.row.get("external_id") is None
        and len(unknown_http.calls) == 1,
        "結果不明はunknownになり、自動再送しない",
        str(unknown_result),
    )
    report("自動再送しません" in (unknown_result["message"] or ""), "結果不明の案内は自動再送しない")

    old_send, old_reason = gbp_local_post.begin_notes_gbp_submit(
        {"id": "row-tokyo", "status": "unknown", "gbp_profile": "tokyo"},
        NOW,
    )
    report(old_send is None and old_reason, "従来の送信開始はunknownを自動再送しない", str(old_reason))
    old_flow = gbp_local_post.perform_notes_gbp_send(
        FakeDB(record("tokyo", status="unknown")),
        record("tokyo", status="unknown"),
        config=config(),
        token_exchange=token_exchange(),
        post_exchange=CreateHttp(),
        now=NOW,
        staff_id="staff-1",
    )
    report(
        old_flow["ok"] is False and old_flow["record"].get("status") == "unknown",
        "従来の送信処理はunknownを送らない",
        str(old_flow),
    )

    explicit = CreateHttp()
    explicit_db = FakeDB(record("tokyo", status="unknown"))
    explicit_result = create(explicit_db, explicit, record("tokyo", status="unknown"))
    report(
        explicit_result["ok"] is True
        and explicit.calls[0]["method"] == "POST"
        and explicit_db.row["status"] == "posted",
        "unknownからの明示再投稿は新規POSTする",
    )

    failed_http = CreateHttp(mode="denied")
    failed_db = FakeDB(record("fukuoka", status="draft"))
    failed_result = create(failed_db, failed_http, record("fukuoka"))
    report(failed_result["ok"] is False and failed_db.row["status"] == "failed", "4xxはfailedになる")
    retry_http = CreateHttp()
    retry_result = create(failed_db, retry_http, dict(failed_db.row, body="本文", link_url="https://karin-sb.jp/blog/kata"))
    report(retry_result["ok"] is True and failed_db.row["status"] == "posted", "failedからの再投稿は新規POSTする")

    posting_plan, posting_reason = gbp_local_post.begin_notes_gbp_create(
        record("tokyo", status="posting"),
        NOW,
    )
    report(posting_plan is None and posting_reason, "送信中は重ねて送らない", str(posting_reason))

    posted_plan, posted_reason = gbp_local_post.begin_notes_gbp_create(
        record("tokyo", status="posted", external_id=f"{tokyo_parent}/localPosts/old"),
        NOW,
    )
    report(
        posted_reason is None
        and posted_plan["previous_id"] == f"{tokyo_parent}/localPosts/old"
        and "前回のGoogle投稿ID" in posted_plan["event"]["detail"],
        "再投稿前に前回の投稿IDを履歴へ残す",
        str(posted_plan),
    )

    patched = gbp_local_post.plan_request(
        {
            "body": "本文",
            "link_url": "https://karin-sb.jp/blog/kata",
            "image_url": "",
            "location_name": TOKYO,
            "external_id": f"{tokyo_parent}/localPosts/old",
        },
        ACCOUNT,
    )
    created = gbp_local_post.plan_create_request(
        {
            "body": "本文",
            "link_url": "https://karin-sb.jp/blog/kata",
            "image_url": "",
            "location_name": TOKYO,
            "external_id": f"{tokyo_parent}/localPosts/old",
        },
        ACCOUNT,
    )
    report(patched["method"] == "PATCH", "既存のplan_requestは投稿IDがあるとPATCHのまま")
    report(created["method"] == "POST", "NOTES専用の作成は投稿IDがあってもPOSTする")

    no_name = CreateHttp(mode="no-name")
    no_name_db = FakeDB(record("tokyo"))
    no_name_result = create(no_name_db, no_name, record("tokyo"))
    report(
        no_name_result["ok"] is False
        and no_name_db.row["status"] == "unknown"
        and no_name_db.row.get("external_id") is None,
        "投稿IDが無いPOST応答は成功にしない",
    )

    finish_posted = gbp_local_post.finish_notes_gbp_create(
        record("tokyo"),
        http_status=200,
        body={"name": f"{tokyo_parent}/localPosts/ok"},
        timed_out=False,
        now=NOW,
        parent=tokyo_parent,
    )
    report(
        finish_posted["fields"]["status"] == "posted"
        and finish_posted["fields"]["external_id"] == f"{tokyo_parent}/localPosts/ok",
        "NOTESの成功判定はPOSTの投稿IDだけを使う",
    )

    schedule_src = open(os.path.join(ROOT, "gbp_schedule_sync.py"), encoding="utf-8").read()
    app_src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    report("perform_notes_gbp_send" in schedule_src and "perform_notes_gbp_create" not in schedule_src, "スケジュール投稿は従来の送信処理のまま")
    report("perform_notes_gbp_check" in schedule_src, "スケジュール投稿の確認処理は残っている")
    report("_run_gbp_external_action" in app_src and "admin_gbp_service_post" in app_src, "鍼灸サービス投稿は従来の送信処理を使う")
    report("perform_hours_apply" in schedule_src, "営業時間同期の処理は残っている")
    report("def perform_notes_gbp_send" in open(os.path.join(ROOT, "gbp_local_post.py"), encoding="utf-8").read(), "従来のPATCH送信関数は残っている")

    events_src = open(os.path.join(ROOT, "external_posts.py"), encoding="utf-8").read()
    report(".limit(100)" in events_src and "DELETE" not in events_src.split("def list_post_events", 1)[1].split("def save_notes_post", 1)[0], "投稿履歴の表示は100件までで、削除しない")

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
