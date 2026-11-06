r"""Poll arXiv for papers that may carry a board-relevant qLDPC code.

Triage, not a claim. A screened-in paper is one whose abstract carries a hard
signal (a stated [[n,k,d]], a construction-family name, or a check-weight or
locality phrase); whether it contains a code, whether that code is new, and
whether its distance is what the abstract says are all questions for a human and
then for the trusted gate. Parameters read out of an abstract are recorded as
`claimed_params` and printed as claims, never as distances. Nothing here writes
to codes/ or touches verify/.

The ledger (research/literature/arxiv-ledger.jsonl, one JSON object per line,
keyed by arXiv id) is both the dedup state and the review record: a paper
already in it is not re-announced, but a version bump is, and a human marks the
verdict with --review. A verdict records the version it was formed on, and a
later version marks it stale rather than replacing it, since a v3 can add the
codes v1 only promised. Superseded verdicts stay in the row's `reviews` list.

    python research/arxiv_watch.py                    # poll, print what is new
    python research/arxiv_watch.py --days 30 --full   # a wider window, all rows
    python research/arxiv_watch.py --dry-run          # poll without writing
    python research/arxiv_watch.py --json             # rows plus query and scan
    python research/arxiv_watch.py --list unreviewed  # read the ledger back
    python research/arxiv_watch.py --review 2503.03827 \
        --status relevant --reason "twisted-torus GB codes, n<=360" \
        --mechanism "twisted-torus quotient"
    python research/arxiv_watch.py --tried 2503.03827 \
        --mechanism "twisted-torus quotient" --where gb-z341-probe \
        --outcome "every quotient in n <= 700 screened below the cell bar"
    python research/arxiv_watch.py --list untried      # mechanisms nobody applied here
    python research/arxiv_watch.py --list mechanisms   # the ledger grouped by mechanism

A verdict says whether a paper is worth reading; it does not say what in it
transfers, or whether anyone here tried. `--mechanism` tags a verdict with the
transferable idea (free text, not the result), and `--tried` records where a
mechanism was applied in this repository and how it went, so a relevant paper
whose idea was never tried is distinguishable from one whose idea was tried and
did not work (issue #4235). Unset is the actionable backlog, `--list untried`.

research/literature/README.md is the process around the tool: the query and why
it is grouped as it is, the polling and rate-limit rules, the ledger format, the
tier definitions, and what a `relevant` verdict does and does not buy.

Operating the poll. The intended cadence is weekly. With no --days the window
is derived from the ledger itself: it reaches back to the latest `last_seen`
across its rows and LAG_SLACK_DAYS further for arXiv's indexing lag, floored at
DEFAULT_DAYS, so a skipped week widens the next run instead of leaving a hole.
An explicit --days shorter than the gap since the last poll is honoured, with a
warning, since it will skip the uncovered days. The window actually used, and
where the number came from, is printed on every run.

Requests go out through curl, not urllib: see http_get(). export.arxiv.org's
edge answers 406 to Python's TLS client on every cache miss while serving the
byte-identical request from curl, so a urllib-only poll can read nothing that
Fastly does not already hold. The 406 carries no body and no Retry-After, so it
is indistinguishable from throttling by inspection; only interleaving the two
clients separates them.

arXiv also answers 406 to bursts. Leave PAUSE_SECONDS between requests and never
run two fetchers against export.arxiv.org at once. Since a refusal can be either
cause, fetch() waits one out rather than treating the first as fatal, with the
backoff doubling up to BACKOFF_CEILING over RETRIES attempts.

The feed is requested with sortBy=lastUpdatedDate (SORT_BY), which the cutoff
depends on: the feed is then monotone decreasing in `updated`, so stopping at
the first entry with updated < cutoff cannot skip a paper. Sorting by
submittedDate instead would hide every new version of an older submission,
which is the common case, since referee rounds put v2 months after v1. A scan
that ends on the page cap or on a short page is reported as truncated on stderr
rather than passing for a complete window.

The query is in QUERY_GROUPS, the screening in SCREEN_TERMS and TIERS below,
and triage records a fingerprint of both, so a rerun on a given day reproduces
the same candidate set and scores from a changed fingerprint are not comparable.
"""
import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(_ROOT, "research", "literature", "arxiv-ledger.jsonl")

API = "https://export.arxiv.org/api/query"

# The cutoff's correctness depends on this: see the module docstring.
SORT_BY = "lastUpdatedDate"
PAUSE_SECONDS = 3.0
BACKOFF_SECONDS = 30.0
# export.arxiv.org refuses with 406 in streaks lasting several minutes, during
# which every request is refused regardless of query, headers or spacing, and
# then serves normally again. So a page request has to be able to wait one out:
# the backoff doubles to BACKOFF_CEILING and RETRIES is set to ride out roughly
# ten minutes rather than the two that a fixed 30s x 2 gives up after.
BACKOFF_CEILING = 120.0
RETRIES = 6
LAG_SLACK_DAYS = 2
DEFAULT_DAYS = 7

# The feed query, as (categories, terms) groups unioned together. A paper
# introducing a construction often never writes "qLDPC", so family names and
# CSS/stabilizer vocabulary are queried alongside it. The groups exist because
# the category gate cuts both ways: a phrase whose wording is also classical
# ("quasi-cyclic", "code distance") drags in the whole cs.IT coding feed unless
# it is held to quant-ph, while a phrase that only ever means one thing
# ("bivariate bicycle") needs no gate, where a gate could only lose papers.
WIDE_CATEGORIES = ("quant-ph", "cs.IT", "math.CO")
QUANTUM_CATEGORIES = ("quant-ph",)

# Unambiguous phrases: no category gate.
SPECIFIC_TERMS = (
    "bivariate bicycle",
    "trivariate bicycle",
    "multivariate bicycle",
    "coprime bicycle",
    "generalized bicycle",
    "lifted product",
    "balanced product",
    "hypergraph product",
    "quantum Tanner",
    "two-block group algebra",
    "2BGA",
    "twisted tori",
)

# Quantum vocabulary, wide enough in category to catch a coding-theory venue.
WIDE_TERMS = (
    "quantum LDPC",
    "qLDPC",
    "quantum low-density parity-check",
    "CSS code",
    "stabilizer code",
    "group algebra code",
    "good quantum codes",
)

# Wording that is also classical, or broad: quant-ph only.
QUANTUM_TERMS = (
    "quasi-cyclic",
    "circulant permutation matrix",
    "code distance",
    "check weight",
    "geometrically local",
    "generalized toric",
    "tile code",
    "coset code",
    "high-rate quantum",
    "finite-length quantum",
    "low-weight quantum",
    "code discovery",
    "search for quantum codes",
)

QUERY_GROUPS = (
    ((), SPECIFIC_TERMS),
    (WIDE_CATEGORIES, WIDE_TERMS),
    (QUANTUM_CATEGORIES, QUANTUM_TERMS),
)

