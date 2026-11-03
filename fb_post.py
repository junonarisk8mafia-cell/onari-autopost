"""
Facebook ページにリールを投稿する係。

video/schedule.json の今日（日本時間）の分を、Facebook ページのリールとして出す。
必要な鍵（GitHub の Secrets）:
  FB_PAGE_ID     : Facebook ページのID（数字）
  FB_PAGE_TOKEN  : ページのアクセストークン（pages_manage_posts など付き、期限なしのもの）
テスト: DRY_RUN=1 で、投稿せずに中身だけ表示。FB_POST_DATE=YYYY-MM-DD で日付を指定。
"""
import json, os, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
SCHED = ROOT / "video/schedule.json"
POSTED = ROOT / "video/posted_facebook.json"
VER = os.environ.get("FB_API_VERSION", "v26.0")
GRAPH = f"https://graph.facebook.com/{VER}"
RUP = f"https://rupload.facebook.com/video-upload/{VER}"


def today():
    return os.environ.get("FB_POST_DATE") or (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()


def fail(msg):
    print(f"::error title=Facebook post failed::{msg[:300]}")
    sys.exit(f"❌ {msg}")


def main():
    day = today()
    posts = {p["date"]: p for p in json.loads(SCHED.read_text(encoding="utf-8"))["posts"]}
    posted = json.loads(POSTED.read_text(encoding="utf-8"))
    p = posts.get(day)
    if not p or not p.get("facebook", True):
        print(f"📭 {day} の Facebook の予定はなし"); return
    if day in posted:
        print(f"✅ {day} はもう投稿済み"); return
    video = ROOT / "video/files" / p["file"]
    desc = p.get("fb_description") or p.get("description", "")
    if not video.exists():
        fail(f"動画がない: {video}")
    if os.environ.get("DRY_RUN") == "1":
        print(f"🧪 [DRY RUN] {day} Facebook リール: {video.name} ({video.stat().st_size//1024} KB)\n{desc}"); return
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not page or not token:
        print("ℹ️ FB_PAGE_ID / FB_PAGE_TOKEN がまだ登録されていないので何もしない"); return

    r = requests.post(f"{GRAPH}/{page}/video_reels", json={"upload_phase": "start", "access_token": token}, timeout=60)
    if r.status_code != 200: fail(f"開始に失敗 {r.status_code} {r.text}")
    vid = r.json()["video_id"]
    data = video.read_bytes()
    r = requests.post(f"{RUP}/{vid}", data=data, timeout=600, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data)),
        "Content-Type": "application/octet-stream"})
    if r.status_code != 200 or not r.json().get("success"): fail(f"アップロードに失敗 {r.status_code} {r.text}")
    r = requests.post(f"{GRAPH}/{page}/video_reels", timeout=60, data={
        "access_token": token, "video_id": vid, "upload_phase": "finish", "video_state": "PUBLISHED",
        "description": desc, "is_ai_generated": "true" if p.get("ai_generated", True) else "false"})
    if r.status_code != 200 or not r.json().get("success"): fail(f"公開に失敗 {r.status_code} {r.text}")
    for _ in range(30):
        time.sleep(10)
        s = requests.get(f"{GRAPH}/{vid}", params={"fields": "status", "access_token": token}, timeout=30).json()
        st = s.get("status", {}).get("video_status")
        print("…", st)
        if st in ("ready", "published"): break
        if st in ("error", "upload_failed", "expired"): fail(f"処理に失敗 {s}")
    posted[day] = {"video_id": vid, "file": p["file"]}
    POSTED.write_text(json.dumps(posted, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ Facebook に投稿: video_id={vid}")


if __name__ == "__main__":
    main()
