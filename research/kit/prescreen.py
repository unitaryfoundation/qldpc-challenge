"""Pre-gate checks a sampler can run on its own candidate (issue #3620).

Two of the gate's refusals are decided before any distance work, and the
staged record of the ten days before #3620 puts most of the search's lost
gate runs there: 25 of the 64 runs at n <= 64 were refused as disconnected
direct sums, and the weight-6 band drew 10 Weisfeiler-Leman (WL) signature
flags against entries the board already held. Both are properties of the
generator, and both are cheap to decide before a candidate is screened,
packaged, or gated. This module decides them with the verifier's own
arithmetic, imported from verify/ and never reimplemented:

* ``block_structure``: the components of the submitted Tanner graph
  (``_tanner_component_count``) and the independent blocks of the
  stabilizer group (``_stabilizer_block_count``, which reads the row space,
  so a redundant check spanning two blocks cannot hide a direct sum). The
  gate's ``tanner_connected`` and ``stabilizer_group_connected`` checks are
  these two numbers compared with 1.
* ``identity``: the exact fingerprint (``css_fingerprint``) and the WL
  ``signature`` under which the gate recognizes a code.
* ``board_index`` and ``lookup``: the index the gate itself dedups against
  (``validate_candidate._board_entries``), each entry under its own
  fingerprint and signature and those of its local-Hadamard images, so a
  Hadamard-relabeled copy of a board code is recognized too.

The verdicts are advisory and subtractive. An exact match means the board
holds this code and the gate will refuse it as a duplicate; a WL match
means the board probably holds a permutation of it, and the gate will admit
the candidate with a ``possibly equivalent`` label that a human then has to
resolve in ``provenance.notes`` (``promote.equivalence_finding``). Neither
is a distance claim, and nothing here replaces the gate: a candidate that
clears every check here can still be refuted there.

``search.screen`` and ``search.screen_adaptive`` run these checks on every
candidate before spending the distance screen, and ``submit.make_submission``
refuses to package a direct sum.

``preflight`` (issue #3616) is the same idea one stage later, on the packaged
document: it runs ``qldpc_verify.verify(doc, refute=False)``, the verifier's
structural half, and reports the checks the gate's verify step would fail
the document on, with the verifier's own detail strings. Of the 355 gate
runs staged in the ten days before #3616, 41 were refused on such checks
(disconnected constructions, check weight over the cap, CSS codes typed
``stabilizer``, malformed documents), and the gate had spent the random
distance search on most of them first: the verifier records a structural
failure and carries on, and a valid witness earns a distance to refute.
``submit.save_submission`` refuses to stage a document that fails it and
``coordination.gate_and_record`` refuses to gate one. For a candidate
already staged as a file:

    uv run python research/kit/prescreen.py research/candidates/<run>/<n>-<k>-<d>.json

prints the preflight, the structure, and the board match and exits 1 when
the gate would refuse the candidate on any of them.
"""

import argparse
import json
import os
import re
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "verify"))
import frontier  # noqa: E402
import qldpc_verify  # noqa: E402
import validate_candidate  # noqa: E402

NO_MATCH = {"exact": None, "wl": None}


def _as_matrices(HX, HZ):
    HX = np.asarray(HX, dtype=np.int8) % 2
    HZ = np.asarray(HZ, dtype=np.int8) % 2
    if HX.ndim != 2 or HZ.ndim != 2 or HX.shape[1] != HZ.shape[1]:
        raise ValueError("HX and HZ must be 2-d arrays over the same qubits")
    return HX, HZ


def _supports(H):
    return [[int(q) for q in np.nonzero(r)[0]] for r in H]


def direct_sum(A, B):
    """Stack two check matrices block-diagonally: the code A plus B on disjoint qubits.

    What a decoupled generator builds by accident, and what the tests build
    on purpose.
    """
    A, B = np.asarray(A, dtype=np.int8), np.asarray(B, dtype=np.int8)
    top = np.concatenate([A, np.zeros((A.shape[0], B.shape[1]), np.int8)], axis=1)
    bot = np.concatenate([np.zeros((B.shape[0], A.shape[1]), np.int8), B], axis=1)
    return np.concatenate([top, bot], axis=0)


