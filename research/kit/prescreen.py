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
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "..", "verify"))
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
    components = qldpc_verify._tanner_component_count(
        {"X": _supports(HX), "Z": _supports(HZ)}, n)
    blocks, sizes = qldpc_verify._stabilizer_block_count(HX, HZ, n)
    return {"tanner_components": int(components), "blocks": int(blocks),
            "block_sizes": [int(s) for s in sizes],
            "connected": components == 1 and blocks == 1}


def describe_structure(structure):
    """One line in the gate's own words, or "one connected code"."""
    if structure["connected"]:
        return "one connected code"
    parts = []
    if structure["tanner_components"] != 1:
        parts.append(f"Tanner graph has {structure['tanner_components']} "
                     "connected component(s)")
    if structure["blocks"] != 1:
        sizes = ", ".join(map(str, structure["block_sizes"][:6]))
        if structure["blocks"] > 6:
            sizes += ", ..."
        parts.append(f"stabilizer group splits into {structure['blocks']} "
                     f"independent block(s) on disjoint qubit sets "
                     f"(sizes {sizes})")
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
    doc = {"code_type": "CSS", "n": n, "k": 0, "distance": {"d": 0},
           "checks": {"X": _supports(HX), "Z": _supports(HZ)}}
    return {"fingerprint": qldpc_verify.css_fingerprint(HX, HZ),
            "signature": qldpc_verify.signature(doc)["hash"]}


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
            out.append({"name": b["name"], "n": b["n"], "k": b["k"],
                        "d": b["d"], "fingerprints": fps - {None},
                        "signatures": sigs - {None}})
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
    wl = next((b["name"] for b in index
               if sig in b["signatures"] and fp not in b["fingerprints"]),
              None)
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
    return {"structure": structure, "identity": ident, "board": match,
            "gate_would_refuse": bool(reasons), "reasons": reasons,
            "labels": labels}


# -- the verifier's structural half on a packaged document (issue #3616) ----

# Which failed checks say the code is inadmissible, as opposed to the
# document being wrong. ``construction`` and ``weight`` are properties of
# (HX, HZ) that no edit to the document changes; everything else is a
# document the code may still be fine under: a malformed field, a wrong
# ``code_type``, a witness that does not verify, a layout that does not
# cover the qubits.
KINDS = {
    "construction": ("tanner_connected", "stabilizer_group_connected",
                     "css_commutation", "stabilizer_commutation",
                     "k_at_least_1"),
    "weight": ("check_weight_is_ldpc",),
    "typing": ("stabilizer_code_is_not_css",
               "stabilizer_code_is_not_locally_css"),
    "layout": ("coordinates_cover_all_qubits", "coordinates_uniform_dimension",
               "interaction_radius_within_claim", "site_occupancy_within_layers",
               "site_spacing_at_least_one", "modules_cover_all_qubits"),
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
            part.startswith("checks/") and "is too long" in part
            for part in detail.split("; ")):
        return "weight"
    if check.startswith(("distance_", "d_matches_")):
        return "witness"
    return "packaging"


