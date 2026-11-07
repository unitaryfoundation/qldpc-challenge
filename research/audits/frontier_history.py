#!/usr/bin/env python3
"""Reconstruct the board's (n, k, d) Pareto frontier from git history.

The board ranks codes on (n, k, d, w). `d` is a witness-backed *upper* bound
whose history is full of downward revisions (``[[882,18,30]]`` -> 29,
``[[684,12,81]]`` -> 66), which is a reason to watch it, not to drop it: with
`d` removed the (n, k) frontier is won by rate alone (``[[n, n-2, 2]]`` exists
for every even n), and what that frontier then measures is who submitted the
highest-rate low-distance code. So this script keeps `d`, reports the
three-axis frontier (n lower, k and d higher are better) after every landing
that moved it, and makes the revisions visible as the steps *down*.

It replays ``codes/*.json`` along main's first-parent chain -- one step per
landing on the board -- and reports, after every step that moved the board,
the CSS code count, the frontier's size, and the frontier's dominated
hypervolume. The replay is only worth quoting if it ends where the repository
is, so ``research/audits/test_frontier_history.py`` asserts exactly that: the
final state must equal ``git ls-tree -r HEAD -- codes/`` read as (n, k, d),
CSS only. Plain ``git log`` breaks that (it orders by date, so a deletion can
land before the add it deletes), and a rename reported for a rewrite of an
unrelated file breaks it differently unless the destination is re-read.

Two charts, both dependency-free SVG:

``--plot`` draws the frontier as a shape: one panel per distance floor
(d >= 4, 6, 8, 12, 16, 24), each carrying the (n, k) staircase of the codes
that clear the floor, on log axes, as of a few snapshots (one per month by
default). The region gained between consecutive snapshots is shaded in the
newer snapshot's colour and a region lost (a correction or removal) in red,
and today's staircase carries a dot and an ``n,k,d`` label per code.

``--plot-history`` draws one line on a time axis: the frontier's hypervolume
as a share of today's, with every downward step marked and named. That is the
signal a "codes over time" count hides.

``--frames`` writes the panel chart once per snapshot (one per day by
default), each frame over the previous one in grey, and ``--gif`` assembles
those frames into an animation. The charts are stdlib only; the GIF needs
``rsvg-convert`` on PATH and Pillow (the ``research`` extra).

  uv run --frozen python research/audits/frontier_history.py
  uv run --frozen python research/audits/frontier_history.py --out /tmp/frontier.csv
  uv run --frozen python research/audits/frontier_history.py --plot frontier.svg
  uv run --frozen python research/audits/frontier_history.py --plot-history history.svg
  uv run --frozen --extra research python research/audits/frontier_history.py --gif frontier.gif

Hypervolume is taken in log2 coordinates against the reference point
(n = ``--n-ref``, k = 1/2, d = 1/2): a frontier code contributes the box
``log2(n_ref/n) x (1 + log2 k) x (1 + log2 d)``, and the union of those boxes
is the number. Log space is what the board's own ``kd^2/n`` lives in, and the
half-unit reference keeps ``k = 1`` codes (which sit on the small-n frontier
legitimately) from contributing nothing. A code at or above ``n_ref``
contributes nothing.

Only the main (CSS) board is replayed; general stabilizer codes rank on their
own board and are skipped. n, k and d are read per file *version*, so an
in-place correction is seen; a rename is read at its destination.
"""

import argparse
import bisect
import datetime
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))

# Distance floors for the small-multiples chart, one panel each.
_FLOORS = (4, 6, 8, 12, 16, 24)


def git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          check=False)


def parse_log(text):
    """Parse the commit list from `git log --name-status`, oldest first.

    Each entry is ``(sha, iso_date, [(status, path, dest), ...])`` with status
    one of ``A`` (added), ``M`` (modified), ``D`` (deleted) or ``R`` (renamed,
    ``dest`` set).
    """
    commits, changes = [], None
    for line in text.splitlines():
        if line.startswith("C "):
            _, sha, date = line.split(" ", 2)
            changes = []
            commits.append((sha, date, changes))
        elif changes is None:
            continue
        elif line.startswith(("A\t", "M\t", "D\t")):
            status, path = line.split("\t")
            changes.append((status, path, None))
        elif line.startswith("R"):
            parts = line.split("\t")
            changes.append(("R", parts[1], parts[2]))
    return commits


def utc_day(iso):
    """Return the UTC calendar day of an ISO-8601 timestamp with offset."""
    stamp = datetime.datetime.fromisoformat(iso)
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(datetime.timezone.utc)
    return stamp.date().isoformat()


def fetch_params(requests, cwd):
    """Map each ``(sha, path)`` to its parsed ``(n, k, d, code_type)`` or None.

    One ``git cat-file --batch`` process, written to and read from one blob at
    a time: the board's history is a growing multiple of the board, so a call
    that buffers every historical version at once would scale with history
    instead of with the board. The header echoes the blob's own oid rather
    than the requested rev, so responses are consumed in request order.
    """
    out = {}
    if not requests:
        return out
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=cwd,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for sha, path in requests:
        proc.stdin.write(f"{sha}:{path}\n".encode())
        proc.stdin.flush()
        header = proc.stdout.readline().split()
        if len(header) == 3 and header[1] != b"missing":
            size = int(header[2])
            out[(sha, path)] = params(proc.stdout.read(size + 1)[:-1])
        else:
            out[(sha, path)] = None
    proc.stdin.close()
    proc.wait()
    return out


def params(raw):
    """``(n, k, d, code_type)`` from a code blob, or None if it will not parse.

    ``d`` is ``distance.d``; an entry that predates that field falls back to
    the minimum of the per-side values, and a bare number is taken as is.
    """
    if raw is None:
        return None
    try:
        doc = json.loads(raw)
        dist = doc.get("distance")
        if isinstance(dist, dict):
            d = dist.get("d")
            if d is None:
                sides = [dist[s]["value"] for s in ("X", "Z")
                         if isinstance(dist.get(s), dict) and "value" in dist[s]]
                d = min(sides) if sides else None
        else:
            d = dist
        if d is None:
            return None
        return int(doc["n"]), int(doc["k"]), int(d), doc.get("code_type", "CSS")
    except (ValueError, KeyError, TypeError):
        return None


