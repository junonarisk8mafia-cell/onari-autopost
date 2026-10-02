"""
Onari Auto Post - Instagram 自動投稿ボット

posts/queue/ にある「画像(.jpg) + キャプション(.txt)」のペアを
ファイル名順に1件だけ Instagram に投稿し、投稿済みは posts/done/ へ移動する。

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


def find_next_post():
    """queue の中から、画像とキャプションが揃っている一番古いものを返す"""
    images = sorted(p for p in QUEUE.glob("*") if p.suffix.lower() in (".jpg", ".jpeg"))
    for img in images:
        caption_file = img.with_suffix(".txt")
        if caption_file.exists():
            return img, caption_file
        print(f"⚠️ キャプションがないのでスキップ: {img.name}")
    return None, None


def public_image_url(img: Path) -> str:
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{img.as_posix()}"


def create_container(user_id, token, image_url, caption):
    r = requests.post(
        f"{BASE}/{user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=60,
    )
    if not r.ok:
        sys.exit(f"❌ 投稿の準備に失敗: {r.status_code} {r.text}")
    return r.json()["id"]


def wait_until_ready(container_id, token, tries=10):
    """Instagram 側で画像の処理が終わるまで待つ"""
    for _ in range(tries):
        r = requests.get(
            f"{BASE}/{container_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=30,
        )
        status = r.json().get("status_code") if r.ok else None
        if status == "FINISHED":
            return
        if status == "ERROR":
            sys.exit(f"❌ Instagram 側で画像の処理に失敗: {r.text}")
        time.sleep(5)
    sys.exit("❌ 画像の処理が時間内に終わらなかった")


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

    img, caption_file = find_next_post()
    if img is None:
        print("📭 投稿待ちのネタがないので、今日は何もしない")
        return

    caption = caption_file.read_text(encoding="utf-8").strip()
    url = public_image_url(img)
    print(f"📤 投稿します: {img.name}")

    container_id = create_container(user_id, token, url, caption)
    wait_until_ready(container_id, token)
    media_id = publish(user_id, token, container_id)
    print(f"✅ 投稿完了！ media id: {media_id}")

    DONE.mkdir(parents=True, exist_ok=True)
    shutil.move(str(img), DONE / img.name)
    shutil.move(str(caption_file), DONE / caption_file.name)


if __name__ == "__main__":
    main()
