"""
Onari Auto Post - Instagram 自動投稿ボット（画像＋リール対応版）

posts/queue/ にある「画像(.jpg) か 動画(.mp4)」＋「キャプション(.txt)」のペアを
ファイル名順に1件だけ Instagram に投稿し、投稿済みは posts/done/ へ移動する。
  - 008.jpg + 008.txt → 画像投稿
  - 009.mp4 + 009.txt → リール投稿（フィードにも表示）

必要な環境変数（GitHub の Secrets に登録）:
  IG_TOKEN    : Meta で発行したアクセストークン
  IG_USER_ID  : Instagram のユーザーID（数字）
自動で入るもの（GitHub Actions が用意）:
  GITHUB_REPOSITORY : "owner/repo"
"""

import os
import sys
import time
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
BASE = f"https://graph.instagram.com/{API_VERSION}"

QUEUE = Path("posts/queue")
DONE = Path("posts/done")
LAST = Path("posts/last_posted.txt")
JST = timezone(timedelta(hours=9))
EARLIEST_HOUR = 5  # 朝5時より前は投稿しない

IMAGE_EXT = (".jpg", ".jpeg")
VIDEO_EXT = (".mp4",)


def find_next_post():
    """queue の中から、メディアとキャプションが揃っている一番若い番号を返す"""
    media = sorted(p for p in QUEUE.glob("*") if p.suffix.lower() in IMAGE_EXT + VIDEO_EXT)
    for m in media:
        caption_file = m.with_suffix(".txt")
        if caption_file.exists():
            return m, caption_file
        print(f"⚠️ キャプションがないのでスキップ: {m.name}")
    return None, None


def public_url(path: Path) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path.as_posix()}"


def create_container(user_id, token, media: Path, caption):
    data = {"caption": caption, "access_token": token}
    if media.suffix.lower() in VIDEO_EXT:
        data.update({"media_type": "REELS", "video_url": public_url(media), "share_to_feed": "true"})
    else:
        data.update({"image_url": public_url(media)})
    r = requests.post(f"{BASE}/{user_id}/media", data=data, timeout=60)
    if not r.ok:
        sys.exit(f"❌ 投稿の準備に失敗: {r.status_code} {r.text}")
    return r.json()["id"]


def wait_until_ready(container_id, token, is_video):
    """Instagram 側で処理が終わるまで待つ（動画は時間がかかるので長めに待つ）"""
    tries, interval = (40, 10) if is_video else (10, 5)
    for _ in range(tries):
        r = requests.get(
            f"{BASE}/{container_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        status = r.json().get("status_code") if r.ok else None
        if status == "FINISHED":
            return
        if status == "ERROR":
            sys.exit(f"❌ Instagram 側で処理に失敗: {r.text}")
        time.sleep(interval)
    sys.exit("❌ 処理が時間内に終わらなかった")


def publish(user_id, token, container_id):
    r = requests.post(
        f"{BASE}/{user_id}/media_publish",
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    if not r.ok:
        sys.exit(f"❌ 公開に失敗: {r.status_code} {r.text}")
    return r.json()["id"]


THREADS_BASE = "https://graph.threads.net/v1.0"
THREADS_TAG = "#借金溶接工の逆転日記"


def threads_text(caption: str) -> str:
    """Threads はタグが1投稿1個までなので、ハッシュタグ行を外してタグを1つだけ付ける"""
    lines = [l for l in caption.splitlines() if not l.strip().startswith("#")]
    body = "\n".join(lines).strip()
    text = f"{body}\n\n{THREADS_TAG}"
    return text[:500]


def post_to_threads(media: Path, caption: str):
    """Threads にも同じ内容を投稿する。設定がない・失敗しても Instagram 側には影響させない"""
    token = os.environ.get("THREADS_TOKEN")
    # ユーザーIDが未登録なら "me"（トークンの持ち主）で投稿する
    user_id = os.environ.get("THREADS_USER_ID") or "me"
    if not token:
        print("ℹ️ Threads の設定がないので、Threads はスキップ")
        return
    try:
        is_video = media.suffix.lower() in VIDEO_EXT
        data = {"text": threads_text(caption), "access_token": token}
        if is_video:
            data.update({"media_type": "VIDEO", "video_url": public_url(media)})
        else:
            data.update({"media_type": "IMAGE", "image_url": public_url(media)})
        r = requests.post(f"{THREADS_BASE}/{user_id}/threads", data=data, timeout=60)
        if not r.ok:
            print(f"⚠️ Threads の準備に失敗: {r.status_code} {r.text}")
            return
        cid = r.json()["id"]
        tries, interval = (40, 10) if is_video else (10, 5)
        for _ in range(tries):
            s = requests.get(f"{THREADS_BASE}/{cid}",
                             params={"fields": "status,error_message", "access_token": token}, timeout=30)
            status = s.json().get("status") if s.ok else None
            if status == "FINISHED":
                break
            if status == "ERROR":
                print(f"⚠️ Threads 側で処理に失敗: {s.text}")
                return
            time.sleep(interval)
        else:
            print("⚠️ Threads の処理が時間内に終わらなかった")
            return
        p = requests.post(f"{THREADS_BASE}/{user_id}/threads_publish",
                          data={"creation_id": cid, "access_token": token}, timeout=60)
        if not p.ok:
            print(f"⚠️ Threads の公開に失敗: {p.status_code} {p.text}")
            return
        print(f"✅ Threads にも投稿完了！ id: {p.json().get('id')}")
    except Exception as e:  # Threads の不具合で Instagram の記録が壊れないようにする
        print(f"⚠️ Threads でエラー: {e}")


def main():
    token = os.environ["IG_TOKEN"]
    user_id = os.environ["IG_USER_ID"]

    # 手動実行（Run workflow）のときは、時間と1日1本のチェックを飛ばす
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    if not manual:
        if now.hour < EARLIEST_HOUR:
            print(f"🌙 まだ{now:%H:%M}。朝{EARLIEST_HOUR}時までは待つ")
            return
        if LAST.exists() and LAST.read_text().strip() == today:
            print("✅ 今日はもう投稿済みなので、何もしない")
            return

    media, caption_file = find_next_post()
    if media is None:
        print("📭 投稿待ちのネタがないので、今日は何もしない")
        return

    is_video = media.suffix.lower() in VIDEO_EXT
    caption = caption_file.read_text(encoding="utf-8").strip()
    print(f"📤 投稿します（{'リール' if is_video else '画像'}）: {media.name}")

    container_id = create_container(user_id, token, media, caption)
    wait_until_ready(container_id, token, is_video)
    media_id = publish(user_id, token, container_id)
    print(f"✅ 投稿完了！ media id: {media_id}")

    # done/ へ移動する前に（同じURLのまま）Threads にも投稿する
    post_to_threads(media, caption)

    DONE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(media), DONE / media.name)
    shutil.move(str(caption_file), DONE / caption_file.name)
    # queue フォルダが空になって消えないように目印を置いておく
    (QUEUE / ".gitkeep").touch()
    LAST.write_text(today)


if __name__ == "__main__":
    main()
