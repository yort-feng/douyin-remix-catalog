#!/usr/bin/env python3
"""Fill Douban rating / cast / director for catalog items.

Douban's `subject_suggest` JSON endpoint is aggressively IP-throttled
(returns HTTP 200 with an empty array after ~15-20 requests and does not
recover quickly). Instead this uses the movie search page
`search.douban.com/movie/subject_search`, whose embedded
`window.__DATA__` JSON carries, per result:

    - title        e.g. "后宫·甄嬛传\u200e (2011)"  (year + LTR mark)
    - rating.value e.g. 9.4  (0 == not rated yet)
    - abstract     region / genre / aliases (used for alias matching)
    - abstract_2   "director / cast1 / cast2 / ..."
    - url          .../subject/{id}/

That search endpoint also throttles after ~6 rapid requests and can escalate
into a longer IP-level temp ban under heavy volume, so we pace requests
steadily (default >=10s) and retry isolated empties with a cooldown. Only one
request per title is needed (rating + people come from the same payload).

Matching is conservative: catalog titles often use the common/short name
(甄嬛传) while Douban uses the full name (后宫·甄嬛传), so we accept a
candidate when the query is a substring of the candidate title, matches an
alias, or is fuzzy-close (>=0.82). Among plausible candidates we take the
most-reviewed one (canonical version). If nothing is plausible we leave the
fields null -- we never fabricate.

Only fills items whose douban fields are all still null, so re-running
resumes past already-filled items.

Usage:
    python3 scripts/fill_douban_meta.py [--limit N] [--sleep S] [--platform P] [--commit]
"""
import json
import os
import re
import time
import difflib
import argparse
import urllib.request
import urllib.parse
import ssl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATFORMS = ["iqiyi", "youku", "mango"]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36")
HEADERS = {"User-Agent": UA, "Referer": "https://movie.douban.com/"}

_INVIS = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u00a0"
_CJK = re.compile(r"[\u4e00-\u9fff]")


def strip_invis(s):
    for ch in _INVIS:
        s = s.replace(ch, "")
    return s


def norm(s):
    """Normalize for matching: drop invisible chars, trailing year, season
    suffix, punctuation/whitespace; lowercase."""
    if not s:
        return ""
    s = strip_invis(str(s))
    s = re.sub(r"\(\d{4}\)\s*$", "", s)              # trailing (2017)
    s = re.sub(r"\s*第[一二三四五六七八九十\d]+季\s*$", "", s)  # 第X季
    s = re.sub(r"[\s\u3000]+", "", s)
    s = s.strip(" .,…。，：:·-_~～()（）[]【】\"'")
    return s.lower()


def clean_title(raw):
    """Human-readable clean title: drop invisible + trailing (year)."""
    s = strip_invis(str(raw or "")).strip()
    s = re.sub(r"\s*\(\d{4}\)\s*$", "", s)
    return s.strip()


def year_of(raw):
    m = re.search(r"\((\d{4})\)\s*$", strip_invis(str(raw or "")))
    return int(m.group(1)) if m else 0


def fuzzy(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def is_junk(title):
    """Obvious OCR noise / non-title -> don't waste a request."""
    if not title:
        return True
    t = strip_invis(title).strip()
    cjk = _CJK.findall(t)
    # fewer than 2 CJK chars and short -> junk (e.g. 'JDK 京东健康' has 4 -> not junk)
    if len(cjk) < 2 and len(t) <= 3:
        return True
    return False


def http_get(url, timeout=25):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout, context=CTX).read().decode("utf-8", "ignore")


def search_raw(title):
    """Return (items, total). `total` is Douban's reported result count;
    total==0 means either a genuine no-match OR an active throttle (both
    render the same empty page), so callers use consecutive-zero runs to
    detect throttling."""
    url = ("https://search.douban.com/movie/subject_search?search_text="
           + urllib.parse.quote(title) + "&cat=1002")
    body = http_get(url)
    m = re.search(r"window\.__DATA__\s*=\s*(\{.*?\});", body, re.S)
    items, total = [], 0
    if m:
        try:
            d = json.loads(m.group(1))
            items = d.get("items", []) or []
            total = d.get("total", 0) or 0
        except Exception:
            pass
    # keep only real subject rows (have title + subject url)
    items = [it for it in items
             if it.get("title") and "/subject/" in (it.get("url") or "")]
    return items, total


def pick(title, items):
    """Pick the best subject dict from search items, or None."""
    qn = norm(title)
    if not qn:
        return None
    plausible = []
    for it in items:
        cand = it.get("title", "")
        cn = norm(cand)
        if not cn:
            continue
        aliases = []
        for tok in re.split(r"[/·|]", it.get("abstract", "") or ""):
            tok = norm(tok)
            if _CJK.search(tok):
                aliases.append(tok)
        ok = (cn == qn or qn in cn or cn in qn
              or fuzzy(title, cand) >= 0.82
              or any(qn == a or (len(qn) >= 3 and qn in a) for a in aliases))
        if ok:
            rc = (it.get("rating") or {}).get("count") or 0
            plausible.append((rc, year_of(cand), it))
    if not plausible:
        return None
    # most-reviewed canonical version; tiebreak latest year
    plausible.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return plausible[0][2]


def people(it):
    parts = [p.strip() for p in (it.get("abstract_2") or "").split("/") if p.strip()]
    director = parts[0] if parts else None
    cast = parts[1:] if len(parts) > 1 else None
    return director, (cast or None)


def apply_meta(item, it):
    rating = (it.get("rating") or {}).get("value")
    item["douban_rating"] = float(rating) if rating else None
    d, c = people(it)
    item["director"] = d
    item["cast"] = c


