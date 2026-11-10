"""
Instagram / Threads / Facebook の成績をまとめて集める係（読むだけ、投稿しない）。
結果: stats/latest.json と stats/YYYY-MM-DD.json
鍵: IG_TOKEN, IG_USER_ID, THREADS_TOKEN, THREADS_USER_ID, FB_PAGE_ID, FB_PAGE_TOKEN（投稿botと同じ）
"""
import json, os, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)


def get(url, **params):
    try:
        r = requests.get(url, params=params, timeout=60)
        j = r.json()
    except Exception as e:
        return {"_error": str(e)[:200]}
    if isinstance(j, dict) and "error" in j:
        return {"_error": (j["error"].get("message") or "")[:300]}
    return j


def instagram():
    tok, uid = os.environ.get("IG_TOKEN"), os.environ.get("IG_USER_ID") or "me"
    if not tok:
        return {"_error": "IG_TOKEN なし"}
    B = "https://graph.instagram.com/v23.0"
    out = {"account": get(f"{B}/{uid}", fields="username,followers_count,media_count", access_token=tok)}
    media = get(f"{B}/{uid}/media", fields="id,caption,timestamp,media_type,permalink,like_count,comments_count",
                limit=30, access_token=tok)
    rows = []
    for m in media.get("data", []) if isinstance(media, dict) else []:
        ins = get(f"{B}/{m['id']}/insights", metric="views,reach,likes,comments,shares,saved,total_interactions",
                  access_token=tok)
        met = {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value"))
               for d in ins.get("data", [])} if "data" in ins else {"_error": ins.get("_error")}
        rows.append({"id": m["id"], "time": m.get("timestamp"), "type": m.get("media_type"),
                     "caption": (m.get("caption") or "")[:60].replace("\n", " "), "permalink": m.get("permalink"),
                     "likes": m.get("like_count"), "comments": m.get("comments_count"), "insights": met})
    if "_error" in media:
        out["media_error"] = media["_error"]
    out["media"] = rows
    return out


def threads():
    tok, uid = os.environ.get("THREADS_TOKEN"), os.environ.get("THREADS_USER_ID") or "me"
    if not tok:
        return {"_error": "THREADS_TOKEN なし"}
    B = "https://graph.threads.net/v1.0"
    out = {"account": get(f"{B}/{uid}/threads_insights", metric="views,likes,replies,followers_count",
                          access_token=tok)}
    posts = get(f"{B}/{uid}/threads", fields="id,text,timestamp,permalink", limit=30, access_token=tok)
    rows = []
    for p in posts.get("data", []) if isinstance(posts, dict) else []:
        ins = get(f"{B}/{p['id']}/insights", metric="views,likes,replies,reposts,quotes,shares", access_token=tok)
        met = {d["name"]: (d.get("values") or [{}])[0].get("value", d.get("total_value", {}).get("value"))
               for d in ins.get("data", [])} if "data" in ins else {"_error": ins.get("_error")}
        rows.append({"id": p["id"], "time": p.get("timestamp"), "text": (p.get("text") or "")[:60].replace("\n", " "),
                     "permalink": p.get("permalink"), "insights": met})
    if "_error" in posts:
        out["posts_error"] = posts["_error"]
    out["posts"] = rows
    return out


def facebook():
    if not os.environ.get("FB_PAGE_TOKEN"):
        return {"_error": "FB_PAGE_TOKEN なし"}
    r = subprocess.run([sys.executable, "fb_stats.py"], cwd=ROOT, capture_output=True, text=True)
    try:
        return json.loads((ROOT / "video/fb_stats.json").read_text(encoding="utf-8"))
    except Exception:
        return {"_error": (r.stderr or r.stdout)[-300:]}


def main():
    data = {"fetched_at": NOW.isoformat(timespec="minutes"),
            "instagram": instagram(), "threads": threads(), "facebook": facebook()}
    d = ROOT / "stats"; d.mkdir(exist_ok=True)
    txt = json.dumps(data, ensure_ascii=False, indent=1)
    (d / "latest.json").write_text(txt, encoding="utf-8")
    (d / f"{NOW:%Y-%m-%d}.json").write_text(txt, encoding="utf-8")
    ig, th = data["instagram"], data["threads"]
    print("IG account:", ig.get("account"), "| media:", len(ig.get("media", [])), ig.get("media_error", ""))
    for m in ig.get("media", [])[:3]:
        print("  IG", m["time"], m["caption"][:20], m["insights"])
    print("TH account:", th.get("account") if "_error" not in th else th)
    for p in th.get("posts", [])[:3]:
        print("  TH", p["time"], p["text"][:20], p["insights"])


if __name__ == "__main__":
    main()