def block_structure(HX, HZ):
    """How many codes (HX, HZ) is.

    Returns ``{"tanner_components", "blocks", "block_sizes", "connected"}``.
    ``tanner_components`` counts the components of the Tanner graph on the
    submitted rows, qubits and checks together, isolated qubits included.
    ``blocks`` counts the independent blocks of the stabilizer GROUP, read
    off the reduced row echelon form of each side, so one redundant check
    spanning two otherwise disjoint blocks joins the graph without joining
    the code; ``block_sizes`` are the blocks' qubit counts, largest first.
    ``connected`` is both counts equal to 1, which is what the gate requires.
    """
    HX, HZ = _as_matrices(HX, HZ)
    n = int(HX.shape[1])
    components = qldpc_verify._tanner_component_count({"X": _supports(HX), "Z": _supports(HZ)}, n)
    blocks, sizes = qldpc_verify._stabilizer_block_count(HX, HZ, n)
    return {
        "tanner_components": int(components),
        "blocks": int(blocks),
        "block_sizes": [int(s) for s in sizes],
        "connected": components == 1 and blocks == 1,
    }


def describe_structure(structure):
    """One line in the gate's own words, or "one connected code"."""
    if structure["connected"]:
        return "one connected code"
    parts = []
    if structure["tanner_components"] != 1:
        parts.append(f"Tanner graph has {structure['tanner_components']} connected component(s)")
    if structure["blocks"] != 1:
        sizes = ", ".join(map(str, structure["block_sizes"][:6]))
        if structure["blocks"] > 6:
            sizes += ", ..."
        parts.append(
            f"stabilizer group splits into {structure['blocks']} "
            f"independent block(s) on disjoint qubit sets "
            f"(sizes {sizes})"
        )
    return "; ".join(parts)


def identity(HX, HZ):
    """Return the fingerprint and WL signature the gate recognizes (HX, HZ) by.

    Computed as ``qldpc_verify.verify`` computes them for a CSS submission
    (``css_fingerprint`` and ``signature``); a test pins both to the
    verifier's own report. The fingerprint equals ``search.fingerprint``.
    """
    HX, HZ = _as_matrices(HX, HZ)
    n = int(HX.shape[1])
    # signature() hashes n, the recomputed k, the check-weight profile, and
    # the WL colors; it only copies "k" and "distance" into its return value,
    # so the placeholders below never reach the hash.
    doc = {"code_type": "CSS", "n": n, "k": 0, "distance": {"d": 0}, "checks": {"X": _supports(HX), "Z": _supports(HZ)}}
    return {"fingerprint": qldpc_verify.css_fingerprint(HX, HZ), "signature": qldpc_verify.signature(doc)["hash"]}


_CACHE = {}


def board_index(*, refresh=False):
    """Return the board as the gate sees it for dedup.

    A list of ``{"name", "n", "k", "d", "fingerprints", "signatures"}``, one
    per entry, built from ``validate_candidate._board_entries()``: each
    entry's own fingerprint and signature plus those of its local-Hadamard
    images, the sets the gate compares a candidate against. The underlying
    scan is memoized on the board's bytes (and on disk under the gitignored
    ``research/candidates/.boardcache``), so the first call in a process
    costs what one gate run costs and later calls are free; this module
    keeps the result for the process, and ``refresh=True`` rebuilds it.
    """
    if "index" not in _CACHE or refresh:
        out = []
        for b in validate_candidate._board_entries():
            fps = {b.get("fingerprint")} | set(b.get("css_fingerprints") or [])
            sigs = {b.get("sig")} | set(b.get("css_sigs") or [])
            out.append(
                {
                    "name": b["name"],
                    "n": b["n"],
                    "k": b["k"],
                    "d": b["d"],
                    "fingerprints": fps - {None},
                    "signatures": sigs - {None},
                }
            )
        _CACHE["index"] = out
    return _CACHE["index"]


