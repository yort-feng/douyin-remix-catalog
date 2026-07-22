#!/usr/bin/env python3
"""
Fill poster_url for data/{platform}.json items by querying each platform's
public search API (pure HTTP, no phone mirroring needed).

Platform endpoints + field paths (verified 2026-07-22):
  iqiyi : https://suggest.video.iqiyi.com/?if=mobile&key={title}
           -> data[].name  (title) , data[].presentation_element.picture_url (poster)
  youku  : https://search.youku.com/api/search?keyword={title}&pg=1  (Referer: youku.com)
           -> pageComponentList[].commonData.posterDTO.vThumbUrl (poster)
              pageComponentList[].commonData.titleDTO.displayName (title)
  mango  : https://mobileso.bz.mgtv.com/applet/search/v1?q={title}
           -> data.contents[].data[].img (poster) , .title/.hit (title, strip <B>)

Matching: returned title must match query (exact or fuzzy ratio >= THRESHOLD).
Fuzzy-matching also picks the BEST candidate per query. Unmatched -> skip (keep null).

Output: web/public/posters/{platform}/{id}.webp (300x450, WebP q~70, <=20KB)
        data/{platform}.json item.poster_url = /douyin-remix-catalog/posters/{platform}/{id}.webp

Usage:
  python3 fill_posters_http.py [--platform iqiyi|youku|mango] [--limit N] [--sleep S] [--no-write]
"""
import json, os, sys, time, re, io, ssl, argparse, difflib
import urllib.request as urllib_request
import urllib.parse as urllib_parse
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
OUT = os.path.join(REPO, "web", "public", "posters")
SCHEMA_BASE = "/douyin-remix-catalog"

PLATFORMS = ["iqiyi", "youku", "mango"]
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

MATCH_TH = 0.82
MAX_W = 300
TARGET_RATIO = 2 / 3  # w:h
QUALITY = 70
MAX_BYTES = 20480  # 20KB


def http_get(url, headers=None, timeout=30, retries=2):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib_request.Request(url, headers=headers or {"User-Agent": UA})
            return urllib_request.urlopen(req, timeout=timeout, context=CTX).read()
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5)
    return None


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"<[^>]+>", "", s)  # strip <B> highlight tags
    s = re.sub(r"[\s\-:：·,，。.！!?？、_~～()（）\[\]【】\"\']+", "", s)
    return s