def frontier(points):
    """Return the (n, k, d) antichain: triples no other beats on all axes.

    Sorted by n ascending (k, then d, descending within a tie), a triple is
    dominated exactly when some earlier triple has k' >= k and d' >= d: an
    earlier triple with a smaller n is strictly better on n, and one with the
    same n sorts earlier only if it is strictly better on k or d. The maximal
    (k, d) pairs seen so far form a staircase (k rising, d falling), so the
    largest d over k' >= k is the one at the first k' >= k. Returned in n
    order.
    """
    front, ks, ds = [], [], []
    for n, k, d in sorted(points, key=lambda t: (t[0], -t[1], -t[2])):
        i = bisect.bisect_left(ks, k)
        if i < len(ks) and ds[i] >= d:
            continue
        front.append((n, k, d))
        j = i
        while j > 0 and ds[j - 1] <= d:
            j -= 1
        end = i + 1 if i < len(ks) and ks[i] == k else i
        ks[j:end] = [k]
        ds[j:end] = [d]
    return front


def hypervolume(front, n_ref):
    """Dominated volume of the frontier in log2 coordinates.

    Each ``(n, k, d)`` with ``n < n_ref`` is the box ``[0, log2(n_ref/n)] x
    [0, 1 + log2 k] x [0, 1 + log2 d]``; the result is the volume of their
    union: a sweep over the first axis, with the cross-section of each slab
    the union area of the origin-anchored rectangles of every box that spans
    it.
    """
    boxes = sorted(((math.log2(n_ref / n), 1 + math.log2(k), 1 + math.log2(d))
                    for n, k, d in front if n < n_ref), reverse=True)
    total, i = 0.0, 0
    while i < len(boxes):
        a = boxes[i][0]
        j = i
        while j < len(boxes) and boxes[j][0] == a:
            j += 1
        below = boxes[j][0] if j < len(boxes) else 0.0
        rects = sorted(((b, c) for _, b, c in boxes[:j]), reverse=True)
        area, best_c = 0.0, 0.0
        for idx, (b, c) in enumerate(rects):
            best_c = max(best_c, c)
            b_next = rects[idx + 1][0] if idx + 1 < len(rects) else 0.0
            area += (b - b_next) * best_c
        total += (a - below) * area
        i = j
    return total


def describe_loss(lost, front):
    """Name what left the frontier.

    ``[[n,k,d]]->d'`` for a revision that kept the code on the frontier at a
    lower d, ``-[[n,k,d]]`` otherwise.
    """
    by_nk = {}
    for n, k, d in front:
        by_nk[(n, k)] = max(by_nk.get((n, k), 0), d)
    notes = []
    for n, k, d in sorted(lost):
        now = by_nk.get((n, k))
        if now is not None and now < d:
            notes.append(f"[[{n},{k},{d}]]->{now}")
        else:
            notes.append(f"-[[{n},{k},{d}]]")
    return " ".join(notes)


def replay(repo, n_ref=1000):
    """Replay ``codes/`` on main's first-parent chain; return ``(rows, state)``.

    ``state`` is ``{path: (n, k, d)}`` for every CSS code as of ``HEAD``;
    ``rows`` is one ``(date, sha, n_codes, frontier_points, frontier_codes,
    front, hypervolume, note)`` entry per step that moved the board, oldest
    first, with ``front`` the frontier itself and ``note`` naming what a step
    pushed off it (empty when nothing left).

    ``--first-parent`` is the ordering, not a shortcut: on a PR-merge repo it
    walks what each landing actually did to main, in landing order. Plain
    ``git log`` orders by date, and date order is not ancestry order, so a
    deletion could be applied before the add it deletes (which is how one file
    that HEAD no longer has once survived the replay). A side branch's
    intermediate states are likewise not board states -- main never had them.

    Dates are committer dates (when the landing happened), as UTC days: the
    author date of a squash or merge landing can be days earlier, and a
    bucket keyed on it would file the landing into a week it did not land in.
    """
    commits, blobs = walk(repo)
    state = {}
    rows = []
    prev_front = set()
    for sha, date, changes in commits:
        moved = False
        for status, path, dest in changes:
            if not path.endswith(".json") and not (dest or "").endswith(".json"):
                continue
            if status == "R":
                old = state.pop(path, None)
                new = blobs.get((sha, dest)) if dest else None
                if new and new[3] == "CSS":
                    state[dest] = new[:3]
                    if old != new[:3]:
                        moved = True
                elif old is not None:
                    moved = True
            elif status == "D":
                if state.pop(path, None) is not None:
                    moved = True
            else:
                value = blobs.get((sha, path))
                if value and value[3] == "CSS":
                    if state.get(path) != value[:3]:
                        state[path] = value[:3]
                        moved = True
                elif state.pop(path, None) is not None:
                    moved = True
        if not moved:
            continue
        flat = frontier(set(state.values()))
        front = set(flat)
        on_front = sum(1 for nkd in state.values() if nkd in front)
        note = describe_loss(prev_front - front, flat)
        rows.append((utc_day(date), sha[:9], len(state), len(front), on_front,
                     tuple(flat), hypervolume(flat, n_ref), note))
        prev_front = front
    return rows, state


replay.unparsed = 0


def walk(repo):
    """Return ``(commits, blobs)``: the first-parent landings and every changed blob's params.

    ``commits`` is ``parse_log``'s list, oldest first; ``blobs`` maps each
    ``(sha, path)`` that a landing added, modified, or renamed into to its
    ``(n, k, d, code_type)`` or None. Shared by :func:`replay` and
    :func:`cell_moves`, so the two read history one way.
    """
    log = git(["log", "--first-parent", "--reverse", "--name-status",
               "--format=C %H %cI", "--", "codes/"], repo)
    if log.returncode != 0:
        sys.exit(f"git log failed: {log.stderr.decode().strip()}")
    commits = parse_log(log.stdout.decode())

    requests = []
    for sha, _, changes in commits:
        for status, path, dest in changes:
            # A rename is read at its destination: git reports a rewrite of an
            # unrelated file as a rename when the similarity check matches, so
            # carrying the source's value over invents one no blob has.
            if status == "R" and dest and dest.endswith(".json"):
                requests.append((sha, dest))
            elif status in ("A", "M") and path.endswith(".json"):
                requests.append((sha, path))
    blobs = fetch_params(requests, repo)
    replay.unparsed = sum(1 for v in blobs.values() if v is None)
    return commits, blobs