# Deliberately absent from the query: bare "CPM" (in quant-ph that is
# overwhelmingly "completely positive map"), "minimum distance" (with cs.IT and
# math.CO in scope it is the entire classical coding feed), and
# "quantum error-correcting code" (a large fraction of quant-ph QEC output).


def _norm(text):
    """Lowercase and collapse hyphens, slashes and runs of space to one space."""
    return re.sub(r"[-\s/]+", " ", text.lower())


# Matching a term is what raises a hit above "mentions error correction
# somewhere", and the tier a term belongs to is what decides whether a human
# sees it. A FAMILY or STRUCTURE match, or a stated [[n,k,d]] the abstract does
# not attribute to someone else, screens a paper in; the score only orders the
# rows a human then reads top down, so it is ordinal and not calibrated.
# Generic terms alone never screen a paper in: every QEC paper writes
# "construction", "distance" and "parity-check", so a threshold on those admits
# the whole candidate set and the flag carries no information.
FAMILY_TERMS = {
    "bicycle": 3,
    "bivariate bicycle": 3,
    "trivariate": 3,
    "multivariate bicycle": 3,
    "coprime bicycle": 3,
    "lifted product": 3,
    "balanced product": 3,
    "hypergraph product": 3,
    "quantum tanner": 3,
    "two block group algebra": 3,
    "2bga": 3,
    "group algebra": 2,
    "quasi cyclic": 3,
    "circulant permutation": 3,
    "circulant": 3,
    "tile code": 3,
    "twisted tor": 3,
    "generalized toric": 3,
    "coset": 2,
    "expander code": 2,
}
STRUCTURE_TERMS = {
    "check weight": 3,
    "weight 4 check": 2,
    "weight 6 check": 2,
    "weight 8 check": 2,
    "weight 4 stabilizer": 2,
    "weight 6 stabilizer": 2,
    "geometrically local": 3,
    "nearest neighbor": 2,
    "bilayer": 2,
    "planar layout": 2,
    "girth": 2,
    "high rate": 2,
    "finite length": 2,
}
GENERIC_TERMS = {
    "construction": 3,
    "explicit": 2,
    "parity check": 2,
    "distance": 1,
    "logical qubits": 2,
    "encoding rate": 2,
    "toric": 1,
    "surface code": 1,
    "numerical search": 2,
    "computer search": 2,
    "exhaustive search": 2,
    "automated search": 2,
    "reinforcement learning": 2,
    "large language model": 2,
    "evolutionary": 2,
    "catalog": 2,
    "database": 2,
    "code family": 2,
    "new codes": 3,
    # data availability, the cheapest signal that a lead is seedable
    "github": 2,
    "zenodo": 2,
    "available at": 2,
    "we provide": 2,
    "code tables": 2,
}
# Vocabulary of papers that use codes rather than introduce them. Negative, not
# excluding: a transversal-gate or lattice-surgery paper on bicycle codes
# sometimes does introduce a code, so these only push a row down the page.
USE_TERMS = {
    "decoder": -2,
    "belief propagation": -2,
    "bp+osd": -2,
    "threshold": -2,
    "syndrome extraction": -2,
    "logical error rate": -2,
    "magic state": -2,
    "lattice surgery": -2,
    "circuit level noise": -2,
    "benchmark": -2,
}
TIERS = (("family", FAMILY_TERMS), ("structure", STRUCTURE_TERMS),
         ("generic", GENERIC_TERMS), ("use", USE_TERMS))
SCREEN_TERMS = {t: w for _tier, terms in TIERS for t, w in terms.items()}
HARD_TERMS = frozenset(FAMILY_TERMS) | frozenset(STRUCTURE_TERMS)
# The trap this closes: triage matches against a normalised haystack, so a key
# carrying a capital or a hyphen ("quantum Tanner", "parity-check") can never
# fire, and its weight is silently unreachable.
assert all(t == _norm(t) for t in SCREEN_TERMS), \
    "SCREEN_TERMS keys must be normalised: " + \
    ", ".join(t for t in SCREEN_TERMS if t != _norm(t))

# [[n,k,d]] (or [[n,k]]) in an abstract is the strongest signal available
# without opening the paper, but only if the abstract is claiming it for this
# paper: "improving on the [[72,12,6]] code of prior work" states someone
# else's parameters, so each match keeps its context and a comparison flag.
PARAMS_RE = re.compile(r"\[\[\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*(\d+)\s*)?\]\]")
COMPARISON_CUES = (
    "improv", "compar", "prior work", "previous", "well known", "known",
    "existing", "outperform", "better than", "versus", " vs ", "reported in",
    "baseline", "state of the art", "whereas", "instead of", "rather than",
    "relative to", "beat",
)
CLAIM_LIMIT = 12
PARAMS_BONUS = 4
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
REVIEW_STATUSES = ("relevant", "not-relevant", "uncertain")
UNREVIEWED = {"status": "unreviewed", "reason": "", "by": "", "date": "",
              "version": None}

DISCLAIMER = ("triage only: screened_in orders a reading queue and asserts "
              "nothing about novelty or distance; every parameter here is an "
              "unverified claim read out of an abstract")


def build_query():
    """Build the search_query string from QUERY_GROUPS."""
    parts = []
    for cats, terms in QUERY_GROUPS:
        if not terms:
            continue
        joined = " OR ".join(f'abs:"{t}"' for t in terms)
        if cats:
            cat_clause = " OR ".join(f"cat:{c}" for c in cats)
            parts.append(f"(({cat_clause}) AND ({joined}))")
        else:
            parts.append(f"({joined})")
    return " OR ".join(parts)