def lookup(ident, index=None):
    """Which board entry, if any, a code with this ``identity`` already is.

    Returns ``{"exact", "wl"}``. ``exact`` names the first entry whose
    fingerprint set contains the candidate's: the same code (possibly up to
    a Hadamard relabeling), which the gate refuses as a duplicate. ``wl``
    names the first entry sharing the WL signature but not the fingerprint:
    a probable permutation of a board code, which the gate admits with a
    ``possibly equivalent`` label. The rule is the gate's own
    (``validate_candidate.validate_candidate``, step 3).
    """
    if index is None:
        index = board_index()
    fp, sig = ident["fingerprint"], ident["signature"]
    exact = next((b["name"] for b in index if fp in b["fingerprints"]), None)
    wl = next((b["name"] for b in index if sig in b["signatures"] and fp not in b["fingerprints"]), None)
    return {"exact": exact, "wl": wl}


def board_match(HX, HZ, *, index=None):
    """``lookup(identity(HX, HZ), index)``."""
    return lookup(identity(HX, HZ), index)


def prescreen(HX, HZ, *, index=None, board=True):
    """Every check above, in one verdict.

    Returns ``{"structure", "identity", "board", "gate_would_refuse",
    "reasons", "labels"}``. ``reasons`` lists what the gate would refuse the
    candidate for (a direct sum, an exact board duplicate); ``labels`` what
    it would admit the candidate with (a WL match). ``board=False`` skips
    the board, for a generator that only wants the structural check.
    """
    structure = block_structure(HX, HZ)
    ident = identity(HX, HZ)
    match = lookup(ident, index) if board else dict(NO_MATCH)
    reasons, labels = [], []
    if not structure["connected"]:
        reasons.append("not one code: " + describe_structure(structure))
    if match["exact"]:
        reasons.append(f"duplicate: identical to board entry {match['exact']}")
    if match["wl"]:
        labels.append(f"possibly equivalent (same WL signature) to {match['wl']}")
    return {
        "structure": structure,
        "identity": ident,
        "board": match,
        "gate_would_refuse": bool(reasons),
        "reasons": reasons,
        "labels": labels,
    }


# -- the verifier's structural half on a packaged document (issue #3616) ----

# Which failed checks say the code is inadmissible, as opposed to the
# document being wrong. ``construction`` and ``weight`` are properties of
# (HX, HZ) that no edit to the document changes; everything else is a
# document the code may still be fine under: a malformed field, a wrong
# ``code_type``, a witness that does not verify, a layout that does not
# cover the qubits, a benchmark or architecture block that contradicts the
# entry.
KINDS = {
    "construction": (
        "tanner_connected",
        "stabilizer_group_connected",
        "css_commutation",
        "stabilizer_commutation",
        "k_at_least_1",
    ),
    "weight": ("check_weight_is_ldpc",),
    "typing": ("stabilizer_code_is_not_css", "stabilizer_code_is_not_locally_css"),
    "layout": (
        "coordinates_cover_all_qubits",
        "coordinates_uniform_dimension",
        "interaction_radius_within_claim",
        "site_occupancy_within_layers",
        "site_spacing_at_least_one",
        "modules_cover_all_qubits",
    ),
    "benchmark": (
        "benchmark_candidate_data_qubits",
        "benchmark_qubit_totals",
        "benchmark_baseline_on_board",
        "benchmark_baseline_k",
        "benchmark_baseline_data_qubits",
    ),
    "architecture": (
        "architecture_gadget_fault_distance",
        "architecture_gadget_data_qubits",
        "architecture_qubit_totals",
        "architecture_partner_on_board",
        "architecture_magic_state_gain",
        "architecture_blocks_cover_logical_qubits",
        "architecture_physical_qubits_cover_blocks",
        "architecture_factory_footprint",
    ),
    "other": ("verifier_ran",),
}
CODE_KINDS = frozenset({"construction", "weight"})


def kind_of(check, detail=""):
    """Classify a failed verifier check: what kind of thing is wrong.

    ``schema_valid`` needs its detail: the schema caps a check row at 32
    qubits, so a check over the weight cap is refused there, before the
    verifier's own ``check_weight_is_ldpc`` is reached, as a ``checks/...``
    row that "is too long". That is the code's weight, not the document's
    shape, and 7 of the 41 refusals in #3616 were this.
    """
    for kind, names in KINDS.items():
        if check in names:
            return kind
    if check == "schema_valid" and any(
        part.startswith("checks/") and "is too long" in part for part in detail.split("; ")
    ):
        return "weight"
    if check.startswith(("distance_", "d_matches_")):
        return "witness"
    return "packaging"