def landings(commits, blobs):
    """Yield ``(utc_day, sha, changes)`` per landing that changed a code blob.

    ``changes`` is a list of ``(path, old, new, dest)`` with ``old`` and ``new``
    the ``(n, k, d, code_type)`` the path held before and after the landing,
    None on either side for an add or a removal, and ``dest`` the new path when
    the landing renamed the file (a distance revision renames it to its new
    slug), else None. A rename whose source was never held is an add at the
    destination; one whose destination will not parse is a removal.
    """
    state = {}
    for sha, date, changes in commits:
        applied = []
        for status, path, dest in changes:
            if not path.endswith(".json") and not (dest or "").endswith(".json"):
                continue
            if status == "R":
                old = state.pop(path, None)
                new = blobs.get((sha, dest)) if dest else None
                if new:
                    state[dest] = new
                    if old is not None:
                        applied.append((path, old, new, dest))
                    else:
                        applied.append((dest, None, new, None))
                elif old is not None:
                    applied.append((path, old, None, None))
            elif status == "D":
                old = state.pop(path, None)
                if old is not None:
                    applied.append((path, old, None, None))
            else:
                new = blobs.get((sha, path))
                old = state.get(path)
                if new:
                    if old != new:
                        state[path] = new
                        applied.append((path, old, new, None))
                elif old is not None:
                    state.pop(path)
                    applied.append((path, old, None, None))
        if applied:
            yield utc_day(date), sha, applied


class _CellFront:
    """One cell's members as (n, k, d, w) rows, with the board's dominance test.

    A growable array with a liveness mask rather than a dict rebuilt per check:
    the replay asks "is this point beaten by any member" twice per touched cell
    per landing, and a Python-level scan of a cell holding thousands of codes
    at each of thousands of landings would take minutes where this takes
    seconds. A point never dominates itself (no axis is strict), so the test
    runs over all live rows, the point's own included.
    """

    def __init__(self, np):
        self.np = np
        self.rows = np.zeros((64, 4), dtype=np.int64)
        self.alive = np.zeros(64, dtype=bool)
        self.index = {}
        self.size = 0

    def put(self, path, point):
        row = self.index.get(path)
        if row is None:
            if self.size == len(self.rows):
                self.rows = self.np.concatenate([self.rows, self.np.zeros_like(self.rows)])
                self.alive = self.np.concatenate([self.alive, self.np.zeros_like(self.alive)])
            row = self.size
            self.size += 1
            self.index[path] = row
        self.rows[row] = point
        self.alive[row] = True

    def get(self, path):
        row = self.index.get(path)
        return None if row is None else tuple(int(x) for x in self.rows[row])

    def drop(self, path):
        row = self.index.pop(path, None)
        if row is not None:
            self.alive[row] = False

    def best(self):
        """Return ``(kd^2/n, path)`` of the live member with the highest efficiency, or None."""
        if not self.index:
            return None
        arr = self.rows[:self.size].astype(float)
        eff = arr[:, 1] * arr[:, 2] * arr[:, 2] / arr[:, 0]
        eff[~self.alive[:self.size]] = -1.0
        row = int(eff.argmax())
        path = next(p for p, r in self.index.items() if r == row)
        return float(eff[row]), path

    def dominated(self, point):
        """Return True when a live member beats ``point`` on (n, k, d, w).

        The board's own rule (site/build.py ``pareto``): n and w lower is
        better, k and d higher, with at least one axis strict.
        """
        n, k, d, w = point
        arr = self.rows[:self.size]
        live = self.alive[:self.size]
        weak = (arr[:, 0] <= n) & (arr[:, 1] >= k) & (arr[:, 2] >= d) & (arr[:, 3] <= w)
        strict = (arr[:, 0] < n) | (arr[:, 1] > k) | (arr[:, 2] > d) | (arr[:, 3] < w)
        return bool(self.np.any(live & weak & strict))


