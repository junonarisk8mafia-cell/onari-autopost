"""
1週間分の投稿予定を、実際には投稿せずにチェックする。

使い方:  python tools/check_week.py 2026-11-02 7
  - Instagram: キューの順番で1日1本ずつ。メディアとキャプションの組、文字数、タグ数、動画の形式
  - Threads  : threads/posts.json の日付ごと。500文字以内、タグは1つまで
  - X        : x/posts.json の日付ごと。本文・ツリーとも280（日本語は1文字2）以内、画像の有無
問題があれば最後に一覧で出して、終了コード1で終わる。
"""

import json
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "posts/queue"
problems = []


def x_weight(text):
    """X の文字数の数え方（ざっくり）：日本語・全角は2、URLは23、それ以外は1"""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    n = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) > 0x2E80:
            n += 2
        else:
            n += 1
    return n


def probe(path):
    if not shutil.which("ffprobe"):
        return None
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height",
                          "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(out.stdout or "{}")


def check_instagram(days):
    media = sorted(p for p in QUEUE.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".mp4"))
    captions = sorted(QUEUE.glob("*.txt"))
    ready = [m for m in media if m.with_suffix(".txt").exists()]
    waiting = [c for c in captions if not any(c.with_suffix(e).exists() for e in (".jpg", ".jpeg", ".mp4"))]
    # 今日の分（1本）がまだ queue にあるなら、それは今日出る
    print("\n=== Instagram（キューの順番で1日1本） ===")
    order = ready + []
    for i, d in enumerate(days):
        if i < len(order):
            m = order[i]
            cap = m.with_suffix(".txt").read_text(encoding="utf-8")
            tags = re.findall(r"#\S+", cap)
            info = ""
            if m.suffix == ".mp4":
                p = probe(m)
                if p:
                    v = next((s for s in p.get("streams", []) if s["codec_type"] == "video"), {})
                    a = next((s for s in p.get("streams", []) if s["codec_type"] == "audio"), None)
                    dur = float(p.get("format", {}).get("duration", 0))
                    info = f"{v.get('width')}x{v.get('height')} {dur:.1f}秒 {'音あり' if a else '音なし'}"
                    if (v.get("width"), v.get("height")) != (1080, 1920):
                        problems.append(f"Instagram {m.name}: 縦長1080x1920ではない")
                    if not (3 <= dur <= 90):
                        problems.append(f"Instagram {m.name}: 長さ{dur:.1f}秒（3〜90秒にする）")
                    if a is None:
                        problems.append(f"Instagram {m.name}: 音がない")
            if len(cap) > 2200:
                problems.append(f"Instagram {m.name}: キャプション{len(cap)}文字（2200まで）")
            if len(tags) > 30:
                problems.append(f"Instagram {m.name}: タグ{len(tags)}個（30まで）")
            first = cap.strip().splitlines()[0]
            print(f"{d}  {m.name}  {info}  キャプション{len(cap)}字 タグ{len(tags)}個 「{first}」")
        else:
            print(f"{d}  ⚠️ 投稿できるネタがない")
            problems.append(f"Instagram {d}: 投稿できるネタがない（メディアとキャプションの組が足りない）")
    for c in waiting:
        print(f"   ⏳ {c.name} はキャプションだけ。動画（{c.stem}.mp4）待ち")


def check_threads(days):
    print("\n=== Threads（日付ごと・文章だけ） ===")
    posts = {p["date"]: p for p in json.loads((ROOT / "threads/posts.json").read_text(encoding="utf-8"))["posts"]}
    for d in days:
        p = posts.get(d)
        if not p:
            print(f"{d}  （予定なし）")
            continue
        t = p["text"]
        tags = re.findall(r"#\S+", t)
        print(f"{d}  {len(t)}字 タグ{len(tags)}個 「{t.splitlines()[0]}」")
        if len(t) > 500:
            problems.append(f"Threads {d}: {len(t)}文字（500まで）")
        if len(tags) > 1:
            problems.append(f"Threads {d}: タグ{len(tags)}個（1つまで）")


def check_x(days):
    print("\n=== X（日付ごと・本文＋ツリー） ===")
    posts = {p["date"]: p for p in json.loads((ROOT / "x/posts.json").read_text(encoding="utf-8"))["posts"]}
    for d in days:
        p = posts.get(d)
        if not p:
            print(f"{d}  （予定なし）")
            continue
        parts = [p["text"]] + p.get("replies", [])
        ws = [x_weight(t) for t in parts]
        img = p.get("image")
        print(f"{d}  {p['title']}  文字数(重み) {ws}  画像:{img or 'なし'}")
        for i, w in enumerate(ws):
            if w > 280:
                problems.append(f"X {d}: {'本文' if i == 0 else f'ツリー{i}'}が{w}（280まで）")
        if img and not (ROOT / img).exists():
            problems.append(f"X {d}: 画像 {img} がない")


def main():
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    days = [(start + timedelta(days=i)).isoformat() for i in range(n)]
    check_instagram(days)
    check_threads(days)
    check_x(days)
    print("\n=== 結果 ===")
    if problems:
        for p in problems:
            print("❌", p)
        sys.exit(1)
    print("✅ 問題なし")


if __name__ == "__main__":
    main()