# Mirror verify/test_family_tag_consistency.py so the staging-time check agrees
# with CI byte for byte. A family named in the construction's opening (90 chars)
# must agree with the self-declared tag, unless the tag is at least as specific
# (MORE_SPECIFIC) or the family is the operand of a "quotient of".
_NOT_BASE = r"(?![- ]base\b)"
_FAMILY_RULES = [
    ("pair-partition-cpm", re.compile(r"pair[- ]partition|2607\.14091|2609\.30069", re.I)),
    ("bivariate-bicycle", re.compile(r"\bbivariate[- ]bicycle\b" + _NOT_BASE, re.I)),
    ("generalized-bicycle", re.compile(r"\bgenerali[sz]ed[- ]bicycle\b" + _NOT_BASE, re.I)),
]
_FAMILY_MORE_SPECIFIC = {
    "pair-partition-cpm": {"lifted-product", "hypergraph-product", "other"},
    "tile": {"bivariate-bicycle", "generalized-bicycle", "topological", "other"},
    "2bga-coset": {"generalized-bicycle", "other"},
    "check-deletion": {
        "bivariate-bicycle",
        "generalized-bicycle",
        "pair-partition-cpm",
        "lifted-product",
        "hypergraph-product",
        "tile",
        "other",
    },
}


def _family_excused(tag, family):
    return tag == family or family in _FAMILY_MORE_SPECIFIC.get(tag, ())


def _family_contradictions(doc):
    import re

    con = str((doc.get("provenance") or {}).get("construction") or "")
    tag = doc.get("family")
    if not con or not tag:
        return []
    out = []
    opening = con[:90]
    for family, pat in _FAMILY_RULES:
        if _family_excused(tag, family):
            continue
        m = pat.search(opening)
        if not m:
            continue
        if re.search(r"\bquotient of\b", opening[: m.start()], re.I):
            continue
        out.append(
            {
                "check": "family_tag_consistency",
                "detail": (f"construction names {family!r} (matched {m.group(0)!r}) but family={tag!r}"),
                "kind": "packaging",
            }
        )
    return out


def preflight(doc, report=None):
    """Run the verifier's structural half on a packaged document.

    ``qldpc_verify.verify(doc, refute=False)``, read for its failed checks.
    Returns ``{"ok", "failed", "kinds", "code_at_fault", "computed"}``:
    ``failed`` is one ``{"check", "detail", "kind"}`` per failed check, in
    the verifier's order and in the verifier's words; ``kinds`` the distinct
    kinds among them (``kind_of``); ``code_at_fault`` True when any failure
    is about the code rather than the document; ``computed`` what the
    verifier derived (``code_type``, ``n``, ``k``, ``max_check_weight``,
    ``weight_class``), as far as it got.

    The failed checks are exactly ``gates.verify.failed_checks`` of the
    gate's verdict for this document: ``validate_candidate`` calls the same
    function and excludes the same one check, ``distance_not_refuted``,
    which ``refute=False`` never records. A document that fails here fails
    the gate's verify step, and one that passes here can still be refuted
    there, so this decides nothing the gate would not. ``report`` is a
    ``qldpc_verify.verify(doc, refute=False)`` result already in hand.
    """
    rep = qldpc_verify.verify(doc, refute=False) if report is None else report
    failed = [
        {"check": c["check"], "detail": c.get("detail", ""), "kind": kind_of(c["check"], c.get("detail", ""))}
        for c in rep["checks"]
        if not c["ok"] and c["check"] != "distance_not_refuted"
    ]
    failed = failed + _family_contradictions(doc)
    kinds = sorted({f["kind"] for f in failed})
    comp = rep.get("computed") or {}
    keep = ("code_type", "n", "k", "max_check_weight", "weight_class")
    return {
        "ok": not failed,
        "failed": failed,
        "kinds": kinds,
        "code_at_fault": any(k in CODE_KINDS for k in kinds),
        "computed": {k: comp[k] for k in keep if k in comp},
    }


def describe_preflight(result):
    """One line per failed check, then what kind of fix there is."""
    if result["ok"]:
        return "the verifier's structural checks all pass"
    lines = [f"{f['check']} ({f['kind']}): {f['detail']}" for f in result["failed"]]
    lines.append(
        "the code is inadmissible; no edit to the document fixes it"
        if result["code_at_fault"]
        else "the document is wrong and the code may be fine; fix the document and save it again"
    )
    return "\n".join(lines)