class Fetcher:
    """Throttle-aware wrapper around search_raw.

    Douban's search page returns an empty payload (total==0, no items) both
    for a genuine no-match AND while the IP is soft-throttled (~after 5-6
    rapid requests, recovers in ~20s). We can't tell them apart from a single
    request, so we track consecutive empties: an isolated empty is treated as
    a real no-match (cheap), but a *run* of empties (>=2) is treated as a
    throttle -> cooldown and retry the same title. Titles that got an empty
    while a throttle episode was active are remembered so main() can re-run
    them once at the end (recovering the boundary victim of each episode)."""

    def __init__(self, base_sleep, log, cooldown=30.0):
        self.base_sleep = base_sleep
        self.log = log
        self.cooldown = cooldown
        self.consec_zero = 0
        self.throttle_episodes = 0

    def _raw(self, title):
        try:
            return search_raw(title)
        except Exception as e:
            self.log(f"  ! http error {title!r}: {e}")
            return [], 0

    def fetch(self, title):
        """Return (items, suspect) where suspect=True means the empty result
        may be a throttle boundary victim worth re-checking later."""
        items, total = self._raw(title)
        if items:
            self.consec_zero = 0
            return items, False
        # empty
        self.consec_zero += 1
        if self.consec_zero >= 2:
            self.throttle_episodes += 1
            self.log(f"  … {self.consec_zero} empties in a row -> "
                     f"throttle? cooldown {self.cooldown:.0f}s")
            time.sleep(self.cooldown)
            items, total = self._raw(title)
            if items:
                self.log("  ✓ recovered after cooldown")
                self.consec_zero = 0
                return items, False
            # still empty after a full recovery window -> genuine miss
            self.consec_zero = 0
            return [], False
        # isolated empty: probably genuine, but flag as a possible boundary
        # victim (the first zero of a throttle episode looks identical).
        return [], True


def _try_fill(it, results):
    chosen = pick(it.get("title") or "", results) if results else None
    if not chosen:
        return False
    apply_meta(it, chosen)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=3.0)
    ap.add_argument("--platform", default="")
    ap.add_argument("--commit", action="store_true",
                    help="git commit+push data files after each platform")
    args = ap.parse_args()

    platforms = [args.platform] if args.platform in PLATFORMS else PLATFORMS
    # Douban tolerates only ~5-6 rapid requests before throttling; a steady
    # >=10s pace avoids even the soft-throttle for long runs.
    base_sleep = max(10.0, args.sleep)

    def log(msg):
        print(msg, flush=True)

    for p in platforms:
        path = os.path.join(ROOT, "data", f"{p}.json")
        data = json.load(open(path, encoding="utf-8"))
        items = data["items"]
        total = len(items)
        filled = matched = skip_junk = no_match = 0
        processed = 0
        suspects = []          # (item, title) empties worth a 2nd pass
        fetcher = Fetcher(base_sleep, log)
        log(f"\n##### {p}: {total} items #####")
        for idx, it in enumerate(items, 1):
            # resume: skip already-filled
            if (it.get("douban_rating") is not None or it.get("cast") is not None
                    or it.get("director") is not None):
                continue
            if args.limit and processed >= args.limit:
                break
            processed += 1
            title = it.get("title") or ""
            if is_junk(title):
                skip_junk += 1
                continue
            results, suspect = fetcher.fetch(title)
            if _try_fill(it, results):
                matched += 1
                if it.get("douban_rating") is not None:
                    filled += 1
            else:
                no_match += 1
                if suspect:
                    suspects.append(it)
            if idx % 25 == 0:
                json.dump(data, open(path, "w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                log(f"  [{idx}/{total}] matched={matched} rated={filled} "
                    f"no_match={no_match} junk={skip_junk} (checkpoint)")
            time.sleep(base_sleep)

        # Second pass: only if throttling actually happened, re-check the
        # isolated empties (boundary victims of throttle episodes).
        if fetcher.throttle_episodes and suspects:
            log(f"  ~~ 2nd pass over {len(suspects)} suspect empties "
                f"({fetcher.throttle_episodes} throttle episodes seen)")
            fetcher.consec_zero = 0
            recovered = 0
            for it in suspects:
                title = it.get("title") or ""
                results, _ = fetcher.fetch(title)
                if _try_fill(it, results):
                    matched += 1
                    no_match -= 1
                    recovered += 1
                    if it.get("douban_rating") is not None:
                        filled += 1
                time.sleep(base_sleep)
            log(f"  ~~ 2nd pass recovered {recovered}")

        json.dump(data, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        log(f"  >>> {p} done: matched={matched} rated={filled} "
            f"no_match={no_match} junk={skip_junk}  (saved)")
        if args.commit and (matched or no_match):
            _git_commit(path, matched, filled,
                        fetcher.throttle_episodes, log)

    if args.commit:
        import subprocess
        try:
            subprocess.run(["git", "push", "origin",
                            "HEAD"], check=True, cwd=ROOT)
            log("  ✓ pushed to origin/HEAD")
        except Exception as e:
            log(f"  ! push failed: {e}")


def _git_commit(path, matched, filled, episodes, log):
    import subprocess
    try:
        subprocess.run(["git", "add", path], check=True, cwd=ROOT)
        msg = (f"data(douban): batch fill {os.path.basename(path)} "
               f"matched={matched} rated={filled}"
               + (f" (throttle episodes={episodes})" if episodes else ""))
        subprocess.run(["git", "commit", "-m", msg], check=True, cwd=ROOT)
        log(f"  ✓ committed {os.path.basename(path)}")
    except Exception as e:
        log(f"  ! commit failed: {e}")


if __name__ == "__main__":
    main()