def cell_moves(repo, classes, *, cell_of=None):
    """Return ``({cell: last move}, landings)``: when each cell's frontier last changed.

    ``classes`` maps a HEAD path (``codes/<slug>.json``) to ``(locality_class,
    weight_class, w, code_type)``, the site's own reading of the entry; it is
    carried back through renames, so a revised entry's earlier names count in
    the same cells. A path no longer on the board cannot be classified and is
    skipped: its removal did move a cell, but which one the record cannot say.
    Classes are read once, at HEAD, so an entry that gained a layout later
    counts in its 2D cells from its first landing.

    A cell moves at a landing when its nondominated set changes: an entry
    that is nondominated among the cell's members lands or is revised, or a
    nondominated entry is removed or revised away. A dominated entry landing
    changes nothing, and neither does its removal, so a batch of dominated
    duplicates leaves every cell where it was. That is the board's own
    frontier rule (site/build.py ``pareto``), applied per cell, with a
    distance revision counting as the move it is.

    Two dates come out per cell, because the frontier rule is permissive (on
    the board today about seven entries in ten are nondominated in their
    cell, since a high-rate low-distance code is beaten by nothing), so the
    frontier moves at most landings. ``record`` is the selective one: the
    last landing that changed the cell's best kd^2/n, up when a new leader
    landed and down when the leader was revised or removed.

    ``cell_of`` maps an entry row ``{locality_class, weight_class}`` to its
    cells; the default is site/build.py's ``cells``. The result maps each
    ``(locality_class, weight_class)`` cell to ``{"frontier": move, "record":
    move}``, each move ``{"date", "commit", "landing", "what", "kind"}`` with
    ``landing`` the 1-based index among the ``landings`` returned beside it,
    so "landings ago" is their difference.
    """
    import numpy as np  # noqa: PLC0415  (the charts stay stdlib-only; this replay does not)

    if cell_of is None:
        site = os.path.join(_REPO, "site")
        if site not in sys.path:
            sys.path.insert(0, site)
        from build import cells as cell_of  # noqa: PLC0415
    commits, blobs = walk(repo)
    classes = dict(classes)
    for _sha, _date, changes in reversed(commits):
        for status, path, dest in changes:
            if status == "R" and dest in classes and path not in classes:
                classes[path] = classes[dest]

    members = {}            # cell -> _CellFront
    last = {}
    best = {}               # cell -> (kd^2/n, path) before the landing
    count = 0
    for date, sha, applied in landings(commits, blobs):
        count += 1
        touched = {}
        for path, old, new, dest in applied:
            cls = classes.get(dest or path) or classes.get(path)
            if cls is None:
                continue
            loc, wc, w, _ct = cls
            if w is None:
                continue
            for cell in cell_of({"locality_class": loc, "weight_class": wc}):
                touched.setdefault(cell, []).append((path, old, new, dest, w))
        for cell, changes in touched.items():
            here = members.get(cell)
            if here is None:
                here = members[cell] = _CellFront(np)
            moved = None
            # removals first, judged against the cell as it stood: a
            # nondominated member leaving changes the frontier, a dominated
            # one leaving changes nothing (whatever beat it still beats
            # everything it beat). A rename that keeps (n, k, d) only re-keys.
            for path, old, new, dest, w in changes:
                if old is None or here.get(path) is None:
                    continue
                point = here.get(path)
                if dest and new and new[:3] == old[:3]:
                    here.drop(path)
                    here.put(dest, point)
                    continue
                if moved is None and not here.dominated(point):
                    moved = (dest or path, old, new, w, "revised" if new else "removed")
                here.drop(path)
            for path, old, new, dest, w in changes:
                if new is not None and not (dest and old and new[:3] == old[:3]):
                    here.put(dest or path, (new[0], new[1], new[2], w))
            # then additions, judged against the cell as it now stands: a
            # dominated arrival joins no frontier and knocks nothing off one
            for path, old, new, dest, w in changes:
                if new is None or moved is not None or (dest and old and new[:3] == old[:3]):
                    continue
                if not here.dominated(here.get(dest or path)):
                    moved = (dest or path, old, new, w, "revised" if old else "landed")
            entry = last.setdefault(cell, {"frontier": None, "record": None})
            if moved is not None:
                path, old, new, w, kind = moved
                shown = new or old
                slug = os.path.basename(path)[:-5]
                entry["frontier"] = {
                    "date": date, "commit": sha[:9], "landing": count,
                    "what": f"[[{shown[0]},{shown[1]},{shown[2]}]] w={w} {slug}",
                    "kind": kind}
            now = here.best()
            before = best.get(cell)
            if now is not None and (before is None or abs(now[0] - before[0]) > 1e-9):
                eff, path = now
                point = here.get(path)
                slug = os.path.basename(path)[:-5]
                entry["record"] = {
                    "date": date, "commit": sha[:9], "landing": count,
                    "what": f"[[{point[0]},{point[1]},{point[2]}]] w={point[3]} {slug}",
                    "kind": ("raised" if before is None or eff > before[0] else "lowered"),
                    "kd2_over_n": round(eff, 3)}
            best[cell] = now
    return last, count


# Oldest -> newest: light-warm to dark-cool, so today's staircase is the
# darkest line on the page while the earliest ones still read against white.
_RAMP = ["#f6bd60", "#f8961e", "#e76f51", "#a34a7c", "#4a6fa5", "#1d3557"]
_LOSS = "#d62828"


def ramp(t):
    """Hex colour lerped along ``_RAMP`` at position t in [0, 1]."""
    pos = min(max(float(t), 0.0), 1.0) * (len(_RAMP) - 1)
    i = min(int(pos), len(_RAMP) - 2)
    f = pos - i
    lo = [_RAMP[i][j:j + 2] for j in (1, 3, 5)]
    hi = [_RAMP[i + 1][j:j + 2] for j in (1, 3, 5)]
    mix = [round(int(a, 16) + (int(b, 16) - int(a, 16)) * f)
           for a, b in zip(lo, hi)]
    return "#%02x%02x%02x" % tuple(mix)


def bucket_key(iso, bucket):
    """Sort key assigning a date to its day / ISO week / month bucket."""
    day = datetime.date.fromisoformat(iso)
    if bucket == "day":
        return (day.toordinal(),)
    if bucket == "week":
        year, week, _ = day.isocalendar()
        return (year, week)
    return (day.year, day.month)


def snapshots(rows, bucket):
    """Report the board as it stood at the last commit of each bucket.

    Oldest first. A bucket with no commit simply has no row: its frontier is
    the previous bucket's, which is the staircase that would be drawn for it
    anyway.
    """
    out, seen = [], {}
    for row in rows:
        key = bucket_key(row[0], bucket)
        if key in seen:
            out[seen[key]] = row
        else:
            seen[key] = len(out)
            out.append(row)
    return out


def floor_staircase(front, floor):
    """Return the (n, k) staircase of the frontier codes with ``d >= floor``.

    Returns ``(n, k, d)`` triples with k strictly rising in n; ``d`` is the
    largest distance standing at that (n, k). This is the two-axis frontier of
    the slice, and every point of it is a point of the three-axis frontier.
    """
    best_d = {}
    for n, k, d in front:
        if d >= floor:
            best_d[(n, k)] = max(best_d.get((n, k), 0), d)
    out, best_k = [], -1
    for (n, k), d in sorted(best_d.items(), key=lambda t: (t[0][0], -t[0][1])):
        if k > best_k:
            best_k = k
            out.append((n, k, d))
    return out


def k_at(stair, n):
    """``k_max`` of a staircase at block length n (0 left of its first step)."""
    best = 0
    for sn, sk, _ in stair:
        if sn > n:
            break
        best = sk
    return best


def region_rects(old, new, n_right):
    """Where two staircases differ, as ``(kind, n0, n1, k_lo, k_hi)`` rects.

    ``kind`` is ``gain`` where the newer staircase is higher and ``loss``
    where the older one was; the last rect runs out to ``n_right``, since past
    the last step k_max stays flat.
    """
    cuts = sorted({n for n, _, _ in old} | {n for n, _, _ in new})
    out = []
    for a, b in zip(cuts, cuts[1:] + [n_right]):
        ko, kn = k_at(old, a), k_at(new, a)
        if kn > ko:
            out.append(("gain", a, b, ko, kn))
        elif kn < ko:
            out.append(("loss", a, b, kn, ko))
    return out


def log_ticks(lo, hi):
    """Return the 1-2-5 ticks inside [lo, hi]."""
    ticks, mag = [], 10 ** math.floor(math.log10(max(lo, 1e-9)))
    while mag <= hi:
        for m in (1, 2, 5):
            v = m * mag
            if lo <= v <= hi:
                ticks.append(v)
        mag *= 10
    return ticks