def family_tag(doc):
    """Return ``{"declared", "ok", "contradictions"}``: the self-declared family against the construction text.

    The rule is ``verify/test_family_tag_consistency.py``'s, mirrored in
    `_family_contradictions`; a contradiction fails CI on the submission.
    """
    contradictions = _family_contradictions(doc)
    return {"declared": doc.get("family"), "ok": not contradictions, "contradictions": contradictions}


def _board_rows():
    """Return the board rows the gate's novelty block reads (memoized by the verifier)."""
    out = []
    for b in validate_candidate._board_entries():
        row = dict(b)
        name = str(b.get("name") or "")
        row["slug"] = name[:-5] if name.endswith(".json") else name
        out.append(row)
    return out


def candidate_row(doc, report):
    """Return the candidate as a frontier row: what the verifier computed, and the document's claimed d."""
    comp = report.get("computed") or {}
    distance = doc.get("distance") or {}
    d = distance.get("d")
    if d is None and isinstance(distance.get("X"), dict):
        d = distance["X"].get("value")
    return {
        "n": comp.get("n", doc.get("n")),
        "k": comp.get("k", doc.get("k")),
        "d": d,
        "w": comp.get("max_check_weight"),
        "code_type": comp.get("code_type", doc.get("code_type", "CSS")),
        "weight_class": comp.get("weight_class"),
        "locality_class": comp.get("locality_class"),
    }


def novelty_of(doc, *, report=None, rows=None):
    """Return the gate's novelty block for a packaged document, or None when it claims no distance.

    `frontier.novelty` over the board rows the gate reads, with the
    candidate's cell as the verifier computed it (the weight class from the
    checks, the locality class from the layout and its measured radius), so
    the answer is the gate's own, only earlier. ``dominators`` repeats
    ``dominated_by`` under the name issue #7442 asks for.
    """
    report = qldpc_verify.verify(doc, refute=False) if report is None else report
    cand = candidate_row(doc, report)
    if cand["d"] is None or cand["w"] is None or cand["n"] is None or cand["k"] is None:
        return None
    out = frontier.novelty(cand, _board_rows() if rows is None else rows)
    out["dominators"] = list(out["dominated_by"])
    return out


def collisions_of(doc, *, report=None, rows=None, codes_dir=None):
    """Return what already sits at this candidate's slug or parameters.

    ``slug`` is ``n-k-d``; ``slug_taken_by`` the board file of that name when
    it exists (a distinct code then needs ``suggested_slug``, the first free
    suffix, issue #5732); ``same_parameters`` the entries at this (n, k, d);
    ``ties`` those at this (n, k, d, w) in the candidate's cell, which share
    the frontier rather than block it but are a second PR for one point.
    ``exact`` and ``wl`` are the dedup matches `lookup` finds, repeated here
    so one block answers "is this name or this code already taken".
    """
    report = qldpc_verify.verify(doc, refute=False) if report is None else report
    cand = candidate_row(doc, report)
    rows = _board_rows() if rows is None else rows
    codes_dir = codes_dir or validate_candidate._CODES
    slug = f"{cand['n']}-{cand['k']}-{cand['d']}" if cand["d"] is not None else None
    taken_by = None
    suggested = None
    if slug and os.path.exists(os.path.join(codes_dir, f"{slug}.json")):
        taken_by = f"{slug}.json"
        suggested = next(
            (
                f"{slug}-{x}"
                for x in "bcdefghijklmnopqrstuvwxyz"
                if not os.path.exists(os.path.join(codes_dir, f"{slug}-{x}.json"))
            ),
            None,
        )
    same = [frontier.describe(b) for b in rows if (b["n"], b["k"], b["d"]) == (cand["n"], cand["k"], cand["d"])]
    ties = [
        frontier.describe(b)
        for b in rows
        if cand["w"] is not None
        and frontier.in_cell(cand, b)
        and (b["n"], b["k"], b["d"], b.get("w")) == (cand["n"], cand["k"], cand["d"], cand["w"])
    ]
    return {"slug": slug, "slug_taken_by": taken_by, "suggested_slug": suggested, "same_parameters": same, "ties": ties}


SCHEMA_VERSION = 1


