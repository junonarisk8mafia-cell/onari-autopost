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
from pathlib import Path

import requests

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
BASE = f"https://graph.instagram.com/{API_VERSION}"

QUEUE = Path("posts/queue")
DONE = Path("posts/done")

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


def main():
    token = os.environ["IG_TOKEN"]
    user_id = os.environ["IG_USER_ID"]

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

    DONE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(media), DONE / media.name)
    shutil.move(str(caption_file), DONE / caption_file.name)
    # queue フォルダが空になって消えないように目印を置いておく
    (QUEUE / ".gitkeep").touch()


if __name__ == "__main__":
    main()