def criteria_fingerprint():
    """Fingerprint the query and screening criteria that produced a score.

    Two rows whose fingerprints differ were screened under different criteria
    and their scores are not comparable.
    """
    blob = json.dumps([build_query(), sorted(SCREEN_TERMS.items()),
                       sorted(HARD_TERMS), PARAMS_BONUS], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# export.arxiv.org answers 406 to urllib's default header set; sending Accept
# and Accept-Encoding explicitly is what it wants.
HEADERS = {"User-Agent": "qldpc-challenge-arxiv-watch/1.0",
           "Accept": "application/atom+xml,application/xml,text/xml",
           "Accept-Encoding": "gzip, deflate"}
THROTTLED = (406, 429)
# see http_get(): on arXiv, urllib is refused where curl is served
CURL = shutil.which("curl")


def page_url(query, start, batch):
    """Build the feed URL for one page."""
    return API + "?" + urllib.parse.urlencode({
        "search_query": query, "start": start, "max_results": batch,
        "sortBy": SORT_BY, "sortOrder": "descending"})


def _get_via_curl(url, timeout):
    """GET `url` with curl, returning (status, body_text)."""
    with tempfile.TemporaryDirectory() as tmp:
        body = os.path.join(tmp, "body")
        cmd = [CURL, "-sS", "--compressed", "--max-time", str(int(timeout)),
               "-o", body, "-w", "%{http_code}"]
        for name, value in HEADERS.items():
            if name != "Accept-Encoding":  # --compressed sets its own
                cmd += ["-H", f"{name}: {value}"]
        cmd.append(url)
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise urllib.error.URLError(
                f"curl exited {done.returncode}: {done.stderr.strip()[:200]}")
        status = (done.stdout or "").strip()[-3:]
        with open(body, "rb") as f:
            return int(status), f.read().decode("utf-8", "replace")


def _get_via_urllib(url, timeout):
    """GET `url` with urllib, returning (status, body_text)."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return r.status, raw.decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


def http_get(url, timeout=60):
    """GET `url`, preferring curl, returning (status, body_text).

    curl is the transport because export.arxiv.org's edge decides on the TLS
    client, not on the request: with byte-identical headers and interleaved
    requests to equivalent uncached URLs, curl was served 200 and
    urllib.request was refused 406 every time, and a 406 carries no body, no
    Retry-After and no diagnostic. The headers, HTTP version, Connection
    header, query length and request spacing were each ruled out separately;
    only the client changed the answer. urllib stays as the fallback so the
    tool still runs where curl is absent, and the fallback is announced, since
    on arXiv it currently cannot get a cache miss served.
    """
    if CURL:
        return _get_via_curl(url, timeout)
    return _get_via_urllib(url, timeout)


def fetch(query, start, batch, timeout=60, retries=RETRIES,
          backoff=BACKOFF_SECONDS, sleep=time.sleep):
    """Return one page of the Atom feed as text, backing off on a throttle.

    The wait doubles per attempt up to BACKOFF_CEILING because a 406 is not a
    per-request verdict: arXiv refuses in streaks lasting minutes, during which
    a retry is refused too, so a fixed 30s retry that gives up after two
    attempts never rides one out.
    """
    url = page_url(query, start, batch)
    for attempt in range(retries + 1):
        status, body = http_get(url, timeout)
        if status == 200:
            return body
        if status not in THROTTLED or attempt == retries:
            raise urllib.error.HTTPError(url, status, "arXiv refused the feed "
                                         "request", None, None)
        wait = min(backoff * 2 ** attempt, BACKOFF_CEILING)
        print(f"arXiv returned {status}; backing off {wait:.0f}s "
              f"(attempt {attempt + 1} of {retries})", file=sys.stderr)
        sleep(wait)
    raise AssertionError("unreachable")


def split_arxiv_id(raw_id):
    """Split a raw arXiv id into (id, version), keeping any archive prefix.

    Old-style ids carry the archive ("quant-ph/0601001v3"), so the version is
    cut from the end and the prefix is never split off: dropping it would key
    two archives' papers to one row and produce a link that does not resolve.
    """
    m = re.match(r"^(.*?)v(\d+)$", raw_id)
    if m:
        return m.group(1), int(m.group(2))
    return raw_id, 1


def parse_feed(xml_text):
    """Return (entries, total_results) for one page, entries in feed order."""
    root = ET.fromstring(xml_text)
    total = root.findtext(OPENSEARCH + "totalResults")
    out = []
    for e in root.findall(ATOM + "entry"):
        raw_id = re.sub(r"^https?://arxiv\.org/abs/", "",
                        (e.findtext(ATOM + "id") or "").strip())
        if not raw_id:
            continue
        bare, ver = split_arxiv_id(raw_id)
        pc = e.find(ARXIV + "primary_category")
        out.append({
            "id": bare,
            "version": ver,
            "title": " ".join((e.findtext(ATOM + "title") or "").split()),
            "authors": [a.findtext(ATOM + "name") or ""
                        for a in e.findall(ATOM + "author")],
            "submitted": (e.findtext(ATOM + "published") or "")[:10],
            "updated": (e.findtext(ATOM + "updated") or "")[:10],
            "categories": [c.get("term") for c in e.findall(ATOM + "category")],
            "primary": pc.get("term") if pc is not None else None,
            "abstract": " ".join((e.findtext(ATOM + "summary") or "").split()),
            "comment": " ".join((e.findtext(ARXIV + "comment") or "").split()),
            "journal_ref": " ".join((e.findtext(ARXIV + "journal_ref") or "").split()),
            "doi": (e.findtext(ARXIV + "doi") or "").strip(),
            "link": f"https://arxiv.org/abs/{raw_id}",
        })
    return out, int(total) if total and total.strip().isdigit() else None


def parse(xml_text):
    """Return the feed entries of one page, in feed order."""
    return parse_feed(xml_text)[0]


def claimed_params(text):
    """Pull every [[n,k,d]] out of `text`, with its context and whose it is.

    Each claim records the sentence it sits in and whether the wording before it
    attributes the parameters to other work, so nothing downstream reads a
    comparison against a published code as this paper's own.
    """
    claims = []
    for m in PARAMS_RE.finditer(text):
        left = text.rfind(".", 0, m.start()) + 1
        right = text.find(".", m.end())
        sentence = text[left:right if right != -1 else len(text)].strip()
        prefix = _norm(text[left:m.start()])
        n, k, d = m.group(1), m.group(2), m.group(3)
        claims.append({
            "n": int(n), "k": int(k), "d": int(d) if d else None,
            "context": sentence[:240],
            "comparison": any(cue in prefix for cue in COMPARISON_CUES),
        })
        if len(claims) >= CLAIM_LIMIT:
            break
    return claims


def triage(paper):
    """Screen a paper's title, abstract and comment, and read out its claims.

    Returns {score, matched, claimed_params, tier, screened_in, screen}.
    `screened_in` true means "worth a human minute": the abstract carries a
    construction-family, check-weight or locality term, or states parameters it
    does not attribute to other work. It is not a claim that the paper holds a
    new code. `tier` is "strong" (a claim of its own plus a family or structure
    term), "candidate" (one hard signal) or "background" (none).
    """
    # joined with a full stop so a claim's context cannot run title into
    # abstract, and so the comment's "code at github..." is screened too
    text = ". ".join(part for part in (paper["title"], paper["abstract"],
                                       paper.get("comment") or "") if part)
    hay = _norm(text)
    matched = sorted(t for t in SCREEN_TERMS if t in hay)
    score = sum(SCREEN_TERMS[t] for t in matched)
    claims = claimed_params(text)
    own = [c for c in claims if not c["comparison"]]
    if own:
        score += PARAMS_BONUS
    hard_terms = [t for t in matched if t in HARD_TERMS]
    hard = bool(own) or bool(hard_terms)
    if own and hard_terms:
        tier = "strong"
    elif hard:
        tier = "candidate"
    else:
        tier = "background"
    return {"score": score, "matched": matched, "claimed_params": claims,
            "tier": tier, "screened_in": hard,
            "screen": criteria_fingerprint()}


def _migrate_triage(t):
    """Bring a ledger row's triage dict up to the current field names."""
    if not isinstance(t, dict):
        return {"score": 0, "matched": [], "claimed_params": [],
                "tier": "background", "screened_in": False, "screen": ""}
    if "claimed_params" not in t:
        old = t.pop("params", []) or []
        t["claimed_params"] = [
            {"n": p[0], "k": p[1], "d": p[2] if len(p) > 2 else None,
             "context": "", "comparison": False}
            for p in old if len(p) >= 2]
    if "screened_in" not in t:
        t["screened_in"] = bool(t.pop("flag", False))
    t.setdefault("tier", "candidate" if t["screened_in"] else "background")
    t.setdefault("screen", "")
    return t


def load_ledger(path=LEDGER):
    """Read the ledger, reporting and skipping any line that will not parse."""
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                r = json.loads(text)
                key = r["id"]
            except (json.JSONDecodeError, KeyError, TypeError) as err:
                print(f"{path}:{lineno}: skipping unreadable ledger line "
                      f"({type(err).__name__})", file=sys.stderr)
                continue
            r["triage"] = _migrate_triage(r.get("triage"))
            if r.get("tier"):
                r["triage"]["tier"] = r["tier"]
                r["triage"]["screened_in"] = r["tier"] in ("strong", "candidate")
            if r.get("claimed_params"):
                r["triage"]["claimed_params"] = r["claimed_params"]
            rows[key] = hydrate_row(r)
    return rows


# What the ledger keeps, and nothing else. arXiv is the durable copy of a
# paper: mirroring its abstract and author list into this repository would add
# about 2.4 KiB per paper forever, most of it text nobody reads from here, for
# a feed that runs at roughly a hundred papers a month. The ledger's job is to
# know what it has already seen, at which version, and what a human decided --
# so it stores exactly that, and the link to read the rest.
#
# Everything else (the abstract, the authors, the matched screening terms) is
# held in memory for the length of one poll, used for screening and printed in
# the report, and then dropped. ROW_BUDGET_BYTES is enforced by a test, so a
# field added later cannot quietly put the bulk back.
# A row with no verdict yet is the common case and the one that sets the
# ledger's long-run size; a fully reviewed row also carries its capped
# reason. Both are enforced by a test, so a field added later cannot
# quietly put the bulk back.
ROW_BUDGET_BYTES = 800
UNREVIEWED_BUDGET_BYTES = 250
REASON_MAX = 300
# A mechanism tag and the place it was tried are written only when set, so the
# common row keeps the two budgets above. This one bounds the opt-in row: a
# reviewed row naming three mechanisms at the cap with one tried record at the
# caps (issue #4235).
MECHANISM_MAX = 60
WHERE_MAX = 120
TAGGED_ROW_BUDGET_BYTES = 1600


def arxiv_link(row):
    """Return the record's URL, derived rather than stored."""
    return f"https://arxiv.org/abs/{row['id']}v{row.get('version', 1)}"


def slim_row(row):
    """Reduce a row to what the ledger keeps: decisions and identity.

    Anything absent carries its default: no `review` key means unreviewed, no
    `version_history` means the row has only ever been seen at one version.
    Writing those out costs about 150 bytes a paper to say nothing.
    """
    out = {"id": row["id"], "version": row.get("version", 1),
           "updated": row.get("updated", ""),
           "title": row.get("title", ""),
           "tier": row.get("tier") or (row.get("triage") or {}).get(
               "tier", "background"),
           "first_seen": row.get("first_seen", ""),
           "last_seen": row.get("last_seen", "")}
    params = row.get("claimed_params") or (row.get("triage") or {}).get(
        "claimed_params") or []
    if params:
        # the quoted sentence a parameter was read out of is what makes the
        # screen auditable DURING a poll; three parameters from one sentence
        # would store that sentence three times forever. The numbers persist,
        # the quote does not, and the link is how anyone checks it.
        out["claimed_params"] = [
            {k: v for k, v in p.items() if k != "context"} for p in params]
    review = row.get("review") or {}
    if review.get("status") and review["status"] != "unreviewed":
        out["review"] = _slim_review(review)
    prior = [_slim_review(r) for r in (row.get("reviews") or [])]
    if prior:
        out["reviews"] = prior
    tried = [t for t in (_slim_tried(t) for t in row.get("tried") or []) if t]
    if tried:
        out["tried"] = tried
    history = row.get("version_history") or []
    if len(history) > 1:
        out["version_history"] = history
    return out


def _slim_review(review):
    """Cap a verdict's reason and keep its mechanisms only when it names some."""
    review = dict(review)
    if review.get("reason"):
        review["reason"] = review["reason"][:REASON_MAX]
    mechanisms = _dedupe_mechanisms(review.get("mechanisms"))
    if mechanisms:
        review["mechanisms"] = mechanisms
    else:
        review.pop("mechanisms", None)
    return review


def _slim_tried(record):
    """Cap a tried record's free text; a record naming no mechanism is dropped."""
    mechanism = normalise_mechanism((record or {}).get("mechanism", ""))
    if not mechanism:
        return None
    return {"mechanism": mechanism,
            "where": str(record.get("where", ""))[:WHERE_MAX],
            "outcome": str(record.get("outcome", ""))[:REASON_MAX],
            "by": record.get("by", ""), "date": record.get("date", "")}


def hydrate_row(row):
    """Fill in what slim_row left out, so callers never see a missing key."""
    row.setdefault("version", 1)
    row.setdefault("updated", "")
    row.setdefault("submitted", row.get("updated", ""))
    row.setdefault("title", "")
    row.setdefault("tier", "background")
    row.setdefault("claimed_params", [])
    row.setdefault("reviews", [])
    row.setdefault("link", arxiv_link(row))
    row.setdefault("version_history",
                   [{"version": row["version"], "updated": row["updated"],
                     "seen": row.get("first_seen", "")}])
    row.setdefault("review", {"status": "unreviewed", "reason": "",
                              "by": "", "date": "", "version": None})
    row["review"].setdefault("mechanisms", [])
    row.setdefault("tried", [])
    row.setdefault("triage", {"tier": row["tier"],
                              "claimed_params": row["claimed_params"],
                              "matched": [], "screened_in":
                              row["tier"] in ("strong", "candidate")})
    return row


def save_ledger(rows, path=LEDGER):
    """Rewrite the ledger atomically, newest first, in its slim form."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    ordered = sorted(rows.values(),
                     key=lambda r: (r.get("updated", ""), r["id"]),
                     reverse=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in ordered:
            f.write(json.dumps(slim_row(r), sort_keys=True) + "\n")
    os.replace(tmp, path)


def last_poll_date(ledger):
    """Return the latest `last_seen` in the ledger, or "" if there is none."""
    return max((r.get("last_seen") or "" for r in ledger.values()), default="")


def window_days(ledger, requested=None, now=None):
    """Decide how far back to scan, and say where the number came from.

    With no --days the window reaches back to the previous poll plus
    LAG_SLACK_DAYS of slack for arXiv's indexing lag, so a skipped run widens
    the next one. An explicit --days is honoured as given.
    """
    now = now or datetime.now(timezone.utc)
    last = last_poll_date(ledger)
    gap = None
    if last:
        try:
            then = datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            gap = (now - then).days
        except ValueError:
            gap = None
    if requested is not None:
        why = f"--days {requested}"
        if gap is not None and requested < gap + LAG_SLACK_DAYS:
            why += (f"; WARNING: {gap} days since the last poll ({last}), so "
                    f"this window skips the days before it")
        return requested, why
    if gap is None:
        return DEFAULT_DAYS, f"no previous poll in the ledger, default {DEFAULT_DAYS} days"
    reach = gap + LAG_SLACK_DAYS
    if reach < DEFAULT_DAYS:
        return DEFAULT_DAYS, (f"{gap} days since the last poll ({last}), "
                              f"widened to the {DEFAULT_DAYS}-day floor")
    return reach, (f"{gap} days since the last poll ({last}) plus "
                   f"{LAG_SLACK_DAYS} days of slack")


def _version_history(prev, paper, today):
    """Carry a row's version history forward and append any bump."""
    if prev is None:
        return [{"version": paper["version"], "updated": paper["updated"],
                 "seen": today}]
    history = [dict(h) for h in (prev.get("version_history") or [])]
    if not history:
        history = [{"version": prev.get("version", paper["version"]),
                    "updated": prev.get("updated", ""),
                    "seen": prev.get("first_seen", today)}]
    if paper["version"] > history[-1].get("version", 0):
        history.append({"version": paper["version"],
                        "updated": paper["updated"], "seen": today})
    return history


def _carry_review(prev, paper):
    """Carry a verdict forward, marking it stale if the paper has moved on."""
    review = dict((prev or {}).get("review") or UNREVIEWED)
    for key, value in UNREVIEWED.items():
        review.setdefault(key, value)
    reviewed_at = review.get("version")
    if review["status"] != "unreviewed" and reviewed_at is not None \
            and paper["version"] > reviewed_at:
        review["stale"] = True
    return review


def poll(days, ledger, batch=100, pages=10, pause=PAUSE_SECONDS, fetcher=None,
         now=None, retry_pause=BACKOFF_SECONDS, sleep=None):
    """Walk the feed back `days` and return (new, updated, ledger, scan).

    `new` are ids absent from the ledger; `updated` are ids whose arXiv version
    has risen since the last poll. Everything else is silently skipped, which
    is the whole point of the ledger. `scan` records how the walk ended, so a
    window truncated by the page cap or a short page can be reported rather
    than passing for a complete one. `pause` honours arXiv's request that
    callers leave three seconds between queries.
    """
    fetcher = fetcher or fetch
    sleep = sleep or time.sleep
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    query = build_query()
    new, updated = [], []
    scan = {"polled": today, "cutoff": cutoff, "days": days,
            "pages_fetched": 0, "entries_seen": 0, "total_results": None,
            "oldest_updated": None, "complete": False, "stopped": ""}
    for page in range(pages):
        start = page * batch
        entries, total = parse_feed(fetcher(query, start, batch))
        scan["pages_fetched"] += 1
        if total is not None:
            scan["total_results"] = total
        exhausted = (scan["total_results"] is not None
                     and start + len(entries) >= scan["total_results"])
        if len(entries) < batch and not exhausted:
            # arXiv returns a short or empty page transiently even when more
            # results exist, so disbelieve it once before ending the scan.
            sleep(retry_pause)
            retry, retry_total = parse_feed(fetcher(query, start, batch))
            scan["pages_fetched"] += 1
            if len(retry) > len(entries):
                entries = retry
                if retry_total is not None:
                    scan["total_results"] = retry_total
        if not entries:
            scan["stopped"] = f"empty page at start={start}"
            if scan["total_results"] == 0:
                scan["complete"] = True
                scan["stopped"] = "no results for the query"
            break
        reached_cutoff = False
        for p in entries:
            scan["entries_seen"] += 1
            if not p["submitted"] and not p["updated"]:
                print(f"arXiv:{p['id']}: no published or updated date; skipped",
                      file=sys.stderr)
                continue
            if p["updated"] < cutoff:
                reached_cutoff = True
                break
            if scan["oldest_updated"] is None or p["updated"] < scan["oldest_updated"]:
                scan["oldest_updated"] = p["updated"]
            prev = ledger.get(p["id"])
            row = {"id": p["id"], "version": p["version"], "title": p["title"],
                   "authors": p["authors"], "submitted": p["submitted"],
                   "updated": p["updated"], "categories": p["categories"],
                   "primary": p["primary"], "link": p["link"],
                   "abstract": p["abstract"], "comment": p["comment"],
                   "journal_ref": p["journal_ref"], "doi": p["doi"],
                   "triage": triage(p),
                   "version_history": _version_history(prev, p, today),
                   "first_seen": prev["first_seen"] if prev else today,
                   "last_seen": today,
                   "reviews": list((prev or {}).get("reviews") or []),
                   "tried": list((prev or {}).get("tried") or []),
                   "review": _carry_review(prev, p)}
            if len(row["version_history"]) > 1:
                row["prior_version"] = row["version_history"][-2]["version"]
            if prev is None:
                new.append(row)
            elif p["version"] > prev.get("version", 1):
                updated.append(row)
            ledger[p["id"]] = row
        if reached_cutoff:
            scan["complete"] = True
            scan["stopped"] = f"reached the cutoff {cutoff}"
            break
        if len(entries) < batch:
            seen = start + len(entries)
            if scan["total_results"] is not None and seen >= scan["total_results"]:
                scan["complete"] = True
                scan["stopped"] = f"end of results ({seen} entries)"
            else:
                scan["stopped"] = (f"short page ({len(entries)} of {batch}) at "
                                   f"start={start}, still inside the window")
            break
        if page + 1 < pages:
            sleep(pause)
    else:
        scan["stopped"] = (f"page cap: {pages} pages of {batch} and still "
                           f"inside the window")
    return new, updated, ledger, scan


def format_claim(claim):
    """Render one abstract claim, keeping the distance marked as a claim."""
    head = f"[[{claim['n']},{claim['k']}]]"
    if claim.get("d") is not None:
        head += f" claims d = {claim['d']}"
    if claim.get("comparison"):
        head += " (attributed to other work)"
    return head


def render(rows, kind, limit, show_abstract=False):
    """Print one section, bounded like `qldpc recent`."""
    if not rows:
        return
    rows = sorted(rows, key=lambda r: -r["triage"]["score"])
    print(f"\n{kind} ({len(rows)}):")
    for r in rows[:limit]:
        t = r["triage"]
        v = f"v{r['version']}"
        if r.get("prior_version"):
            v = f"v{r['prior_version']} -> v{r['version']}"
        mark = "READ" if t["screened_in"] else "    "
        score = f", score {t['score']}" if t.get("score") else ""
        print(f"  {mark} {r['submitted']}  arXiv:{r['id']} {v}  "
              f"{t['tier']}{score}")
        print(f"       {r['title']}")
        # authors and categories are known during a poll and not kept in the
        # ledger, so a later offline read prints the link instead
        authors, cats = r.get("authors") or [], r.get("categories") or []
        if authors or cats:
            who = ", ".join(authors[:3])
            if len(authors) > 3:
                who += f", +{len(authors) - 3}"
            tail = f"  [{', '.join(c for c in cats[:4] if c)}]" if cats else ""
            print(f"       {who}{tail}")
        if t["claimed_params"]:
            shown = "; ".join(format_claim(c) for c in t["claimed_params"][:6])
            print(f"       claimed in abstract: {shown}")
        if r.get("comment"):
            print(f"       comment: {r['comment'][:160]}")
        rv = r.get("review") or UNREVIEWED
        line = rv.get("status", "unreviewed")
        if line != "unreviewed":
            at = rv.get("version")
            line += f" (on v{at}, {rv.get('date', '')})" if at else \
                f" ({rv.get('date', '')})"
            if rv.get("reason"):
                line += f": {rv['reason']}"
            if rv.get("stale"):
                line += "  -- predates this version, needs re-reading"
        print(f"       review: {line}")
        mechanisms = mechanisms_of(r)
        if mechanisms:
            left = untried_mechanisms(r)
            tail = "  (not tried here)" if len(left) == len(mechanisms) else ""
            print(f"       mechanisms: {'; '.join(mechanisms)}{tail}")
            if left and len(left) < len(mechanisms):
                print(f"       not tried here: {'; '.join(left)}")
        for t in r.get("tried") or []:
            print(f"       tried: {t.get('mechanism', '')} in {t.get('where', '')} "
                  f"({t.get('date', '')}, {t.get('by', '')}): {t.get('outcome', '')}")
        print(f"       {r['link']}")
        if show_abstract:
            print(f"       {r['abstract'][:400]}")
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more (--limit N, --full)")


def normalise_key(text):
    """Normalise a user-typed arXiv reference to a ledger key."""
    key = (text or "").strip()
    key = re.sub(r"^arxiv:", "", key, flags=re.IGNORECASE)
    key = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", key)
    key = re.sub(r"\.pdf$", "", key)
    return split_arxiv_id(key.strip())[0]


# -- the transferable mechanism, and whether it was tried here (issue #4235) --
#
# A verdict says whether a paper is worth reading. What transfers out of it is
# a mechanism (a construction move, a symmetry, a way of choosing supports),
# and whether anyone here applied it is a separate fact from whether the paper
# was relevant. Tags are free text by design: a taxonomy fixed in advance would
# not match the transfers that turn out to matter, so two spellings of one
# mechanism are compared after the same normalization the screen uses.

def normalise_mechanism(text):
    """Return one mechanism tag as the ledger keeps it: trimmed, single-spaced, capped."""
    tag = re.sub(r"\s+", " ", str(text or "")).strip()
    return tag[:MECHANISM_MAX].rstrip()


def _mechanism_key(tag):
    """Return the form under which two spellings of one mechanism are compared."""
    return _norm(normalise_mechanism(tag)).strip()


def _dedupe_mechanisms(tags):
    """Normalize tags, dropping blanks and repeats; the first spelling is kept."""
    seen = {}
    for tag in tags or []:
        clean = normalise_mechanism(tag)
        if clean:
            seen.setdefault(_mechanism_key(clean), clean)
    return list(seen.values())


def mechanisms_of(row):
    """Every mechanism a row names, on its current verdict or in a tried record.

    The verdict says what the paper carries and a tried record says what was
    applied here; a mechanism tried without ever being tagged still counts as
    named, so the two are unioned rather than one being authoritative.
    """
    review = row.get("review") or {}
    tried = [t.get("mechanism", "") for t in row.get("tried") or []]
    return _dedupe_mechanisms(list(review.get("mechanisms") or []) + tried)


def untried_mechanisms(row):
    """Return the mechanisms a row names that no tried record covers: the backlog."""
    done = {_mechanism_key(t.get("mechanism", "")) for t in row.get("tried") or []}
    return [m for m in mechanisms_of(row) if _mechanism_key(m) not in done]


def _mechanism_matches(row, wanted):
    """Return True when a mechanism the row names contains `wanted`."""
    key = _mechanism_key(wanted)
    return bool(key) and any(key in _mechanism_key(m) for m in mechanisms_of(row))


# Where a mechanism was applied has to be something the next reader can open,
# for the reason check_prose holds a note's citations to the PR tree: a
# backlog entry pointing at a scratch directory that no longer exists records
# nothing. The accepted shapes are an issue or PR reference, a campaign id, a
# board slug, or a committed path.
WORKING_OUTPUT = ("research/candidates", "research/out", "research/runs")
ISSUE_REF = re.compile(
    r"^(?:#|https?://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues)/)(\d+)$")
SLUG_RE = re.compile(r"^\d+-\d+-\d+(?:-[a-z0-9]+)?$")


def resolve_where(where, root=None):
    """Return (ok, what) for the place a mechanism was applied.

    Accepted: an issue or PR reference (`#4235` or its GitHub URL), a campaign
    id or directory under research/campaigns/, a board slug or its codes/
    path, or any committed path in the repository. Refused, naming the
    accepted shapes: gitignored working output, an absolute path, and anything
    that does not exist.
    """
    root = root or _ROOT
    text = (where or "").strip().rstrip("/")
    if not text:
        return False, "--where is empty"
    m = ISSUE_REF.match(text)
    if m:
        return True, f"issue or PR #{m.group(1)}"
    parts = text.replace("\\", "/").split("/")
    if os.path.isabs(text) or ".." in parts:
        return False, (f"{text} is not a path inside the repository; name the committed "
                       "file, the campaign, or the PR")
    if any(text == w or text.startswith(w + "/") for w in WORKING_OUTPUT):
        return False, (f"{text} is gitignored working output and cannot be cited; name the "
                       "campaign summary, the fieldnote, or the PR it became")
    if "/" not in text and os.path.isdir(os.path.join(root, "research", "campaigns", text)):
        return True, f"campaign research/campaigns/{text}"
    if SLUG_RE.match(text) and os.path.exists(os.path.join(root, "codes", text + ".json")):
        return True, f"board entry codes/{text}.json"
    if os.path.exists(os.path.join(root, text)):
        return True, f"path {text}"
    return False, (f"{text} is not an issue or PR reference (#N), a campaign id under "
                   "research/campaigns/, a board slug, or a committed path")


def _missing(key, rows):
    """Explain an id the ledger does not hold, without reaching for the network."""
    near = sorted(k for k in rows if key in k or k in key)[:5]
    hint = f"; did you mean {', '.join(near)}?" if near else ""
    print(f"arXiv:{key} not in the ledger ({len(rows)} rows); run a poll "
          f"covering its submission date first{hint}", file=sys.stderr)


def cmd_review(args, path=LEDGER):
    """Record a human verdict on one paper, with the mechanisms it carries.

    `--mechanism` alone, with no `--status`, restates the standing verdict as
    a new review that adds the tags, so a tag is a review in the history and
    never an edit of one. Tags accumulate across verdicts: they name what the
    paper contains, which a changed verdict does not change.
    """
    rows = load_ledger(path)
    key = normalise_key(args.review)
    if not key:
        print("--review needs an arXiv id", file=sys.stderr)
        return 2
    if key not in rows:
        _missing(key, rows)
        return 1
    row = rows[key]
    prior = row.get("review") or {}
    had_verdict = prior.get("status", "unreviewed") != "unreviewed"
    status, reason = args.status, args.reason
    if status is None:
        if not had_verdict:
            print(f"arXiv:{key} has no verdict to tag; give --status and --reason "
                  "with --mechanism", file=sys.stderr)
            return 1
        status, reason = prior["status"], prior.get("reason", "")
    verdict = {"status": status, "reason": reason,
               "by": args.by or os.environ.get("USER", ""),
               "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
               "version": row.get("version")}
    mechanisms = _dedupe_mechanisms(
        list(prior.get("mechanisms") or []) + list(getattr(args, "mechanism", None) or []))
    if mechanisms:
        verdict["mechanisms"] = mechanisms
    tagged = f"; mechanisms: {'; '.join(mechanisms)}" if mechanisms else ""
    if getattr(args, "dry_run", False):
        print(f"dry run, not written -- arXiv:{key}: {status} ({reason}){tagged}")
        return 0
    if had_verdict:
        row["reviews"] = list(row.get("reviews") or []) + [prior]
    row["review"] = verdict
    save_ledger(rows, path)
    print(f"arXiv:{key} v{row.get('version')}: {status} ({reason}){tagged}")
    return 0


def cmd_tried(args, path=LEDGER):
    """Record that a paper's mechanism was applied here, where, and how it went."""
    rows = load_ledger(path)
    key = normalise_key(args.tried)
    if not key:
        print("--tried needs an arXiv id", file=sys.stderr)
        return 2
    if key not in rows:
        _missing(key, rows)
        return 1
    ok, what = resolve_where(args.where)
    if not ok:
        print(f"--where: {what}", file=sys.stderr)
        return 1
    row = rows[key]
    where = args.where.strip().rstrip("/")[:WHERE_MAX]
    outcome = args.outcome.strip()[:REASON_MAX]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    by = args.by or os.environ.get("USER", "")
    records = [{"mechanism": m, "where": where, "outcome": outcome, "by": by, "date": today}
               for m in _dedupe_mechanisms(args.mechanism)]
    tagged = {_mechanism_key(m) for m in (row.get("review") or {}).get("mechanisms") or []}
    untagged = [r["mechanism"] for r in records if _mechanism_key(r["mechanism"]) not in tagged]
    if getattr(args, "dry_run", False):
        for r in records:
            print(f"dry run, not written -- arXiv:{key}: tried {r['mechanism']} in "
                  f"{where} ({what}): {outcome}")
        return 0
    row["tried"] = list(row.get("tried") or []) + records
    save_ledger(rows, path)
    for r in records:
        print(f"arXiv:{key} v{row.get('version')}: tried {r['mechanism']} in {where} "
              f"({what}): {outcome}")
    if untagged:
        print(f"note: {'; '.join(untagged)} is not among the verdict's mechanisms for "
              f"arXiv:{key}; this record now names it", file=sys.stderr)
    return 0


LIST_KINDS = ("all", "screened-in", "unreviewed", *REVIEW_STATUSES,
              "mechanisms", "untried", "tried")


def _select(rows, want):
    """Return the ledger rows a `--list` kind asks for."""
    if want == "screened-in":
        return [r for r in rows.values() if r["triage"]["screened_in"]]
    if want == "all":
        return list(rows.values())
    if want == "mechanisms":
        return [r for r in rows.values() if mechanisms_of(r)]
    if want == "untried":
        return [r for r in rows.values() if untried_mechanisms(r)]
    if want == "tried":
        return [r for r in rows.values() if r.get("tried")]
    return [r for r in rows.values()
            if (r.get("review") or UNREVIEWED).get("status") == want]


def _newest_first(rows):
    return sorted(rows, key=lambda r: (r.get("updated", ""), r["id"]), reverse=True)


def render_mechanisms(rows, limit):
    """Print the ledger grouped by mechanism, each paper with whether it was tried here."""
    groups = {}
    for r in rows:
        for m in mechanisms_of(r):
            groups.setdefault(_mechanism_key(m), (m, []))[1].append(r)
    if not groups:
        print("no mechanisms recorded; tag one with --review <id> --mechanism '...'")
        return
    ordered = sorted(groups.values(), key=lambda g: (-len(g[1]), _mechanism_key(g[0])))
    backlog = sum(1 for r in rows if untried_mechanisms(r))
    print(f"\n{len(groups)} mechanisms on {len(rows)} papers, {backlog} papers with one "
          "not tried here:")
    for name, papers in ordered[:limit]:
        key = _mechanism_key(name)
        waiting = [r for r in papers
                   if key in {_mechanism_key(u) for u in untried_mechanisms(r)}]
        print(f"\n  {name}: {len(papers)} paper(s), {len(waiting)} not tried here")
        for r in _newest_first(papers):
            rv = r.get("review") or UNREVIEWED
            status = rv.get("status", "unreviewed")
            if rv.get("version"):
                status += f" (on v{rv['version']}, {rv.get('date', '')})"
            print(f"    arXiv:{r['id']} v{r['version']}  {status}  {r['title']}")
            hits = [t for t in r.get("tried") or []
                    if _mechanism_key(t.get("mechanism", "")) == key]
            if not hits:
                print("        not tried here")
            for t in hits:
                print(f"        tried in {t.get('where', '')} ({t.get('date', '')}, "
                      f"{t.get('by', '')}): {t.get('outcome', '')}")
    if len(ordered) > limit:
        print(f"  ... {len(ordered) - limit} more mechanisms (--limit N, --full)")


def cmd_list(args, path=LEDGER):
    """Print ledger rows by review status, mechanism, or tried state, without polling."""
    rows = load_ledger(path)
    want = args.list
    keep = _select(rows, want)
    wanted = [m for m in (getattr(args, "mechanism", None) or []) if normalise_mechanism(m)]
    if wanted:
        keep = [r for r in keep if any(_mechanism_matches(r, m) for m in wanted)]
    if getattr(args, "json", False):
        payload = {"disclaimer": DISCLAIMER, "ledger": path, "list": want,
                   "mechanism": wanted,
                   "rows": [dict(slim_row(r), link=arxiv_link(r),
                                 mechanisms=mechanisms_of(r),
                                 untried=untried_mechanisms(r))
                            for r in _newest_first(keep)]}
        print(json.dumps(payload, indent=2, sort_keys=True))
        print(DISCLAIMER, file=sys.stderr)
        return 0
    naming = f" naming {' or '.join(wanted)}" if wanted else ""
    print(f"ledger {path}: {len(rows)} papers, {len(keep)} matching {want}{naming}")
    limit = 10 ** 6 if args.full else max(1, args.limit)
    if want == "mechanisms":
        render_mechanisms(keep, limit)
    else:
        render(keep, want, limit, args.abstracts)
    return 0


def _has_mechanism(args):
    return bool(args.mechanism and any(normalise_mechanism(m) for m in args.mechanism))


def main(argv=None):
    """Poll arXiv, list the ledger, record a verdict, or record what was tried."""
    p = argparse.ArgumentParser(
        prog="arxiv_watch",
        description="poll arXiv for possibly board-relevant qLDPC papers")
    p.add_argument("--days", type=int, default=None,
                   help="how far back to look (default: since the previous "
                        f"poll plus {LAG_SLACK_DAYS} days of slack)")
    p.add_argument("--pages", type=int, default=10,
                   help="page cap per poll (default 10)")
    p.add_argument("--batch", type=int, default=100,
                   help="entries per page (default 100)")
    p.add_argument("--limit", type=int, default=10,
                   help="rows per section (default 10)")
    p.add_argument("--full", action="store_true", help="print every row")
    p.add_argument("--abstracts", action="store_true",
                   help="include the first 400 characters of each abstract")
    p.add_argument("--dry-run", action="store_true",
                   help="poll, review, or record without writing the ledger")
    p.add_argument("--json", action="store_true",
                   help="emit the new and updated rows as JSON (with --list, the "
                        "matching rows)")
    p.add_argument("--ledger", default=LEDGER)
    p.add_argument("--list", nargs="?", const="unreviewed", default=None,
                   choices=list(LIST_KINDS),
                   help="print ledger rows instead of polling")
    p.add_argument("--review", default=None,
                   help="record a verdict on this arXiv id instead of polling")
    p.add_argument("--status", default=None, choices=list(REVIEW_STATUSES))
    p.add_argument("--reason", default=None,
                   help="a brief reason, required with --review")
    p.add_argument("--by", default="", help="who reviewed it (default $USER)")
    p.add_argument("--mechanism", action="append", default=None, metavar="TAG",
                   help="with --review, a transferable idea the paper carries (repeatable); "
                        "with --tried, the one applied; with --list, keep only papers "
                        "naming a mechanism containing TAG")
    p.add_argument("--tried", default=None, metavar="ID",
                   help="record that a mechanism of this arXiv id was applied here; needs "
                        "--mechanism, --where and --outcome")
    p.add_argument("--where", default=None,
                   help="where it was applied: an issue or PR (#N), a campaign id, a board "
                        "slug, or a committed path")
    p.add_argument("--outcome", default=None, help="how it went, in a sentence")
    args = p.parse_args(argv)

    if args.list is not None:
        if args.review is not None or args.tried is not None:
            p.error("--list does not combine with --review or --tried")
        return cmd_list(args, args.ledger)
    if args.tried is not None:
        if not args.tried.strip():
            p.error("--tried needs an arXiv id")
        if args.review is not None:
            p.error("--review and --tried are separate records; run them one at a time")
        if args.status is not None or args.reason is not None:
            p.error("--status and --reason only apply with --review")
        if not _has_mechanism(args):
            p.error("--tried requires --mechanism, the one that was applied")
        if not (args.where or "").strip() or not (args.outcome or "").strip():
            p.error("--tried requires --where and a non-empty --outcome")
        return cmd_tried(args, args.ledger)
    if args.review is not None:
        if not args.review.strip():
            p.error("--review needs an arXiv id")
        if args.where is not None or args.outcome is not None:
            p.error("--where and --outcome only apply with --tried")
        tag_only = args.status is None and args.reason is None and _has_mechanism(args)
        if not tag_only and (args.status is None or args.reason is None
                             or not args.reason.strip()):
            p.error("--review requires --status and a non-empty --reason, or --mechanism "
                    "alone to tag the standing verdict")
        return cmd_review(args, args.ledger)
    if args.status is not None or args.reason is not None:
        p.error("--status and --reason only apply with --review")
    if args.mechanism or args.where is not None or args.outcome is not None:
        p.error("--mechanism, --where and --outcome apply with --review, --tried or --list")

    ledger = load_ledger(args.ledger)
    before = len(ledger)
    days, why = window_days(ledger, args.days)
    new, updated, ledger, scan = poll(days, ledger, batch=max(1, args.batch),
                                      pages=max(1, args.pages))
    if not scan["complete"]:
        print(f"WARNING: window truncated -- {scan['stopped']}; oldest entry "
              f"scanned was updated {scan['oldest_updated']}. Papers older "
              f"than that in the window were not seen: rerun with a larger "
              f"--pages or a narrower --days.", file=sys.stderr)
    if args.json:
        print(json.dumps({"disclaimer": DISCLAIMER, "query": build_query(),
                          "screen": criteria_fingerprint(),
                          "screen_terms": SCREEN_TERMS, "window": why,
                          "scan": scan, "new": new, "updated": updated},
                         indent=2, sort_keys=True))
        print(DISCLAIMER, file=sys.stderr)
    else:
        limit = 10 ** 6 if args.full else max(1, args.limit)
        picked = sum(1 for r in new + updated if r["triage"]["screened_in"])
        print(f"arXiv watch, last {days} days ({why}): {len(new)} new, "
              f"{len(updated)} updated, {picked} screened in for review "
              f"({before} papers in the ledger before this poll)")
        render(new, "new", limit, args.abstracts)
        render(updated, "new versions of papers already seen", limit,
               args.abstracts)
        if new or updated:
            print(f"\n{DISCLAIMER}.")
            print("record a verdict: python research/arxiv_watch.py --review "
                  "<id> --status relevant|not-relevant|uncertain --reason '...'")
    if not args.dry_run:
        save_ledger(ledger, args.ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