def verdict(doc, *, board=True, index=None, rows=None, codes_dir=None):
    """Return everything a generator can learn about a packaged candidate before the gate (issue #7442).

    One record, ``schema_version`` 1; the keys are the contract and additions
    never remove one:

    * ``candidate``: n, k, d (the claimed distance, or null), w, code_type,
      weight_class, locality_class, as the verifier computed them.
    * ``preflight``: `preflight`'s record, the structural half of the gate's
      verify step (family-tag contradictions are among its ``failed``).
    * ``family_tag``: `family_tag`'s record, the same contradictions on their own.
    * ``structure``, ``identity``, ``board``, ``reasons``, ``labels``:
      `prescreen`'s verdict for a CSS candidate (a direct sum, an exact board
      duplicate, a WL match); null for a stabilizer one, whose dedup the gate does.
    * ``novelty``: `novelty_of`, the gate's block with ``board_advancing``,
      ``advances_by``, ``dominators``, ``d_only_gain``, ``d_only_peers``,
      ``beaten``; null when no distance is claimed.
    * ``collisions``: `collisions_of`, plus the ``exact`` and ``wl`` dedup names.
    * ``gate_would_refuse``: a preflight failure, a direct sum, or an exact
      duplicate. ``frontier_submittable``: not refused, and board-advancing.

    ``board=False`` skips every board read (structure and preflight only).
    ``index`` and ``rows`` inject the dedup index and the frontier rows, for
    tests and for a generator that holds its own snapshot.
    """
    report = qldpc_verify.verify(doc, refute=False)
    pre = preflight(doc, report)
    cand = candidate_row(doc, report)
    stabilizer = qldpc_verify.is_stabilizer(doc)
    out = {
        "schema_version": SCHEMA_VERSION,
        "candidate": cand,
        "preflight": pre,
        "family_tag": family_tag(doc),
        "structure": None,
        "identity": None,
        "board": dict(NO_MATCH),
        "reasons": [],
        "labels": [],
        "novelty": None,
        "collisions": None,
        "gate_would_refuse": not pre["ok"],
        "frontier_submittable": False,
    }
    if not stabilizer and "X" in (doc.get("checks") or {}):
        n = int(doc["n"])
        HX = qldpc_verify._matrix(doc["checks"]["X"], n)
        HZ = qldpc_verify._matrix(doc["checks"]["Z"], n)
        pre_v = prescreen(HX, HZ, index=index, board=board)
        for key in ("structure", "identity", "board", "reasons", "labels"):
            out[key] = pre_v[key]
        out["gate_would_refuse"] = out["gate_would_refuse"] or pre_v["gate_would_refuse"]
    if board:
        out["novelty"] = novelty_of(doc, report=report, rows=rows)
        out["collisions"] = dict(collisions_of(doc, report=report, rows=rows, codes_dir=codes_dir), **out["board"])
    out["frontier_submittable"] = bool(
        not out["gate_would_refuse"] and out["novelty"] and out["novelty"]["board_advancing"]
    )
    return out


