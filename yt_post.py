"""
YouTube にショート動画を投稿する係。

video/schedule.json の今日（日本時間）の分を、YouTube に出す。
必要な鍵（GitHub の Secrets）:
  YT_CLIENT_ID, YT_CLIENT_SECRET : Google Cloud で作った OAuth クライアント
  YT_REFRESH_TOKEN               : OAuth Playground で取ったリフレッシュトークン（youtube.upload）
注意: Google の審査（API監査）を通るまで、API で上げた動画は「非公開」に固定される。
テスト: DRY_RUN=1 で投稿せずに中身だけ表示。YT_POST_DATE=YYYY-MM-DD で日付を指定。
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
SCHED = ROOT / "video/schedule.json"
POSTED = ROOT / "video/posted_youtube.json"


def today():
    return os.environ.get("YT_POST_DATE") or (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()


def fail(msg):
    print(f"::error title=YouTube post failed::{msg[:300]}")
    sys.exit(f"❌ {msg}")


def main():
    day = today()
    posts = {p["date"]: p for p in json.loads(SCHED.read_text(encoding="utf-8"))["posts"]}
    posted = json.loads(POSTED.read_text(encoding="utf-8"))
    p = posts.get(day)
    if not p or not p.get("youtube", True):
        print(f"📭 {day} の YouTube の予定はなし"); return
    if day in posted:
        print(f"✅ {day} はもう投稿済み"); return
    video = ROOT / "video/files" / p["file"]
    if not video.exists():
        fail(f"動画がない: {video}")
    title = p["yt_title"][:100]
    desc = p.get("yt_description", "")
    if os.environ.get("DRY_RUN") == "1":
        print(f"🧪 [DRY RUN] {day} YouTube: {video.name}\nタイトル: {title}\n{desc}\nタグ: {p.get('yt_tags', [])}"); return
    cid, sec, rt = (os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))
    if not (cid and sec and rt):
        print("ℹ️ YouTube の鍵がまだ登録されていないので何もしない"); return

    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": cid, "client_secret": sec, "refresh_token": rt, "grant_type": "refresh_token"})
    if r.status_code != 200: fail(f"ログインに失敗（鍵の期限切れかも）{r.status_code} {r.text}")
    access = r.json()["access_token"]
    meta = {
        "snippet": {"title": title, "description": desc, "tags": p.get("yt_tags", []),
                    "categoryId": p.get("yt_category", "22"), "defaultLanguage": p.get("yt_lang", "en")},
        "status": {"privacyStatus": p.get("yt_privacy", "public"), "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": p.get("ai_generated", True)},
    }
    data = video.read_bytes()
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      timeout=60, json=meta, headers={"Authorization": f"Bearer {access}",
                      "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(data))})
    if r.status_code != 200: fail(f"アップロード開始に失敗 {r.status_code} {r.text}")
    r = requests.put(r.headers["Location"], data=data, timeout=900, headers={"Content-Type": "video/mp4"})
    if r.status_code not in (200, 201): fail(f"アップロードに失敗 {r.status_code} {r.text}")
    v = r.json()
    print(f"✅ YouTube に投稿: https://youtube.com/shorts/{v['id']} 公開設定={v['status']['privacyStatus']}")
    posted[day] = {"id": v["id"], "file": p["file"], "privacy": v["status"]["privacyStatus"]}
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
