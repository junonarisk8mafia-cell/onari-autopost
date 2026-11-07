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
JST = timezone(timedelta(hours=9))
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


def page_token(page, token):
    """ユーザー用の鍵が入っていても、そこからページ用の鍵を取り出して使う"""
    me = requests.get(f"{GRAPH}/me", params={"fields": "id", "access_token": token}, timeout=30).json()
    if str(me.get("id")) == str(page):
        return token, False
    r = requests.get(f"{GRAPH}/{page}", params={"fields": "access_token", "access_token": token}, timeout=30).json()
    if not r.get("access_token"):
        fail(f"ページ用の鍵を取り出せない {str(r)[:200]}")
    return r["access_token"], True


def check():
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not page or not token: fail("FB_PAGE_ID / FB_PAGE_TOKEN が登録されていない")
    r = requests.get(f"{GRAPH}/{page}", params={"fields": "id,name", "access_token": token}, timeout=30)
    if r.status_code != 200: fail(f"ページに届かない {r.status_code} {r.text}")
    print(f"✅ ページに接続できた: {r.json().get('name')}")
    raw = requests.get(f"{GRAPH}/debug_token", params={"input_token": token, "access_token": token}, timeout=30).json()
    d = raw.get("data", {})
    if not d: print(f"::warning title=debug_token::{str(raw)[:250]}")
    me = requests.get(f"{GRAPH}/me", params={"fields": "id,name", "access_token": token}, timeout=30).json()
    print(f"::warning title=この鍵の持ち主::{me.get('name')} ({me.get('id')}) type={d.get('type')} expires={d.get('expires_at')}")
    exp = d.get("expires_at")
    print(f"種類: {d.get('type')}  期限: {'なし' if not exp else exp}  権限: {', '.join(d.get('scopes', []))}")
    pt, derived = page_token(page, token)
    who = requests.get(f"{GRAPH}/me", params={"fields": "id,name", "access_token": pt}, timeout=30).json()
    print(f"::warning title=投稿に使う鍵::{who.get('name')} ({who.get('id')}) {'ユーザーの鍵から自動で取り出した' if derived else 'ページの鍵'}")
    if str(who.get("id")) != str(page): fail("ページとして投稿できない")
    if exp: print(f"::warning title=期限あり::この鍵には期限がある（{exp}）。長期の鍵から作り直すと期限なしになる")


def main():
    if os.environ.get("CHECK") == "1":
        return check()
    now = datetime.now(JST)
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and now.hour < 19:
        print(f"🌙 まだ{now:%H:%M}（日本）。19時（フィリピン18時）までは待つ"); return
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
    token, _ = page_token(page, token)

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