def load_matrices(path):
    """Load (HX, HZ) from a staged candidate file.

    A ``.json`` candidate carries a checks block; an ``.npz`` carries the
    matrices under ``hx``/``HX``/``H_X`` and ``hz``/``HZ``/``H_Z``. These are
    the two forms ``qldpc submit`` accepts.
    """
    if path.endswith(".npz"):
        z = np.load(path, allow_pickle=False)

        def pick(keys):
            for key in keys:
                if key in z.files:
                    return z[key]
            raise KeyError(f"{path}: no array under any of {keys}")

        return pick(("hx", "HX", "H_X", "Hx")), pick(("hz", "HZ", "H_Z", "Hz"))
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if qldpc_verify.is_stabilizer(doc):
        raise ValueError(
            f"{path}: a stabilizer candidate; this pre-check reads CSS candidates only, the gate handles the rest"
        )
    n = int(doc["n"])
    return (qldpc_verify._matrix(doc["checks"]["X"], n), qldpc_verify._matrix(doc["checks"]["Z"], n))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Decide, before the gate, whether a candidate is one "
        "connected code, whether the board already holds it, "
        "and (for a .json document) whether the gate's verify "
        "step would refuse it."
    )
    ap.add_argument("path", nargs="?", help="candidate .json or .npz; with none, run the demo")
    ap.add_argument("--no-board", action="store_true", help="structural check only, no board scan")
    ap.add_argument("--json", action="store_true", help="print the verdict as JSON")
    args = ap.parse_args(argv)
    if args.path is None:
        return _demo()
    pre = None
    if args.path.endswith(".json"):
        with open(args.path, encoding="utf-8") as f:
            doc = json.load(f)
        full = verdict(doc, board=not args.no_board)
        pre = full["preflight"]
        if qldpc_verify.is_stabilizer(doc):
            # the structure and board checks here read CSS matrices; the
            # gate's own dedup covers a stabilizer candidate
            if args.json:
                print(json.dumps(full, indent=1))
            else:
                print(f"{args.path}: a stabilizer candidate; preflight only")
                for line in describe_preflight(pre).split("\n"):
                    print(f"  {'REFUSE  ' if not pre['ok'] else ''}{line}")
                _print_novelty(full)
            return 0 if pre["ok"] else 1
        if args.json:
            print(json.dumps(full, indent=1))
            return 1 if full["gate_would_refuse"] else 0
        HX, HZ = load_matrices(args.path)
        result = full
    else:
        HX, HZ = load_matrices(args.path)
        result = prescreen(HX, HZ, board=not args.no_board)
        full = None
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        n = int(np.asarray(HX).shape[1])
        print(f"{args.path}: n={n}, {describe_structure(result['structure'])}")
        if pre is not None and not pre["ok"]:
            for line in describe_preflight(pre).split("\n"):
                print(f"  REFUSE  {line}")
        match = result["board"]
        if not args.no_board:
            if match["exact"]:
                print(f"  board: identical to {match['exact']}")
            elif match["wl"]:
                print(
                    f"  board: same WL signature as {match['wl']} (a probable "
                    "permutation; the gate admits it with a label you must "
                    "resolve in provenance.notes)"
                )
            else:
                print("  board: no entry shares this fingerprint or WL signature")
        for reason in result["reasons"]:
            print(f"  REFUSE  {reason}")
        if full is not None:
            _print_novelty(full)
        print(
            "  the gate would refuse this candidate"
            if result["gate_would_refuse"]
            else "  worth gating; the distance is the gate's to decide"
        )
    return 1 if result["gate_would_refuse"] else 0


def _print_novelty(full):
    """Print the novelty and collision lines of the human report."""
    nov = full.get("novelty")
    if nov is None:
        print("  novelty: not assessed (no distance claimed in the document)")
    else:
        verb = "advances" if nov["board_advancing"] else "does not advance"
        axes = f" on {', '.join(nov['advances_by'])}" if nov["advances_by"] else ""
        print(f"  novelty: {verb} the {nov['cell'][0]} x {nov['cell'][1]} {nov['board']} board{axes}")
        for desc in nov["dominators"][:5]:
            print(f"      dominated by {desc}")
        if nov["d_only_peers"]:
            print(f"      d-only over {len(nov['d_only_peers'])} peer(s): a matched-depth peer audit is owed")
    col = full.get("collisions") or {}
    if col.get("slug_taken_by"):
        print(
            f"  slug {col['slug']} is taken by {col['slug_taken_by']}; "
            f"a distinct code needs --slug {col['suggested_slug']}"
        )
    if col.get("ties"):
        print(f"  ties at this (n, k, d, w): {', '.join(col['ties'][:5])}")
    tag = full.get("family_tag") or {}
    for c in tag.get("contradictions") or []:
        print(f"  REFUSE  family tag: {c['detail']}")


def _demo():
    """Steane's [[7,1,3]] is on the board; two copies of it are a direct sum."""
    H = np.array([[1, 0, 1, 0, 1, 0, 1], [0, 1, 1, 0, 0, 1, 1], [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    H2 = direct_sum(H, H)
    for label, HX, HZ in (("Steane [[7,1,3]]", H, H), ("Steane plus Steane", H2, H2)):
        v = prescreen(HX, HZ)
        print(
            f"{label}: {describe_structure(v['structure'])}; board exact="
            f"{v['board']['exact']} wl={v['board']['wl']}; "
            + ("the gate would refuse" if v["gate_would_refuse"] else "worth gating")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