def preflight(doc):
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
    there, so this decides nothing the gate would not.
    """
    rep = qldpc_verify.verify(doc, refute=False)
    failed = [{"check": c["check"], "detail": c.get("detail", ""),
               "kind": kind_of(c["check"], c.get("detail", ""))}
              for c in rep["checks"]
              if not c["ok"] and c["check"] != "distance_not_refuted"]
    kinds = sorted({f["kind"] for f in failed})
    comp = rep.get("computed") or {}
    keep = ("code_type", "n", "k", "max_check_weight", "weight_class")
    return {"ok": not failed, "failed": failed, "kinds": kinds,
            "code_at_fault": any(k in CODE_KINDS for k in kinds),
            "computed": {k: comp[k] for k in keep if k in comp}}


def describe_preflight(result):
    """One line per failed check, then what kind of fix there is."""
    if result["ok"]:
        return "the verifier's structural checks all pass"
    lines = [f"{f['check']} ({f['kind']}): {f['detail']}"
             for f in result["failed"]]
    lines.append("the code is inadmissible; no edit to the document fixes it"
                 if result["code_at_fault"] else
                 "the document is wrong and the code may be fine; fix the "
                 "document and save it again")
    return "\n".join(lines)


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
        raise ValueError(f"{path}: a stabilizer candidate; this pre-check "
                         "reads CSS candidates only, the gate handles the rest")
    n = int(doc["n"])
    return (qldpc_verify._matrix(doc["checks"]["X"], n),
            qldpc_verify._matrix(doc["checks"]["Z"], n))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Decide, before the gate, whether a candidate is one "
                    "connected code, whether the board already holds it, "
                    "and (for a .json document) whether the gate's verify "
                    "step would refuse it.")
    ap.add_argument("path", nargs="?",
                    help="candidate .json or .npz; with none, run the demo")
    ap.add_argument("--no-board", action="store_true",
                    help="structural check only, no board scan")
    ap.add_argument("--json", action="store_true",
                    help="print the verdict as JSON")
    args = ap.parse_args(argv)
    if args.path is None:
        return _demo()
    pre = None
    if args.path.endswith(".json"):
        with open(args.path, encoding="utf-8") as f:
            doc = json.load(f)
        pre = preflight(doc)
        if qldpc_verify.is_stabilizer(doc):
            # the structure and board checks here read CSS matrices; the
            # gate's own dedup covers a stabilizer candidate
            if args.json:
                print(json.dumps({"preflight": pre,
                                  "gate_would_refuse": not pre["ok"]}, indent=1))
            else:
                print(f"{args.path}: a stabilizer candidate; preflight only")
                for line in describe_preflight(pre).split("\n"):
                    print(f"  {'REFUSE  ' if not pre['ok'] else ''}{line}")
            return 0 if pre["ok"] else 1
    HX, HZ = load_matrices(args.path)
    verdict = prescreen(HX, HZ, board=not args.no_board)
    if pre is not None:
        verdict["preflight"] = pre
        verdict["gate_would_refuse"] = verdict["gate_would_refuse"] or not pre["ok"]
    if args.json:
        print(json.dumps(verdict, indent=1))
    else:
        n = int(np.asarray(HX).shape[1])
        print(f"{args.path}: n={n}, {describe_structure(verdict['structure'])}")
        if pre is not None and not pre["ok"]:
            for line in describe_preflight(pre).split("\n"):
                print(f"  REFUSE  {line}")
        match = verdict["board"]
        if not args.no_board:
            if match["exact"]:
                print(f"  board: identical to {match['exact']}")
            elif match["wl"]:
                print(f"  board: same WL signature as {match['wl']} (a probable "
                      "permutation; the gate admits it with a label you must "
                      "resolve in provenance.notes)")
            else:
                print("  board: no entry shares this fingerprint or WL signature")
        for reason in verdict["reasons"]:
            print(f"  REFUSE  {reason}")
        print("  the gate would refuse this candidate"
              if verdict["gate_would_refuse"] else
              "  worth gating; the distance is the gate's to decide")
    return 1 if verdict["gate_would_refuse"] else 0


def _demo():
    """Steane's [[7,1,3]] is on the board; two copies of it are a direct sum."""
    H = np.array([[1, 0, 1, 0, 1, 0, 1],
                  [0, 1, 1, 0, 0, 1, 1],
                  [0, 0, 0, 1, 1, 1, 1]], dtype=np.int8)
    H2 = direct_sum(H, H)
    for label, HX, HZ in (("Steane [[7,1,3]]", H, H),
                          ("Steane plus Steane", H2, H2)):
        v = prescreen(HX, HZ)
        print(f"{label}: {describe_structure(v['structure'])}; board exact="
              f"{v['board']['exact']} wl={v['board']['wl']}; "
              + ("the gate would refuse" if v["gate_would_refuse"]
                 else "worth gating"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
