"""
Facebook ページとリールの成績を集める係（投稿はしない、読むだけ）。
結果は video/fb_stats.json に保存する。
必要な鍵: FB_PAGE_ID / FB_PAGE_TOKEN（投稿botと同じ）
"""
import json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from fb_post import page_token, GRAPH

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "video/fb_stats.json"
JST = timezone(timedelta(hours=9))


def get(path, token, **params):
    params["access_token"] = token
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=60)
    try:
        j = r.json()
    except Exception:
        j = {"error": {"message": r.text[:300]}}
    if "error" in j:
        return {"_error": j["error"].get("message", "")[:300]}
    return j


def main():
    page, token = os.environ.get("FB_PAGE_ID"), os.environ.get("FB_PAGE_TOKEN")
    if not page or not token:
        sys.exit("FB_PAGE_ID / FB_PAGE_TOKEN が登録されていない")
    pt, _ = page_token(page, token)
    out = {"fetched_at": datetime.now(JST).isoformat(timespec="minutes")}
    out["page"] = get(page, pt, fields="name,followers_count,fan_count,link")
    out["page_insights"] = get(f"{page}/insights", pt,
                               metric="page_impressions_unique,page_post_engagements,page_video_views,page_follows,page_daily_follows_unique,page_views_total",
                               period="day", since=(datetime.now(JST) - timedelta(days=10)).date().isoformat())

    # 投稿済みリール（botの記録＋ページにあるリール全部）
    ids = {}
    posted = json.loads((ROOT / "video/posted_facebook.json").read_text(encoding="utf-8"))
    for day, v in posted.items():
        ids[v["video_id"]] = {"date": day, "file": v.get("file")}
    reels = get(f"{page}/video_reels", pt, fields="id,description,created_time,length,permalink_url", limit=50)
    for v in reels.get("data", []) if isinstance(reels, dict) else []:
        ids.setdefault(v["id"], {})["created_time"] = v.get("created_time")
    if "_error" in reels:
        out["video_reels_error"] = reels["_error"]

    vids = []
    for vid, meta in ids.items():
        info = get(vid, pt, fields="title,description,created_time,length,permalink_url,"
                   "likes.summary(true).limit(0),comments.summary(true).limit(0)")
        ins = get(f"{vid}/video_insights", pt)
        metrics = {}
        if isinstance(ins, dict) and "data" in ins:
            for m in ins["data"]:
                vals = m.get("values") or [{}]
                metrics[m["name"]] = vals[0].get("value")
        vids.append({
            "id": vid, **meta,
            "created_time": info.get("created_time"),
            "length": info.get("length"),
            "permalink": info.get("permalink_url"),
            "description": (info.get("description") or "")[:120],
            "likes": (info.get("likes") or {}).get("summary", {}).get("total_count"),
            "comments": (info.get("comments") or {}).get("summary", {}).get("total_count"),
            "insights": metrics,
            "errors": {k: v["_error"] for k, v in {"info": info, "insights": ins}.items() if isinstance(v, dict) and "_error" in v},
        })
    out["reels"] = sorted(vids, key=lambda v: v.get("created_time") or "")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("page",)}, ensure_ascii=False))
    for v in out["reels"]:
        print(v.get("date"), v.get("file"), {k: v["insights"].get(k) for k in list(v["insights"])[:6]}, v["errors"] or "")


if __name__ == "__main__":
    main()