def place_labels(points, panel):
    """Place labels greedily: three candidate offsets per dot, else no label.

    The first offset that neither overlaps a placed label nor leaves the
    panel wins.
    """
    x0, y0, x1, y1 = panel
    placed, out = [], []
    for x, y, text in points:
        w, h = 4.9 * len(text), 9.0
        for dx, dy, anchor in ((4, -4, "start"), (4, 11, "start"),
                               (-4, -4, "end")):
            lx, ly = x + dx, y + dy
            bx0 = lx if anchor == "start" else lx - w
            box = (bx0, ly - h, bx0 + w, ly)
            if box[0] < x0 or box[2] > x1 or box[1] < y0 or box[3] > y1:
                continue
            if any(not (box[2] < p[0] or box[0] > p[2] or box[3] < p[1]
                        or box[1] > p[3]) for p in placed):
                continue
            placed.append(box)
            out.append((lx, ly, anchor, text))
            break
    return out


_SUBTITLE = ('CSS board replayed from git history; each panel keeps the codes '
             'with d at or above its floor; lower n and higher k are better; '
             'check weight and locality ignored; log axes')


def render_panels(snaps, floors, title, subtitle, colors, labels, extent,
                  timeline=None):
    """Return the SVG text of the panel chart for the given snapshots.

    One panel per distance floor, one staircase per snapshot in ``snaps``
    (oldest first), coloured and labelled per entry. Each panel keeps the
    frontier codes clearing its floor, on log axes whose range is set by
    ``extent`` (rows, usually every snapshot the caller will ever draw, so
    animation frames share axes). Consecutive snapshots are
    compared as regions rather than as overlaid lines: the area gained is
    tinted in the newer colour, the area lost is red-hatched, and only a
    staircase that differs from the next one is drawn, so an unchanged
    snapshot is not a second line in a second colour. The last staircase is
    heavy and carries a dot and an ``n,k,d`` label per code where the label
    fits. Each staircase ends at its last code and continues dashed: past the
    largest n no larger k exists, but no code stands out there. ``timeline``
    is ``(first_date, last_date, current_date)`` for a strip under the panels
    that places the frame in the board's history.
    """
    stairs = [[floor_staircase(s[5], f) for s in snaps] for f in floors]
    ext_pts = [p for s in extent for f in floors
               for p in floor_staircase(s[5], f)]
    if not ext_pts:
        sys.exit("no frontier code clears the lowest floor")

    n_lo, n_hi = min(p[0] for p in ext_pts), max(p[0] for p in ext_pts)
    k_hi = max(p[1] for p in ext_pts)
    n_min, n_max = n_lo / 1.25, n_hi * 1.6
    k_min, k_max = 1 / 1.25, k_hi * 1.8

    cols = 3
    rws = -(-len(floors) // cols)
    w, left, right, top, gap_x, gap_y = 1180, 58, 18, 74, 44, 52
    bot = 78 + (30 if timeline else 0)
    pw = (w - left - right - (cols - 1) * gap_x) / cols
    ph = 300
    h = top + rws * ph + (rws - 1) * gap_y + bot

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="system-ui,sans-serif">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{left}" y="28" font-size="15" font-weight="600">{title}'
        '</text>',
        f'<text x="{left}" y="46" font-size="11.5" fill="#666">{subtitle}'
        '</text>',
        '<defs><pattern id="loss" patternUnits="userSpaceOnUse" width="6" '
        'height="6" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" '
        f'y2="6" stroke="{_LOSS}" stroke-width="2.2"/></pattern></defs>',
    ]

    for idx, (floor, per_floor) in enumerate(zip(floors, stairs)):
        r, c = divmod(idx, cols)
        x0 = left + c * (pw + gap_x)
        y0 = top + r * (ph + gap_y)
        x1, y1 = x0 + pw, y0 + ph

        def sx(n, x0=x0, x1=x1):
            return x0 + (math.log(n) - math.log(n_min)) / \
                (math.log(n_max) - math.log(n_min)) * (x1 - x0)

        def sy(k, y0=y0, y1=y1):
            return y1 - (math.log(max(k, k_min)) - math.log(k_min)) / \
                (math.log(k_max) - math.log(k_min)) * (y1 - y0)

        parts.append(f'<clipPath id="p{idx}"><rect x="{x0:.1f}" y="{y0:.1f}" '
                     f'width="{pw:.1f}" height="{ph:.1f}"/></clipPath>')
        for v in log_ticks(k_min, k_max):
            yy = sy(v)
            parts.append(f'<line x1="{x0:.1f}" y1="{yy:.1f}" x2="{x1:.1f}" '
                         f'y2="{yy:.1f}" stroke="#eee"/>')
            parts.append(f'<text x="{x0 - 6:.1f}" y="{yy + 3.5:.1f}" '
                         f'font-size="9.5" fill="#888" text-anchor="end">{v:g}'
                         '</text>')
        for v in log_ticks(n_min, n_max):
            xx = sx(v)
            parts.append(f'<line x1="{xx:.1f}" y1="{y0:.1f}" x2="{xx:.1f}" '
                         f'y2="{y1:.1f}" stroke="#f2f2f2"/>')
            parts.append(f'<text x="{xx:.1f}" y="{y1 + 13:.1f}" font-size="9.5" '
                         f'fill="#888" text-anchor="middle">{v:g}</text>')

        parts.append(f'<g clip-path="url(#p{idx})">')
        for i in range(1, len(per_floor)):
            for kind, a, b, klo, khi in region_rects(per_floor[i - 1],
                                                     per_floor[i], n_max):
                # A gain is tinted with the snapshot that made it, so the
                # shading itself says when; a loss is a red hatch, which no
                # tint in the ramp can be mistaken for.
                fill = (f'fill="{colors[i]}" fill-opacity="0.16"'
                        if kind == "gain" else 'fill="url(#loss)"')
                parts.append(
                    f'<rect x="{sx(a):.1f}" y="{sy(khi):.1f}" '
                    f'width="{sx(b) - sx(a):.1f}" '
                    f'height="{sy(klo) - sy(khi):.1f}" {fill}/>')
        for i, stair in enumerate(per_floor):
            if not stair:
                continue
            last = i == len(per_floor) - 1
            if not last and stair == per_floor[i + 1]:
                continue
            pts = [f"M{sx(stair[0][0]):.1f},{sy(stair[0][1]):.1f}"]
            for j in range(1, len(stair)):
                n, k, _ = stair[j]
                pts.append(f"L{sx(n):.1f},{sy(stair[j - 1][1]):.1f}")
                pts.append(f"L{sx(n):.1f},{sy(k):.1f}")
            width = 2.2 if last else 1.4
            parts.append(f'<path d="{" ".join(pts)}" fill="none" '
                         f'stroke="{colors[i]}" stroke-width="{width}" '
                         'stroke-linejoin="round"/>')
            ex, ey = sx(stair[-1][0]), sy(stair[-1][1])
            parts.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{x1:.1f}" '
                         f'y2="{ey:.1f}" stroke="{colors[i]}" '
                         f'stroke-width="{width * 0.6:.1f}" '
                         'stroke-dasharray="3 3"/>')
        parts.append("</g>")

        today = per_floor[-1]
        dots = [(sx(n), sy(k), f"{n},{k},{d}") for n, k, d in today]
        for x, y, _ in dots:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" '
                         f'fill="{colors[-1]}" stroke="#fff" stroke-width="1"/>')
        for lx, ly, anchor, text in place_labels(dots, (x0, y0, x1, y1)):
            # A white halo keeps a label legible where it crosses a line.
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="8.5" '
                         f'fill="#333" text-anchor="{anchor}" stroke="#fff" '
                         'stroke-width="2.5" stroke-linejoin="round" '
                         f'paint-order="stroke">{text}</text>')

        parts.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{pw:.1f}" '
                     f'height="{ph:.1f}" fill="none" stroke="#bbb"/>')
        parts.append(f'<text x="{x0 + 6:.1f}" y="{y0 - 6:.1f}" font-size="12" '
                     f'font-weight="600" fill="#333">d ≥ {floor}'
                     f'<tspan dx="10" font-weight="400" fill="#777">'
                     f'{len(today)} codes on the staircase</tspan></text>')
        if r == rws - 1:
            parts.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{y1 + 28:.1f}" '
                         'font-size="10.5" fill="#666" text-anchor="middle">'
                         'block length n</text>')
        if c == 0:
            parts.append(f'<text transform="translate({x0 - 34:.1f},'
                         f'{(y0 + y1) / 2:.1f}) rotate(-90)" font-size="10.5" '
                         'fill="#666" text-anchor="middle">logical qubits k'
                         '</text>')

    # Legend: each snapshot as its line over its tint (the tint is the region
    # that snapshot gained), then the loss hatch and the dot.
    ly = h - 22
    lx = left
    for i, (label, color) in enumerate(zip(labels, colors)):
        parts.append(f'<rect x="{lx}" y="{ly - 11}" width="22" height="10" '
                     f'fill="{color}" fill-opacity="0.16"/>')
        parts.append(f'<line x1="{lx}" y1="{ly - 11}" x2="{lx + 22}" '
                     f'y2="{ly - 11}" stroke="{color}" '
                     f'stroke-width="{2.4 if i == len(labels) - 1 else 1.6}"/>')
        parts.append(f'<text x="{lx + 27}" y="{ly}" font-size="10.5" '
                     f'fill="#444">{label}</text>')
        lx += 27 + 5.4 * len(label) + 16
    parts.append(f'<text x="{lx}" y="{ly}" font-size="10.5" fill="#777">'
                 '(tint: region that snapshot gained)</text>')
    lx += 5.4 * 35 + 16
    parts.append(f'<rect x="{lx}" y="{ly - 11}" width="22" height="10" '
                 'fill="url(#loss)"/>')
    parts.append(f'<text x="{lx + 27}" y="{ly}" font-size="10.5" fill="#444">'
                 'lost (correction or removal)</text>')
    lx += 27 + 5.4 * 28 + 16
    parts.append(f'<circle cx="{lx + 5}" cy="{ly - 5}" r="2.6" '
                 f'fill="{colors[-1]}"/>')
    parts.append(f'<text x="{lx + 14}" y="{ly}" font-size="10.5" fill="#444">'
                 'code on the last staircase (n,k,d)</text>')

    if timeline:
        # A strip from the board's first landing to its last, month ticks,
        # and a marker at this frame's date.
        first, last, cur = (datetime.date.fromisoformat(t).toordinal()
                            for t in timeline)
        ty, tx0, tx1 = h - 52, left, w - right

        def tx(day):
            return tx0 + (day - first) / max(last - first, 1) * (tx1 - tx0)

        parts.append(f'<line x1="{tx0}" y1="{ty}" x2="{tx1}" y2="{ty}" '
                     'stroke="#ccc" stroke-width="2"/>')
        parts.append(f'<line x1="{tx0}" y1="{ty}" x2="{tx(cur):.1f}" '
                     f'y2="{ty}" stroke="{colors[-1]}" stroke-width="2"/>')
        day = datetime.date.fromordinal(first).replace(day=1)
        while day.toordinal() <= last:
            if day.toordinal() >= first:
                parts.append(f'<line x1="{tx(day.toordinal()):.1f}" '
                             f'y1="{ty - 4}" x2="{tx(day.toordinal()):.1f}" '
                             f'y2="{ty + 4}" stroke="#aaa"/>')
                parts.append(f'<text x="{tx(day.toordinal()):.1f}" '
                             f'y="{ty + 15}" font-size="9" fill="#888" '
                             f'text-anchor="middle">{day.strftime("%b")}</text>')
            day = (day.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        parts.append(f'<circle cx="{tx(cur):.1f}" cy="{ty}" r="4.5" '
                     f'fill="{colors[-1]}" stroke="#fff" stroke-width="1.5"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def svg_frontier(rows, path, bucket="month", floors=_FLOORS):
    """Write the static panel chart, one ramp-coloured staircase per snapshot."""
    snaps = snapshots(rows, bucket)
    if not snaps:
        sys.exit("no frontier snapshots found to plot")
    colors = ([ramp(1.0)] if len(snaps) == 1 else
              [ramp(i / (len(snaps) - 1)) for i in range(len(snaps))])
    text = render_panels(
        snaps, floors,
        f"Board (n, k) frontier by distance floor, as of {snaps[-1][0]}",
        _SUBTITLE, colors, [f"as of {s[0]}" for s in snaps], snaps)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return snaps


_PREV, _CUR = "#9a9a9a", "#1d3557"


def frame_svgs(rows, bucket="day", floors=_FLOORS):
    """Yield ``(date, svg_text)`` frames of the animation, oldest first.

    Each frame draws the frontier as of a snapshot, heavy, over the previous
    frame's in thin grey, with the region gained since tinted and the region
    lost hatched, on axes shared across every frame. A snapshot whose six
    staircases all equal the previous frame's is folded into it -- the
    frontier often moves only in d, off every (n, k) staircase -- and the
    frame's title then spans the dates it stayed current, so every frame is
    a visible change and the last frame ends on the last snapshot. The
    subtitle carries the board's size and the frontier's hypervolume as a
    share of the final frame's, and the strip below places the frame in time.
    """
    snaps = snapshots(rows, bucket)
    final_hv = snaps[-1][6] or 1.0
    runs = []
    for snap in snaps:
        shape = tuple(tuple(floor_staircase(snap[5], f)) for f in floors)
        if runs and runs[-1][0] == shape:
            runs[-1][2] = snap
        else:
            runs.append([shape, snap, snap])
    for i, (_shape, first, last) in enumerate(runs):
        shown = ([runs[i - 1][1]] if i else []) + [first]
        colors = ([_PREV] if i else []) + [_CUR]
        labels = (["previous frame"] if i else []) + [f"as of {first[0]}"]
        when = first[0] if first is last else \
            f"{first[0]} (unchanged through {last[0]})"
        subtitle = (f"{last[2]} CSS codes, {last[3]} (n, k, d) points on the "
                    f"frontier, hypervolume {100 * last[6] / final_hv:.0f}% "
                    "of the final frame's; lower n and higher k are better; "
                    "log axes")
        yield first[0], render_panels(
            shown, floors, f"Board (n, k) frontier by distance floor, {when}",
            subtitle, colors, labels, snaps,
            timeline=(snaps[0][0], snaps[-1][0], last[0]))


def write_frames(rows, directory, bucket="day", floors=_FLOORS):
    """Write one SVG per snapshot into ``directory``; return their paths."""
    os.makedirs(directory, exist_ok=True)
    paths = []
    for i, (date, text) in enumerate(frame_svgs(rows, bucket, floors)):
        path = os.path.join(directory, f"frame_{i:04d}_{date}.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        paths.append(path)
    return paths


def write_gif(rows, path, bucket="day", floors=_FLOORS, frame_ms=300,
              hold_ms=2500, width=1180):
    """Assemble the frames into an animated GIF; return the frame count.

    The frames are drawn here; rasterizing them takes ``rsvg-convert``
    (librsvg) on PATH and assembling them takes Pillow, which the
    ``research`` extra brings in. The last frame holds for ``hold_ms``.
    """
    try:
        from PIL import Image
    except ImportError:
        sys.exit("--gif needs Pillow: run under `uv run --frozen --extra "
                 "research`")
    if shutil.which("rsvg-convert") is None:
        sys.exit("--gif needs rsvg-convert (librsvg) on PATH to rasterize "
                 "the frames")
    images = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, (date, text) in enumerate(frame_svgs(rows, bucket, floors)):
            svg = os.path.join(tmp, f"{i:04d}.svg")
            png = os.path.join(tmp, f"{i:04d}.png")
            with open(svg, "w", encoding="utf-8") as f:
                f.write(text)
            subprocess.run(["rsvg-convert", "-w", str(width), svg, "-o", png],
                           check=True)
            with Image.open(png) as im:
                images.append(im.convert("RGB").quantize(colors=128))
    if not images:
        sys.exit("no frontier snapshots found to animate")
    durations = [frame_ms] * len(images)
    durations[-1] = hold_ms
    images[0].save(path, save_all=True, append_images=images[1:],
                   duration=durations, loop=0)
    return len(images)


def svg_history(rows, path):
    """Frontier hypervolume over time, as a share of today's, on a date axis.

    A step line: the value holds until the next landing moves it. Every step
    down is a red dot, and the largest ones are named with what left the
    frontier, so a distance revision reads as the event it was.
    """
    w, h, left, right, top, bot = 980, 380, 62, 18, 52, 46
    days = [datetime.date.fromisoformat(r[0]).toordinal() for r in rows]
    d0, d1 = days[0], days[-1]
    today = rows[-1][6] or 1.0
    vals = [r[6] / today for r in rows]
    ymax = max(vals) * 1.08

    def x(day):
        return left + (day - d0) / max(d1 - d0, 1) * (w - left - right)

    def y(v):
        return h - bot - v / ymax * (h - top - bot)

    pts, prev = [], None
    for day, v in zip(days, vals):
        if prev is None:
            pts.append(f"M{x(day):.1f},{y(v):.1f}")
        elif v != prev:
            pts.append(f"L{x(day):.1f},{y(prev):.1f}")
            pts.append(f"L{x(day):.1f},{y(v):.1f}")
        prev = v
    pts.append(f"L{x(days[-1]):.1f},{y(prev):.1f}")

    # Steps down, each with its size relative to the value it stepped from.
    drops = [((vals[i - 1] - vals[i]) / vals[i - 1], i)
             for i in range(1, len(vals)) if vals[i] < vals[i - 1]]
    # The largest get a numeral at the dot and a line in the list above the
    # curve's low early stretch, where there is room; labels at the dots
    # collide.
    named = {i: rank + 1 for rank, (_, i)
             in enumerate(sorted(drops, reverse=True)[:8])}

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="system-ui,sans-serif">',
        f'<rect width="{w}" height="{h}" fill="#ffffff"/>',
        f'<text x="{left}" y="24" font-size="15" font-weight="600">'
        'Board (n, k, d) frontier hypervolume over time</text>',
        f'<text x="{left}" y="40" font-size="11.5" fill="#666">'
        f'CSS board replayed from git history; share of today\'s '
        f'({rows[-1][0]}) value; log2 coordinates; every step down marked, '
        'the largest named</text>',
    ]
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        if v > ymax:
            break
        yy = y(v)
        parts.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{w - right}" '
                     f'y2="{yy:.1f}" stroke="#eee"/>')
        parts.append(f'<text x="{left - 8}" y="{yy + 4:.1f}" font-size="11" '
                     f'fill="#888" text-anchor="end">{v:.2f}</text>')
    # Six date ticks, spaced by DATE not by index (commits cluster toward the
    # end, so evenly spaced indices give unevenly spaced dates).
    for i in range(6):
        day = d0 + round(i * (d1 - d0) / 5)
        xx = x(day)
        anchor = "start" if i == 0 else "end" if i == 5 else "middle"
        label = datetime.date.fromordinal(day).strftime("%m-%d")
        parts.append(f'<line x1="{xx:.1f}" y1="{top}" x2="{xx:.1f}" '
                     f'y2="{h - bot}" stroke="#f4f4f4"/>')
        parts.append(f'<text x="{xx:.1f}" y="{h - bot + 16}" font-size="11" '
                     f'fill="#888" text-anchor="{anchor}">{label}</text>')
    parts.append(f'<path d="{" ".join(pts)}" fill="none" stroke="#1d3557" '
                 'stroke-width="2"/>')
    for _, i in drops:
        xx, yy = x(days[i]), y(vals[i])
        parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="3.2" '
                     f'fill="{_LOSS}"/>')
        if i in named:
            parts.append(f'<text x="{xx:.1f}" y="{yy + 15:.1f}" font-size="9" '
                         f'fill="{_LOSS}" text-anchor="middle" stroke="#fff" '
                         'stroke-width="2" paint-order="stroke">'
                         f'{named[i]}</text>')
    lx, ly = left + 12, top + 12
    parts.append(f'<text x="{lx}" y="{ly}" font-size="10" fill="#666">'
                 f'{len(drops)} steps down; the largest:</text>')
    rel = dict((i, r) for r, i in drops)
    for i, rank in sorted(named.items(), key=lambda t: t[1]):
        ly += 13
        parts.append(f'<text x="{lx}" y="{ly}" font-size="10" fill="{_LOSS}">'
                     f'{rank}</text>')
        parts.append(f'<text x="{lx + 14}" y="{ly}" font-size="10" '
                     f'fill="#444">{rows[i][0]}  {rows[i][7]}  '
                     f'−{100 * rel[i]:.2f}%</text>')
    parts.append(f'<text transform="translate(16,{(top + h - bot) / 2:.1f}) '
                 'rotate(-90)" font-size="11" fill="#666" text-anchor="middle">'
                 'share of today\'s hypervolume</text>')
    parts.append(f'<line x1="{left}" y1="{h - bot}" x2="{w - right}" '
                 f'y2="{h - bot}" stroke="#bbb"/>')
    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts) + "\n")
    return drops


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=_REPO,
                    help="repository to replay (default: this checkout)")
    ap.add_argument("--out", default=None,
                    help="write the series as CSV here (default: print a summary)")
    ap.add_argument("--plot", default=None,
                    help="write the per-distance-floor staircase panels as an SVG here")
    ap.add_argument("--bucket", default=None,
                    choices=("day", "week", "month"),
                    help="snapshot spacing (default: month for --plot, day "
                         "for --frames and --gif)")
    ap.add_argument("--floors", default=",".join(map(str, _FLOORS)),
                    help="comma-separated distance floors, one panel each")
    ap.add_argument("--plot-history", default=None,
                    help="write the hypervolume-over-time chart as an SVG here")
    ap.add_argument("--frames", default=None,
                    help="write one panel-chart SVG per snapshot into this directory")
    ap.add_argument("--gif", default=None,
                    help="write the panel chart as an animated GIF here, one "
                         "frame per snapshot (needs rsvg-convert and Pillow)")
    ap.add_argument("--frame-ms", type=int, default=300,
                    help="GIF frame duration in ms (default: 300)")
    ap.add_argument("--n-ref", type=int, default=1000,
                    help="hypervolume reference block length (default: 1000)")
    args = ap.parse_args()

    rows, state = replay(args.repo, args.n_ref)
    if not rows:
        sys.exit("no board-moving commits found; is --repo the board's repo?")
    floors = tuple(int(f) for f in args.floors.split(","))

    if args.plot:
        snaps = svg_frontier(rows, args.plot, args.bucket or "month", floors)
        print(f"wrote {len(floors)} panels x {len(snaps)} snapshots "
              f"({snaps[0][0]} .. {snaps[-1][0]}) to {args.plot}")

    if args.frames:
        paths = write_frames(rows, args.frames, args.bucket or "day", floors)
        print(f"wrote {len(paths)} frames to {args.frames}")

    if args.gif:
        count = write_gif(rows, args.gif, args.bucket or "day", floors,
                          args.frame_ms)
        print(f"wrote {count} frames to {args.gif}")

    if args.plot_history:
        drops = svg_history(rows, args.plot_history)
        print(f"wrote hypervolume history with {len(drops)} steps down to "
              f"{args.plot_history}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("date,commit,codes,frontier_points,frontier_codes,"
                    "hypervolume,note\n")
            for date, sha, n, fp, fc, _front, hv, note in rows:
                f.write(f"{date},{sha},{n},{fp},{fc},{hv:.3f},{note}\n")
        print(f"wrote {len(rows)} rows to {args.out}")

    date, sha, n, fp, fc, _front, hv, _note = rows[-1]
    print(f"{len(rows)} board-moving commits, {rows[0][0]} .. {rows[-1][0]}"
          + (f"; {replay.unparsed} blobs did not parse and were skipped"
             if replay.unparsed else ""))
    print(f"current: {n} CSS codes, {fp} (n,k,d) points on the frontier, "
          f"{fc} codes standing on it, hypervolume {hv:.1f}")

    if not args.out:
        step = max(1, len(rows) // 10)
        for row in rows[::step] + [rows[-1]]:
            print(f"  {row[0]}  codes={row[2]:<5} frontier_points={row[3]:<4} "
                  f"hypervolume={row[6]:.1f}")
        downs = [(rows[i - 1][6], rows[i]) for i in range(1, len(rows))
                 if rows[i][6] < rows[i - 1][6]]
        print(f"{len(downs)} steps down:")
        for before, row in downs:
            pct = 100 * (before - row[6]) / before
            print(f"  {row[0]}  {row[1]}  {pct:5.1f}%  {row[7]}")


if __name__ == "__main__":
    main()
