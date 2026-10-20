#!/usr/bin/env python3
"""GBP投稿のペイロードと状態遷移。Googleへは送らない。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import external_posts
import gbp_local_post
from gbp_local_post import GbpPostRefused, GbpPostTimeout

FAILED = 0
PASSED = 0
NOW = "2026-11-01T10:00:00+09:00"
LATER = "2026-11-01T10:00:05+09:00"
ACCOUNT = "accounts/111554120993304611204"
TOKYO = "locations/8877844916727282076"
FUKUOKA = "locations/9653834603317620900"
PARENT = f"{ACCOUNT}/locations/{FUKUOKA.split('/')[1]}"
CREATED = f"{PARENT}/localPosts/created1"
OLD_TOKYO = f"{ACCOUNT}/locations/{TOKYO.split('/')[1]}/localPosts/existing1"


def report(ok, name, detail=""):
    global FAILED, PASSED
    if ok:
        PASSED += 1
        print(f"PASS: {name}")
    else:
        FAILED += 1
        print(f"FAIL: {name} {detail}")


class FakeHttp:
    def __init__(self, mode, name=CREATED, summary="本文"):
        self.mode = mode
        self.name = name
        self.summary = summary
        self.calls = []

    def __call__(self, method, url, body=None):
        self.calls.append({"method": method, "url": url, "body": body})
        if method == "DELETE":
            raise AssertionError("delete")
        if self.mode == "timeout":
            raise GbpPostTimeout()
        if self.mode == "server":
            return 503, {"error": {"status": "UNAVAILABLE"}}
        if self.mode == "denied":
            return 403, {"error": {"status": "PERMISSION_DENIED"}}
        if self.mode == "other-name":
            return 200, {"name": OLD_TOKYO, "summary": self.summary}
        if self.mode == "no-name":
            return 200, {"summary": self.summary}
        if self.mode == "mismatch":
            return 200, {"name": self.name, "summary": "別の本文"}
        if method == "GET":
            return 200, {
                "name": self.name,
                "summary": self.summary,
                "callToAction": {"actionType": "LEARN_MORE", "url": "https://karin-sb.jp/blog/kata"},
            }
        reply = {"name": self.name, "summary": body["summary"]}
        if body.get("callToAction"):
            reply["callToAction"] = body["callToAction"]
        else:
            reply["callToAction"] = {"actionType": "LEARN_MORE", "url": "https://karin-sb.jp/blog/kata"}
        if body.get("media"):
            reply["media"] = body["media"]
        return 200, reply


def ready_record(**extra):
    record = {
        "id": "row-1",
        "status": "ready",
        "body": "本文",
        "link_url": "https://karin-sb.jp/blog/kata",
        "image_url": "",
        "external_id": None,
        "posted_at": None,
        "location_name": FUKUOKA,
    }
    record.update(extra)
    return record


def main():
    trial = gbp_local_post.build_fukuoka_trial_payload()
    report(trial["ok"], "福岡の試験ペイロードは検証を通る", str(trial["errors"]))
    report(trial["payload"]["topicType"] == "STANDARD" and "media" not in trial["payload"], "試験はSTANDARDで画像なし")
    report(trial["payload"]["callToAction"]["url"] == "https://karin-sb.jp/", "試験のリンクは公開サイト")
    report(len(trial["payload"]["summary"]) <= 1500, "試験文は1500文字以内")

    too_long = gbp_local_post.build_standard_post("あ" * 1501, "https://karin-sb.jp/")
    report(not too_long["ok"], "1501文字は送らない")
    relative = gbp_local_post.build_standard_post("本文", "https://karin-sb.jp/", "/static/images/a.jpg")
    report(not relative["ok"], "サイト内パスの画像は送らない")
    http_link = gbp_local_post.build_standard_post("本文", "http://karin-sb.jp/")
    report(not http_link["ok"], "httpのリンクは送らない")
    with_image = gbp_local_post.build_standard_post(
        "本文",
        "https://karin-sb.jp/blog/stretch-pole-posture",
        "https://karin-sb.jp/static/images/blogs/pole.jpg",
    )
    report(
        with_image["ok"]
        and with_image["payload"]["media"]
        == [{"mediaFormat": "PHOTO", "sourceUrl": "https://karin-sb.jp/static/images/blogs/pole.jpg"}],
        "https画像はmediaに1枚だけ載せる",
    )
    report("media" not in gbp_local_post.build_standard_post("本文", "https://karin-sb.jp/")["payload"], "画像なしはmediaを付けない")
    preview = gbp_local_post.build_standard_post(
        "本文\nhttps://karin-sb.jp/blog/stretch-pole-posture",
        "https://karin-sb.jp/blog/stretch-pole-posture",
        "https://karin-sb.jp/static/images/notes/stretch-pole-posture.jpg",
    )
    preview_text = gbp_local_post.payload_text(preview["payload"])
    report(
        preview["payload"]["callToAction"]["url"] == "https://karin-sb.jp/blog/stretch-pole-posture"
        and preview["payload"]["media"][0]["sourceUrl"] == "https://karin-sb.jp/static/images/notes/stretch-pole-posture.jpg"
        and "](" not in preview_text
        and "[https://" not in preview["payload"]["summary"],
        "送信JSONのURLはMarkdownではなく絶対https",
    )

    report(gbp_local_post.require_single_account([{"name": ACCOUNT}]) == ACCOUNT, "アカウント1件は採用する")
    refused = False
    try:
        gbp_local_post.require_single_account([{"name": ACCOUNT}, {"name": "accounts/2"}])
    except GbpPostRefused:
        refused = True
    report(refused, "アカウントが2件なら送信しない")
    refused = False
    try:
        gbp_local_post.require_single_account([])
    except GbpPostRefused:
        refused = True
    report(refused, "アカウントが0件なら送信しない")

    tokyo_req = gbp_local_post.plan_request(ready_record(location_name=TOKYO), ACCOUNT)
    fukuoka_req = gbp_local_post.plan_request(ready_record(), ACCOUNT)
    report("8877844916727282076" in tokyo_req["url"] and "9653834603317620900" in fukuoka_req["url"], "東京と福岡は別の投稿先")
    report(tokyo_req["method"] == "POST" and fukuoka_req["method"] == "POST", "投稿IDがなければPOST")
    image_create = gbp_local_post.plan_request(
        ready_record(image_url="https://karin-sb.jp/static/images/blogs/pole.jpg"),
        ACCOUNT,
    )
    report(
        image_create["method"] == "POST"
        and image_create["body"]["media"][0]["sourceUrl"] == "https://karin-sb.jp/static/images/blogs/pole.jpg",
        "新規送信の本文に画像を含める",
    )
    image_patch = gbp_local_post.plan_request(
        ready_record(
            external_id=CREATED,
            image_url="https://karin-sb.jp/static/images/blogs/pole.jpg",
        ),
        ACCOUNT,
    )
    report(
        image_patch["method"] == "PATCH"
        and CREATED in image_patch["url"]
        and "updateMask=summary,callToAction.actionType,callToAction.url,media.mediaFormat,media.sourceUrl"
        in image_patch["url"]
        and image_patch["body"]["summary"] == "本文"
        and image_patch["body"]["callToAction"]["url"] == "https://karin-sb.jp/blog/kata"
        and image_patch["body"]["media"][0]["sourceUrl"] == "https://karin-sb.jp/static/images/blogs/pole.jpg"
        and "languageCode" not in image_patch["body"],
        "投稿済み更新のPATCHは同じ投稿へ本文・CTA・画像を指定する",
    )
    stale = gbp_local_post.finish_notes_gbp_submit(
        ready_record(external_id=CREATED, image_url="https://karin-sb.jp/static/images/blogs/pole.jpg"),
        http_status=200,
        body={
            "name": CREATED,
            "summary": "本文",
            "callToAction": {"actionType": "LEARN_MORE", "url": "https://karin-sb.jp/old"},
            "media": [{"mediaFormat": "PHOTO", "sourceUrl": "https://karin-sb.jp/old.jpg"}],
        },
        timed_out=False,
        now=LATER,
        parent=PARENT,
    )
    report(stale["fields"]["status"] == "unknown", "応答のリンクや画像が古ければ投稿成功にしない")
    incomplete = gbp_local_post.finish_notes_gbp_submit(
        ready_record(external_id=CREATED, image_url="https://karin-sb.jp/static/images/blogs/pole.jpg"),
        http_status=200,
        body={"name": CREATED, "summary": "本文"},
        timed_out=False,
        now=LATER,
        parent=PARENT,
    )
    report(incomplete["fields"]["status"] == "unknown", "リンクや画像が無い応答は投稿成功にしない")
    log_info = gbp_local_post.inspect_local_post_reply(
        ready_record(image_url="https://karin-sb.jp/static/images/blogs/pole.jpg"),
        {"name": CREATED, "summary": "本文"},
        parent=PARENT,
        expected_name=CREATED,
    )
    log_text = gbp_local_post.log_local_post_verify(
        "PATCH",
        200,
        ready_record(image_url="https://karin-sb.jp/static/images/blogs/pole.jpg"),
        {"name": CREATED, "summary": "本文", "callToAction": {"url": "https://secret.example/path"}},
        parent=PARENT,
        expected_name=CREATED,
    )
    report(
        log_info["has_cta"] == "no"
        and log_info["has_media"] == "no"
        and log_info["cta"] == "absent"
        and log_info["image"] == "absent"
        and log_text["summary"] == "match",
        "確認ログは項目の有無と一致だけを残す",
    )
    report(
        "https://" not in str(log_text)
        and "secret.example" not in str(log_text)
        and "karin-sb.jp" not in str(log_text),
        "確認ログにURLを出さない",
    )
    report("media" not in fukuoka_req["url"] and "media" not in fukuoka_req["body"], "画像なしの送信はmediaを付けない")

    http = FakeHttp("ok")
    result, reason = gbp_local_post.execute_notes_gbp_submit(ready_record(), ACCOUNT, http, NOW)
    report(reason is None and result["fields"]["status"] == "posted", "成功応答のあとだけ投稿済")
    report(result["fields"]["external_id"] == CREATED and result["fields"]["posted_at"] == NOW, "投稿IDと時刻を保存する")
    report(http.calls[0]["method"] == "POST" and "/localPosts" in http.calls[0]["url"], "新規はPOST")
    report(all(call["method"] != "DELETE" for call in http.calls), "削除は送らない")

    posted = ready_record(status="posted", external_id=CREATED, posted_at=NOW, body="本文")
    again = FakeHttp("ok", name=CREATED)
    blocked, block_reason = gbp_local_post.execute_notes_gbp_submit(posted, ACCOUNT, again, LATER)
    report(blocked is None and again.calls == [], "投稿済のままでは再送しない", str(block_reason))

    update = ready_record(external_id=CREATED, body="本文")
    patched = FakeHttp("ok", name=CREATED)
    updated, update_reason = gbp_local_post.execute_notes_gbp_submit(update, ACCOUNT, patched, LATER)
    report(update_reason is None and patched.calls[0]["method"] == "PATCH", "投稿IDがある確認済はPATCH", str(update_reason))
    report(updated["fields"]["external_id"] == CREATED, "PATCH後も同じ投稿ID")

    timed = FakeHttp("timeout")
    unknown, unknown_reason = gbp_local_post.execute_notes_gbp_submit(ready_record(), ACCOUNT, timed, NOW)
    report(unknown_reason is None and unknown["fields"]["status"] == "unknown", "タイムアウトは成否不明")
    report(unknown["fields"]["external_id"] is None and unknown["fields"]["status"] != "posted", "不明なまま投稿済にしない")
    retry = FakeHttp("ok")
    unknown_record = ready_record(status="unknown", body="本文")
    retried, retry_reason = gbp_local_post.execute_notes_gbp_submit(unknown_record, ACCOUNT, retry, LATER)
    report(retried is None and retry.calls == [], "成否不明からは自動再送しない", str(retry_reason))

    denied = FakeHttp("denied")
    failed, failed_reason = gbp_local_post.execute_notes_gbp_submit(ready_record(external_id=CREATED), ACCOUNT, denied, NOW)
    report(failed_reason is None and failed["fields"]["status"] == "failed", "403は失敗")
    report(failed["fields"]["external_id"] == CREATED, "失敗しても投稿IDを消さない")

    server = FakeHttp("server")
    unclear, unclear_reason = gbp_local_post.execute_notes_gbp_submit(ready_record(), ACCOUNT, server, NOW)
    report(unclear_reason is None and unclear["fields"]["status"] == "unknown", "5xxは成否不明")

    other = FakeHttp("other-name")
    not_adopted, adopt_reason = gbp_local_post.execute_notes_gbp_submit(ready_record(), ACCOUNT, other, NOW)
    report(adopt_reason is None and not_adopted["fields"]["status"] == "unknown", "別ロケーションの投稿IDは採用しない")
    report(not_adopted["fields"]["external_id"] is None, "既存の東京投稿IDを保存しない")

    draft = FakeHttp("ok")
    skipped, skip_reason = gbp_local_post.execute_notes_gbp_submit(ready_record(status="draft"), ACCOUNT, draft, NOW)
    report(skipped is None and draft.calls == [], "未確認は送信しない", str(skip_reason))

    posting = FakeHttp("ok")
    overlap, overlap_reason = gbp_local_post.execute_notes_gbp_submit(ready_record(status="posting"), ACCOUNT, posting, NOW)
    report(overlap is None and posting.calls == [], "送信中は重ねて送らない", str(overlap_reason))

    listed = gbp_local_post.reconcile_unknown(
        ready_record(status="unknown"),
        [
            {"name": OLD_TOKYO, "summary": "本文", "createTime": "2026-10-01T00:00:00Z"},
            {"name": CREATED, "summary": "本文", "createTime": "2026-11-01T10:00:02Z"},
        ],
        submitted_summary="本文",
        submitted_at=NOW,
        parent=PARENT,
    )
    report(listed["candidate_name"] == CREATED and listed["fields"]["status"] == "unknown", "送信後の1件だけ候補にし、まだ投稿済にしない")
    confirmed = gbp_local_post.confirm_fetched_post(
        {
            "id": "row-1",
            "status": "unknown",
            "external_id": CREATED,
            "body": "本文",
            "link_url": "https://karin-sb.jp/blog/kata",
            "posted_at": None,
        },
        {
            "name": CREATED,
            "summary": "本文",
            "callToAction": {"actionType": "LEARN_MORE", "url": "https://karin-sb.jp/blog/kata"},
        },
        "本文",
        LATER,
    )
    report(confirmed["fields"]["status"] == "posted" and confirmed["fields"]["external_id"] == CREATED, "取得本文が一致してから投稿済")
    incomplete_get = gbp_local_post.confirm_fetched_post(
        {
            "id": "row-1",
            "status": "unknown",
            "external_id": CREATED,
            "body": "本文",
            "link_url": "https://karin-sb.jp/blog/kata",
            "image_url": "https://karin-sb.jp/static/images/blogs/pole.jpg",
            "posted_at": None,
        },
        {"name": CREATED, "summary": "本文"},
        "本文",
        LATER,
    )
    report(incomplete_get["fields"]["status"] == "unknown", "GETにリンクや画像が無ければ投稿済にしない")

    missed = gbp_local_post.reconcile_unknown(
        ready_record(status="unknown"),
        [{"name": OLD_TOKYO, "summary": "本文", "createTime": "2026-10-01T00:00:00Z"}],
        submitted_summary="本文",
        submitted_at=NOW,
        parent=PARENT,
    )
    report(
        missed["fields"]["status"] == "unknown"
        and missed["fields"]["external_id"] is None
        and missed["fields"]["error_message"] == gbp_local_post.UNRESOLVED_POST_MESSAGE,
        "古い東京投稿は紐づけず、新規送信も再開しない",
    )

    ambiguous = gbp_local_post.reconcile_unknown(
        ready_record(status="unknown"),
        [
            {"name": CREATED, "summary": "本文", "createTime": "2026-11-01T10:00:02Z"},
            {"name": PARENT + "/localPosts/created2", "summary": "本文", "createTime": "2026-11-01T10:00:03Z"},
        ],
        submitted_summary="本文",
        submitted_at=NOW,
        parent=PARENT,
    )
    report(ambiguous["fields"]["status"] == "unknown" and "candidate_name" not in ambiguous, "候補が複数なら確定しない")

    stuck = gbp_local_post.reconcile_unknown(
        ready_record(status="posting"),
        [{"name": CREATED, "summary": "本文", "createTime": "2026-11-01T10:00:02Z"}],
        submitted_summary="本文",
        submitted_at=NOW,
        parent=PARENT,
    )
    report(stuck["candidate_name"] == CREATED and stuck["fields"]["status"] == "unknown", "送信中のまま残っても再送せず候補だけ控える")

    kept_patch = gbp_local_post.reconcile_unknown(
        ready_record(status="unknown", external_id=CREATED),
        [{"name": OLD_TOKYO, "summary": "本文", "createTime": "2026-10-01T00:00:00Z"}],
        submitted_summary="本文",
        submitted_at=NOW,
        parent=PARENT,
    )
    report(
        kept_patch["fields"]["status"] == "unknown" and kept_patch["fields"]["external_id"] == CREATED,
        "更新の確認でも既存の投稿IDを消さない",
    )

    kept, kept_reason = external_posts.prepare_notes_save(
        {"status": "failed", "id": "row-1", "external_id": CREATED, "posted_at": NOW, "blog_id": "12"},
        external_posts.get_target("gbp_fukuoka"),
        12,
        "本文",
        "https://karin-sb.jp/blog/kata",
        "",
        "staff-1",
        LATER,
    )
    report(kept_reason is None and kept["fields"]["external_id"] == CREATED, "失敗行を保存し直しても投稿IDを消さない", str(kept_reason))
    report(kept["fields"]["posted_at"] == NOW and kept["fields"]["status"] == "draft", "失敗行の保存は下書きのまま投稿日時を残す")

    unknown_locked, unknown_reason = external_posts.prepare_notes_save(
        {"status": "unknown", "id": "row-1", "external_id": CREATED},
        external_posts.get_target("gbp_fukuoka"),
        12,
        "本文",
        "",
        "",
        "staff-1",
        LATER,
    )
    report(unknown_locked is None and unknown_reason, "成否未確認は上書きしない", str(unknown_reason))

    revised, revise_reason = external_posts.prepare_notes_revision(
        {"status": "posted", "id": "row-1", "blog_id": "12", "external_id": CREATED, "posted_at": NOW},
        external_posts.get_target("gbp_fukuoka"),
        "更新後",
        "https://karin-sb.jp/blog/kata",
        "",
        "staff-1",
        LATER,
    )
    report(revise_reason is None and revised["fields"]["external_id"] == CREATED, "投稿済みの更新でも投稿IDを残す", str(revise_reason))
    report(revised["fields"]["status"] == "ready" and "投稿していません" in revised["event"]["detail"], "更新後は確認待ちで、まだ送信しない")

    still_locked, still_reason = external_posts.prepare_notes_save(
        {"status": "posted", "id": "x"},
        external_posts.get_target("gbp_tokyo"),
        12,
        "本文",
        "",
        "",
        "staff-1",
        NOW,
    )
    report(still_locked is None and still_reason, "通常の保存は投稿済を上書きしない", str(still_reason))

    print(f"\n{PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