def match(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return max(0.5, difflib.SequenceMatcher(None, a, b).ratio())
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------- per-platform extractors ----------------
# Each returns the BEST (title, poster_url) tuple by match score, or (None, None).
def extract_iqiyi(q):
    raw = http_get(f"https://suggest.video.iqiyi.com/?if=mobile&key={urllib_parse.quote(q)}")
    if not raw:
        return None, None
    try:
        d = json.loads(raw)
    except Exception:
        return None, None
    best, bs = None, 0.0
    for it in d.get("data", []):
        nm = it.get("name", "")
        pic = it.get("presentation_element", {}).get("picture_url") or it.get("picture_url")
        if not (nm and pic):
            continue
        sc = match(q, nm)
        if sc > bs:
            bs, best = sc, (nm, pic)
    return best or (None, None)


def extract_youku(q):
    raw = http_get(
        f"https://search.youku.com/api/search?keyword={urllib_parse.quote(q)}&pg=1",
        headers={"User-Agent": UA, "Referer": "https://www.youku.com/"},
    )
    if not raw:
        return None, None
    try:
        d = json.loads(raw)
    except Exception:
        return None, None
    best, bs = None, 0.0
    for c in d.get("pageComponentList", []):
        cd = c.get("commonData", {})
        pic = cd.get("posterDTO", {}).get("vThumbUrl")
        nm = cd.get("titleDTO", {}).get("displayName") or cd.get("titleDTO", {}).get("title")
        if not (nm and pic):
            continue
        sc = match(q, nm)
        if sc > bs:
            bs, best = sc, (nm, pic)
    return best or (None, None)


def extract_mango(q):
    raw = http_get(f"https://mobileso.bz.mgtv.com/applet/search/v1?q={urllib_parse.quote(q)}")
    if not raw:
        return None, None
    try:
        d = json.loads(raw)
    except Exception:
        return None, None
    best, bs = None, 0.0
    for c in d.get("data", {}).get("contents", []):
        for it in c.get("data", []):
            nm = it.get("title") or re.sub(r"<[^>]+>", "", it.get("hit", "") or "")
            img = it.get("img")
            if not (nm and img):
                continue
            sc = match(q, nm)
            if sc > bs:
                bs, best = sc, (nm, img)
    return best or (None, None)


EXTRACT = {"iqiyi": extract_iqiyi, "youku": extract_youku, "mango": extract_mango}


# ---------------- image processing ----------------
def make_webp(raw_bytes):
    img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    W, H = img.size
    cur = W / H
    if cur > TARGET_RATIO:
        nw = int(H * TARGET_RATIO)
        nx = (W - nw) // 2
        img = img.crop((nx, 0, nx + nw, H))
    elif cur < TARGET_RATIO:
        nh = int(W / TARGET_RATIO)
        ny = (H - nh) // 2
        img = img.crop((0, ny, W, ny + nh))
    q = QUALITY
    while True:
        buf = io.BytesIO()
        img.resize((MAX_W, int(MAX_W / TARGET_RATIO)), Image.LANCZOS).save(buf, "WEBP", quality=q)
        if buf.tell() <= MAX_BYTES or q <= 30:
            return buf.getvalue(), buf.tell()
        q -= 5


# ---------------- main ----------------
def run_platform(p, limit=None, sleep=0.35, write=True):
    fn = EXTRACT[p]
    path = os.path.join(DATA, f"{p}.json")
    data = json.load(open(path, encoding="utf-8"))
    items = data["items"]
    outdir = os.path.join(OUT, p)
    os.makedirs(outdir, exist_ok=True)

    filled = skipped = err = 0
    changed = False
    n = limit if limit else len(items)
    t0 = time.time()
    for idx, it in enumerate(items[:n]):
        iid = it["id"]
        q = it["title"]
        outp = os.path.join(outdir, f"{iid}.webp")

        # resume: already done (in JSON or file exists)
        if it.get("poster_url") and os.path.exists(outp):
            filled += 1
            continue
        # already has poster_url but file missing -> re-download path not needed; skip
        if it.get("poster_url") and not os.path.exists(outp):
            # try to re-fetch if we somehow lost the file
            pass

        nm, pic = fn(q)
        if not pic or match(q, nm) < MATCH_TH:
            skipped += 1
            continue
        raw = http_get(pic, headers={"User-Agent": UA, "Referer": pic})
        if not raw:
            err += 1
            continue
        try:
            webp, size = make_webp(raw)
        except Exception as e:  # noqa
            sys.stderr.write(f"  [img-err] {p}/{iid}: {e!r}\n")
            err += 1
            continue
        if write:
            with open(outp, "wb") as f:
                f.write(webp)
            it["poster_url"] = f"{SCHEMA_BASE}/posters/{p}/{iid}.webp"
            changed = True
        filled += 1
        if (idx + 1) % 50 == 0:
            if write and changed:
                json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
                changed = False
            dt = time.time() - t0
            print(f"  [{p}] {idx+1}/{n}  ok={filled} skip={skipped} err={err}  {dt:.0f}s", flush=True)
        time.sleep(sleep)

    if write and changed:
        json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f">>> {p}: filled={filled} skipped={skipped} err={err}  (of {n})", flush=True)
    return filled, skipped, err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", choices=PLATFORMS, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    plats = [a.platform] if a.platform else PLATFORMS
    for p in plats:
        print(f"=== {p} ===", flush=True)
        run_platform(p, limit=a.limit, sleep=a.sleep, write=not a.no_write)


if __name__ == "__main__":
    main()
