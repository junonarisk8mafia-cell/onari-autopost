"""
Onari Auto Post - X（旧Twitter）自動投稿ボット

x/posts.json に書いた投稿のうち、日付が「今日（日本時間）」のものを1本だけ投稿する。
  1. 本文＋画像を投稿
  2. replies に書いた文を、自分の投稿へのリプとして順番に付ける（ツリー）
投稿済みの日付は x/posted.json に記録し、同じ日に二重投稿しない。

必要な環境変数（GitHub の Secrets に登録）:
  X_API_KEY / X_API_SECRET         : X Developer Portal の「API Key and Secret」
  X_ACCESS_TOKEN / X_ACCESS_SECRET : 同じ画面の「Access Token and Secret」
                                     （アプリの権限を Read and Write にしてから発行すること）
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests_oauthlib import OAuth1

POSTS = Path("x/posts.json")
POSTED = Path("x/posted.json")
JST = timezone(timedelta(hours=9))

TWEET_URL = "https://api.x.com/2/tweets"
MEDIA_URL_V2 = "https://api.x.com/2/media/upload"
MEDIA_URL_V1 = "https://upload.twitter.com/1.1/media/upload.json"


def auth():
    keys = ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        print(f"ℹ️ X の鍵がまだ登録されていないので何もしない: {', '.join(missing)}")
        return None
    return OAuth1(*(os.environ[k] for k in keys))


def upload_image(oauth, path: Path) -> str:
    """画像をアップロードして media_id を返す（新しい v2 → ダメなら旧 v1.1）"""
    with open(path, "rb") as f:
        r = requests.post(MEDIA_URL_V2, auth=oauth, files={"media": f},
                          data={"media_category": "tweet_image"}, timeout=120)
    if r.ok:
        data = r.json().get("data", r.json())
        mid = data.get("id") or data.get("media_id_string")
        if mid:
            return str(mid)
    print(f"ℹ️ v2 アップロード失敗 ({r.status_code} {r.text[:200]})、v1.1 で再挑戦")
    with open(path, "rb") as f:
        r = requests.post(MEDIA_URL_V1, auth=oauth, files={"media": f}, timeout=120)
    if not r.ok:
        sys.exit(f"❌ 画像のアップロードに失敗: {r.status_code} {r.text}")
    return r.json()["media_id_string"]


def tweet(oauth, text, media_id=None, reply_to=None) -> str:
    body = {"text": text}
    if media_id:
        body["media"] = {"media_ids": [media_id]}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    r = requests.post(TWEET_URL, auth=oauth, json=body, timeout=60)
    if not r.ok:
        sys.exit(f"❌ 投稿に失敗: {r.status_code} {r.text}")
    return r.json()["data"]["id"]


def main():
    oauth = auth()
    if oauth is None:
        return

    today = os.environ.get("X_POST_DATE") or datetime.now(JST).strftime("%Y-%m-%d")
    posted = json.loads(POSTED.read_text(encoding="utf-8")) if POSTED.exists() else {}
    if today in posted:
        print(f"✅ {today} はもう投稿済みなので、何もしない")
        return

    posts = json.loads(POSTS.read_text(encoding="utf-8"))["posts"]
    post = next((p for p in posts if p["date"] == today), None)
    if post is None:
        print(f"📭 {today} の投稿予定はないので、今日は休み")
        return

    print(f"📤 投稿します: {post['title']}")
    media_id = upload_image(oauth, Path(post["image"])) if post.get("image") else None
    first_id = tweet(oauth, post["text"], media_id=media_id)
    print(f"✅ 本文を投稿: https://x.com/i/web/status/{first_id}")

    # 先に記録しておく（ツリーの途中で失敗しても、本文の二重投稿はしない）
    posted[today] = {"id": first_id, "title": post["title"], "replies": []}
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")

    parent = first_id
    for i, reply in enumerate(post.get("replies", []), 1):
        time.sleep(5)
        try:
            parent = tweet(oauth, reply, reply_to=parent)
        except SystemExit as e:
            print(f"⚠️ ツリー{i}つ目で失敗。本文は投稿済み。手動で付けてくれ: {e}")
            break
        posted[today]["replies"].append(parent)
        print(f"✅ ツリー{i}つ目を投稿")
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
