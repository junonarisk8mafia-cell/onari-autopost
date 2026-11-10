"""
Onari Auto Post - Threads 自動投稿ボット（文章だけ）

threads/posts.json に書いた投稿のうち、日付が「今日（日本時間）」のものを1本だけ投稿する。
Instagram とは別の、Threads 専用の短い文章を出すための係。
投稿済みの日付は threads/posted.json に記録し、同じ日に二重投稿しない。

必要な環境変数（GitHub の Secrets に登録）:
  THREADS_TOKEN   : Threads のアクセストークン
  THREADS_USER_ID : Threads のユーザーID（未登録なら "me" を使う）
テスト用:
  THREADS_POST_DATE : 投稿する日付を指定（例 2026-11-02）。空なら今日
  DRY_RUN=1         : 実際には投稿せず、投稿する予定の文章を表示するだけ
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

POSTS = Path("threads/posts.json")
POSTED = Path("threads/posted.json")
JST = timezone(timedelta(hours=9))
EARLIEST_HOUR = 18  # 夕方6時より前は投稿しない（見られてるのは18〜21時）
BASE = "https://graph.threads.net/v1.0"
MAX_CHARS = 500


def load_post(today):
    posts = json.loads(POSTS.read_text(encoding="utf-8"))["posts"]
    return next((p for p in posts if p["date"] == today), None)


def publish_text(token, user_id, text, topic=None):
    data = {"media_type": "TEXT", "text": text, "access_token": token}
    if topic:  # トピックを付けると伸びやすい（Meta公式）。1投稿に1つだけ
        data["topic_tag"] = topic
    r = requests.post(f"{BASE}/{user_id}/threads", data=data, timeout=60)
    if not r.ok and topic:  # トピックで失敗したら、トピックなしでもう一度
        print(f"⚠️ トピック「{topic}」で失敗したので、なしで投稿: {r.text[:200]}")
        data.pop("topic_tag")
        r = requests.post(f"{BASE}/{user_id}/threads", data=data, timeout=60)
    if not r.ok:
        sys.exit(f"❌ Threads の準備に失敗: {r.status_code} {r.text}")
    cid = r.json()["id"]
    # 文章だけでも、公開前に少し待つのが公式の推奨
    for _ in range(10):
        s = requests.get(f"{BASE}/{cid}", params={"fields": "status,error_message", "access_token": token}, timeout=30)
        status = s.json().get("status") if s.ok else None
        if status == "FINISHED":
            break
        if status == "ERROR":
            sys.exit(f"❌ Threads 側で処理に失敗: {s.text}")
        time.sleep(3)
    for _ in range(6):  # 準備ができる前だと "Media Not Found" になるので、少し待ってやり直す
        p = requests.post(f"{BASE}/{user_id}/threads_publish",
                          data={"creation_id": cid, "access_token": token}, timeout=60)
        if p.ok or "4279009" not in p.text:
            break
        print("⏳ まだ準備中みたいなので、10秒待ってやり直す")
        time.sleep(10)
    if not p.ok:
        sys.exit(f"❌ Threads の公開に失敗: {p.status_code} {p.text}")
    return p.json().get("id")


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    now = datetime.now(JST)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and now.hour < EARLIEST_HOUR:
        print(f"🌙 まだ{now:%H:%M}。{EARLIEST_HOUR}時までは待つ")
        return
    today = os.environ.get("THREADS_POST_DATE") or now.strftime("%Y-%m-%d")
    posted = json.loads(POSTED.read_text(encoding="utf-8")) if POSTED.exists() else {}
    if today in posted:
        print(f"✅ {today} はもう投稿済みなので、何もしない")
        return

    post = load_post(today)
    if post is None:
        print(f"📭 {today} の Threads の予定はないので、今日は休み")
        return
    text = post["text"].strip()
    if len(text) > MAX_CHARS:
        sys.exit(f"❌ {today} の文章が{len(text)}文字。Threads は{MAX_CHARS}文字まで")

    if dry:
        print(f"🧪 [DRY RUN] {today} に投稿する予定:\n{text}")
        return

    token = os.environ.get("THREADS_TOKEN")
    if not token:
        print("ℹ️ THREADS_TOKEN が登録されていないので何もしない")
        return
    user_id = os.environ.get("THREADS_USER_ID") or "me"

    print(f"📤 Threads に投稿します: {post.get('title', '')}")
    pid = publish_text(token, user_id, text, post.get("topic"))
    posted[today] = {"id": pid, "title": post.get("title", "")}
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Threads に投稿完了！ id: {pid}")


if __name__ == "__main__":
    main()
