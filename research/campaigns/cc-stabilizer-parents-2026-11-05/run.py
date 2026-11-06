#!/usr/bin/env python3
"""Single-step symplectic moves on the board's stabilizer entries (issue #4478, direction 1).

Direction 1 of issue #4478 proposes stabilizer codes as parents for code-calculus
moves, converted to CSS by a local Clifford. On this board that premise fails:
none of the 226 stabilizer entries is CSS up to a local Clifford, because the
verifier refuses such a submission as a CSS code in disguise, so v0.1's CSS
state model cannot load any of them. This campaign runs the symplectic analogs
of the library's three productive moves on the parents with n <= N instead:
delete an independent generator (C-DELETE-CHECK), puncture a qubit by removing
it and every generator touching it (E-PUNCTURE), and peel a qubit with one of
the generators touching it, the others losing the qubit, kept only when the
result is still isotropic (E-PEEL). Children are deduplicated by the canonical
form of the symplectic matrix, refused on the gate's structural grounds (a
dependent display, a bare qubit, a disconnected group, k = 0), pruned when the
optimistic point (n', k', d_parent, w') is dominated on the stabilizer board,
screened with the kit's Pauli-weight RIS, and the nondominated survivors with
screened d >= 3 go through the trusted gate and are staged under the run's
staging directory. Children at d <= 2 are counted and not gated: on a board of
226 stabilizer entries they are nondominated on paper and worthless. One ledger
experiment per (parent, move) records the depth and the verdict.

    QLDPC_RUN_ID=<run> uv run --extra research python research/campaigns/cc-stabilizer-parents-2026-11-05/run.py \
        [--n-cap 40] [--gate-cap 200] [--out <dir>]

summary.json, manifest.json, and report.json beside this file are the run of
2026-11-05; the reading is fieldnotes/2026-11-05-code-calculus-v0p1-directions-1-and-6.md.
"""

import argparse
import collections
import datetime
import json
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in ("verify", os.path.join("research", "kit")):
    _full = os.path.join(ROOT, _p)
    if _full not in sys.path:
        sys.path.insert(0, _full)
os.environ.setdefault("QLDPC_RUN_ID", "cc-stabilizer-parents")
import coordination  # noqa: E402
import gf2  # noqa: E402
import heuristic_distance as hd  # noqa: E402
import qldpc_verify as V  # noqa: E402
import validate_candidate as VC  # noqa: E402
from campaign import Campaign, Ledger, scaffold_campaign, write_campaign, write_manifest, write_summary  # noqa: E402

TRIALS = 1000
MIN_GATE_D = 3  # d <= 2 children are nondominated on a sparse board and worthless; count, do not gate
CAMPAIGN_ID = "cc-stabilizer-parents-2026-11-05"
TODAY = datetime.date.today().isoformat()
W_ORDER, L_ORDER = VC._WEIGHT_ORDER, VC._LOCAL_ORDER


def weight_class(w):
    return "weight-4" if w <= 4 else "weight-6" if w <= 6 else "weight-8" if w <= 8 else "weight-9plus"


def canon(A, B):
    S = np.concatenate([A, B], axis=1).astype(np.int8)
    R, _ = gf2.rref(S)
    R = np.asarray(R)
    R = R[np.any(R, axis=1)]
    return R.tobytes() + bytes([S.shape[1] % 251])


def isotropic(A, B):
    return not bool(((A @ B.T + B @ A.T) % 2).any())


def child_ok(A, B):
    """(ok, why, k) for a symplectic display: independent, isotropic, no bare qubit, connected, k >= 1."""
    n = A.shape[1]
    if A.shape[0] == 0:
        return False, "no rows", None
    if not isotropic(A, B):
        return False, "not isotropic", None
    S = np.concatenate([A, B], axis=1)
    r = gf2.rank(S)
    if r < S.shape[0]:
        return False, "dependent display", None
    k = n - r
    if k < 1:
        return False, "k = 0", None
    if not np.all((A | B).any(axis=0)):
        return False, "bare qubit", None
    blocks, _ = V._symplectic_block_count(S, n)
    if blocks != 1:
        return False, "disconnected", None
    return True, "", int(k)


def drop_qubit(A, B, q):
    keep = [j for j in range(A.shape[1]) if j != q]
    return A[:, keep], B[:, keep]


def moves(A, B):
    """Yield (move, A', B', detail) for every single-step symplectic child."""
    m, n = A.shape
    touch = (A | B).astype(bool)
    for i in range(m):
        yield ("C-DELETE-CHECK", np.delete(A, i, 0), np.delete(B, i, 0), f"delete generator {i}")
    for q in range(n):
        keep = [i for i in range(m) if not touch[i, q]]
        A2, B2 = drop_qubit(A[keep], B[keep], q)
        yield ("E-PUNCTURE", A2, B2, f"puncture qubit {q} (remove it and every generator touching it)")
    for q in range(n):
        for i in range(m):
            if not touch[i, q]:
                continue
            keep = [j for j in range(m) if j != i]
            A2, B2 = drop_qubit(A[keep], B[keep], q)
            yield ("E-PEEL", A2, B2, f"peel qubit {q} with generator {i} (the other generators lose the qubit)")


def dominated(point, cell, board):
    n, k, d, w = point
    wc, lc = cell
    for b in board:
        if b["code_type"] != "stabilizer" or b.get("w") is None:
            continue
        if W_ORDER.get(b["weight_class"], 9) > W_ORDER.get(wc, 9) or L_ORDER.get(b["locality_class"], 9) > L_ORDER.get(
            lc, 9
        ):
            continue
        if (
            b["n"] <= n
            and b["k"] >= k
            and b["d"] >= d
            and b["w"] <= w
            and (b["n"] < n or b["k"] > k or b["d"] > d or b["w"] < w)
        ):
            return True
    return False


def gens(A, B):
    return [
        {"X": [int(j) for j in np.nonzero(A[i])[0]], "Z": [int(j) for j in np.nonzero(B[i])[0]]}
        for i in range(A.shape[0])
    ]


def make_doc(A, B, k, d, wit, parent_slug, parent_doc, move, detail, dropped_q):
    n = A.shape[1]
    doc = {
        "schema_version": "0.4",
        "name": f"[[{n},{k},{d}]] {move} of {parent_slug}",
        "code_type": "stabilizer",
        "n": n,
        "k": k,
        "checks": {"S": gens(A, B)},
        "distance": {
            "d": int(d),
            "P": {"value": int(d), "confidence": "upper_bound", "witness": hd.pauli_witness(wit, n)},
        },
        "provenance": {
            "authors": ["@vprusso"],
            "origin": "submission",
            "date": TODAY,
            "construction": (
                f"Symplectic single-step move on the stabilizer board entry "
                f"codes/{parent_slug}.json ([[{parent_doc['n']},{parent_doc['k']},"
                f"{parent_doc['distance']['d']}]]): {move}, {detail}; qubits relabeled "
                f"in increasing order of the parent's surviving indices. The move is the "
                f"symplectic analog of code-calculus v0.1's {move} (issue #4478, direction 1: "
                f"stabilizer parents); the library's CSS state model does not cover this parent. "
                f"Parent construction: {parent_doc['provenance'].get('construction', '')[:400]}"
            ),
            "notes": f"Pauli-weight witness from a {TRIALS}-trial RIS screen; distance is an upper bound.",
        },
        "family": "other",
    }
    loc = parent_doc.get("locality")
    if loc and loc.get("coordinates") and len(loc["coordinates"]) == parent_doc["n"]:
        coords = (
            [c for j, c in enumerate(loc["coordinates"]) if j != dropped_q]
            if dropped_q is not None
            else list(loc["coordinates"])
        )
        doc["locality"] = {"coordinates": coords, "layers": int(loc.get("layers", 1))}
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n-cap", type=int, default=40, help="largest parent blocklength (default 40)")
    ap.add_argument("--gate-cap", type=int, default=200, help="most children put through the gate (default 200)")
    ap.add_argument("--out", default=_HERE, help="where campaign.json, summary.json, manifest.json, report.json go")
    args = ap.parse_args(argv)
    N_CAP, GATE_CAP, OUTDIR = args.n_cap, args.gate_cap, args.out
    t0 = time.time()
    os.makedirs(OUTDIR, exist_ok=True)
    board = VC._board_entries()
    stab_board = [b for b in board if b["code_type"] == "stabilizer"]
    reports = {e["slug"]: e for e in V.board_reports(os.path.join(ROOT, "codes"))}
    parents = [
        (slug, e["doc"], e["report"])
        for slug, e in reports.items()
        if e["doc"]
        and e["report"]
        and e["report"].get("ok")
        and e["doc"].get("code_type") == "stabilizer"
        and e["doc"]["n"] <= N_CAP
    ]
    parents.sort(key=lambda t: (t[1]["n"], t[0]))
    bar = max(stab_board, key=lambda b: b["k"] * b["d"] ** 2 / b["n"] if b["n"] <= N_CAP else -1)
    print(
        f"{len(parents)} stabilizer parents with n <= {N_CAP}; stabilizer board rows {len(stab_board)}; "
        f"bar {bar['name']} kd2/n {bar['k'] * bar['d'] ** 2 / bar['n']:.3f}",
        flush=True,
    )
    card = {
        "hypothesis": (
            "Single-step symplectic moves (delete a generator, puncture a qubit, peel a qubit with one "
            "of its generators) on the board's stabilizer entries with n <= %d reach stabilizer-board "
            "frontier points that code-calculus v0.1's CSS-only moves cannot express." % N_CAP
        ),
        "cell": "unrestricted~weight-any",
        "family": "other",
        "bar": {
            "slug": bar["name"][:-5],
            "axes": ["k", "d"],
            "note": "the stabilizer entry with the best kd^2/n at n <= %d; the stabilizer board ranks apart "
            "from the CSS board"
            % N_CAP,
        },
        "budget": {"walltime_hours": 2, "candidates_screened": 20000, "trials_per_candidate": TRIALS},
        "feasibility": (
            "%d stabilizer parents at n <= %d; a Pauli-weight RIS screen at %d trials reads a child in "
            "well under a second at these sizes, the gate accepts stabilizer documents, and the board's "
            "stabilizer entries all carry layouts or none, so children inherit what their parent has."
            % (len(parents), N_CAP, TRIALS)
        ),
        "novelty": {
            "claim": "a stabilizer code one symplectic move from a board stabilizer entry, nondominated on the "
            "stabilizer board",
            "against": "the stabilizer board's 226 entries, mostly codetables.de additive codes read as "
            "symplectic rows",
        },
        "expected_value": (
            "A nondominated stabilizer child at d >= 3 would show that the calculus's moves transfer beyond "
            "CSS presentations and give the stabilizer board, which carries no certified distance, a "
            "frontier point with an auditable parent."
        ),
        "abandon_criterion": {
            "flat_fresh_rungs": 2,
            "trials_cap": TRIALS,
            "note": "one screen depth; a survivor is gated, not deepened, in this probe",
        },
        "what_a_negative_would_teach": (
            "That one deletion, puncture, or peel from a stabilizer entry with n <= %d lands only on "
            "dominated points or at d <= 2, so the stabilizer board's small-n frontier is not "
            "reachable by its own entries' single-step children and a symplectic extension of "
            "the calculus would need depth or a different move set to pay." % N_CAP
        ),
    }
    spec = scaffold_campaign(
        CAMPAIGN_ID,
        "code-calculus moves on stabilizer parents (issue #4478, direction 1)",
        card=card,
        budget={"walltime_hours": 2, "candidates_screened": 20000},
        families=["other"],
        constraints={"n": [1, N_CAP]},
        methods={"families": ["other"], "screening": {"trials_per_candidate": TRIALS}},
        notes=(
            "Symplectic analogs of C-DELETE-CHECK, E-PUNCTURE, and E-PEEL applied once to each "
            "stabilizer board entry; see the fieldnote of 2026-11-05."
        ),
    )
    write_campaign(spec, os.path.join(OUTDIR, "campaign.json"), overwrite=True)
    camp = Campaign(spec)
    staging = coordination.staging_dir()
    led = Ledger(camp, journal=os.path.join(staging, "ledger.jsonl"))
    led.record_negative(
        "stabilizer parents are outside code-calculus v0.1's state model",
        "0 of the board's 226 stabilizer entries are CSS up to a local Clifford (the verifier "
        "refuses such submissions as CSS codes in disguise), so the library's CodeState cannot "
        "load any of them; the moves here are symplectic analogs written for this probe",
    )
    totals = collections.Counter()
    refused = collections.Counter()
    gated = 0
    finds = []
    screened_rows = []
    low_d_rows = []
    by_move = collections.defaultdict(collections.Counter)
    for slug, doc, rep in parents:
        A, B = V.stabilizer_matrices(doc)
        A, B = A.astype(np.int8), B.astype(np.int8)
        n, k0, d0 = doc["n"], doc["k"], doc["distance"]["d"]
        laid = rep["computed"].get("locality_class", "unrestricted") != "unrestricted"
        strict_loc = "local-2d-single" if laid else "unrestricted"
        seen = set()
        per_move = collections.defaultdict(
            lambda: {
                "derived": 0,
                "dup": 0,
                "pruned": 0,
                "screened": 0,
                "best_d": None,
                "gated": 0,
                "passed": 0,
                "dominated": 0,
                "refuted": 0,
                "low_d": 0,
                "children": [],
            }
        )
        for move, A2, B2, detail in moves(A, B):
            totals[(move, "enumerated")] += 1
            ok, why, k2 = child_ok(A2, B2)
            if not ok:
                refused[(move, why)] += 1
                continue
            key = canon(A2, B2)
            if key in seen:
                per_move[move]["dup"] += 1
                continue
            seen.add(key)
            per_move[move]["derived"] += 1
            n2 = A2.shape[1]
            w2 = int((A2 | B2).sum(axis=1).max())
            cell = (weight_class(w2), strict_loc)
            if dominated((n2, k2, d0, w2), cell, stab_board):
                per_move[move]["pruned"] += 1
                continue
            dP, wit = hd.ris_min_pauli_logical(A2, B2, trials=TRIALS, seed=7)
            per_move[move]["screened"] += 1
            if dP is None:
                refused[(move, "no logical found")] += 1
                continue
            best = per_move[move]["best_d"]
            per_move[move]["best_d"] = dP if best is None else max(best, dP)
            screened_rows.append({"parent": slug, "move": move, "n": n2, "k": k2, "d": int(dP), "w": w2})
            if dominated((n2, k2, dP, w2), cell, stab_board):
                per_move[move]["dominated"] += 1
                continue
            if dP < MIN_GATE_D:
                per_move[move]["low_d"] += 1
                low_d_rows.append({"parent": slug, "move": move, "n": n2, "k": k2, "d": int(dP), "w": w2})
                continue
            dropped_q = None
            if move != "C-DELETE-CHECK":
                dropped_q = int(detail.split("qubit ")[1].split()[0])
            per_move[move]["children"].append((n2, k2, int(dP), w2, A2, B2, wit, detail, dropped_q))
        # gate the nondominated screened children, best efficiency first, under the cap
        for move, st in per_move.items():
            led.start_experiment(
                "other",
                seed=7,
                mode="novel_generation",
                params={"parent": slug, "move": move, "n": n, "k": k0, "d": d0},
                note=(
                    f"{st['derived']} distinct children ({st['dup']} duplicates folded), "
                    f"{st['pruned']} pruned as dominated at the parent's d, {st['screened']} "
                    f"screened at {TRIALS} Pauli RIS trials, {st['low_d']} nondominated at "
                    f"the screen but at d <= {MIN_GATE_D - 1} and not gated"
                ),
            )
            led.spend(candidates_screened=st["screened"])
            if st["screened"]:
                led.record_screen(trials=TRIALS, d=st["best_d"], backend="numpy")
            kids = sorted(st["children"], key=lambda c: -(c[1] * c[2] ** 2 / c[0]))
            verdict_name = "not_run" if not kids else None
            for n2, k2, dP, w2, A2, B2, wit, detail, dropped_q in kids:
                if gated >= GATE_CAP:
                    verdict_name = verdict_name or "held"
                    break
                cdoc = make_doc(A2, B2, k2, dP, wit, slug, doc, move, detail, dropped_q)
                path = coordination.unique_path(os.path.join(staging, f"{n2}-{k2}-{dP}.json"), cdoc)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(cdoc, f, indent=1)
                gated += 1
                st["gated"] += 1
                try:
                    verdict, _ = coordination.gate_and_record(path, seed=11)
                except coordination.PreflightFailure as e:
                    refused[(move, "preflight")] += 1
                    verdict_name = verdict_name or "refuted"
                    print(f"  preflight refused {os.path.basename(path)}: {str(e)[:120]}", flush=True)
                    continue
                labels = "; ".join(verdict.get("labels") or [])
                if verdict.get("passed"):
                    nov = (verdict.get("gates") or {}).get("novelty") or {}
                    st["passed"] += 1
                    led.record_candidate(cdoc, verdict)
                    verdict_name = "passed"
                    finds.append(
                        {
                            "file": os.path.relpath(path, ROOT),
                            "parent": slug,
                            "move": move,
                            "n": n2,
                            "k": k2,
                            "d": dP,
                            "w": w2,
                            "board_advancing": nov.get("board_advancing"),
                            "dominated_by": nov.get("dominated_by"),
                            "d_only_peers": nov.get("d_only_peers"),
                            "labels": verdict.get("labels"),
                        }
                    )
                    print(
                        f"  PASSED [[{n2},{k2},{dP}]] w={w2} {move} of {slug}: advancing={nov.get('board_advancing')} "
                        + ("dominated by " + ", ".join(nov.get("dominated_by") or [])
                           if nov.get("dominated_by") else ""),
                        flush=True,
                    )
                else:
                    if "refuted" in labels.lower():
                        st["refuted"] += 1
                        verdict_name = verdict_name or "refuted"
                    elif "duplicate" in labels.lower():
                        verdict_name = verdict_name or "duplicate"
                    else:
                        verdict_name = verdict_name or "refuted"
                    print(f"  gate refused [[{n2},{k2},{dP}]] {move} of {slug}: {labels[:160]}", flush=True)
            if verdict_name is None:
                verdict_name = "dominated" if st["dominated"] and not st["low_d"] else "not_run"
            led.record_verdict(verdict_name)
            led.end_experiment(empty_ok=not st["screened"] and not st["derived"])
        for move, st in per_move.items():
            for key in ("derived", "dup", "pruned", "screened", "low_d", "gated", "passed", "dominated", "refuted"):
                by_move[move][key] += st[key]
        print(
            f"{slug} [[{n},{k0},{d0}]]: "
            + ", ".join(
                f"{m}: {s['derived']} derived, {s['pruned']} pruned, {s['screened']} screened, "
                f"{s['low_d']} low-d, {s['gated']} gated, {s['passed']} passed"
                for m, s in per_move.items()
            )
            + f"  ({time.time() - t0:.0f}s)",
            flush=True,
        )
    for move in ("C-DELETE-CHECK", "E-PUNCTURE", "E-PEEL"):
        n_pass = sum(1 for f in finds if f["move"] == move)
        n_adv = sum(1 for f in finds if f["move"] == move and f["board_advancing"])
        n_low = sum(1 for r in low_d_rows if r["move"] == move)
        if not n_adv:
            led.record_negative(
                f"{move} on stabilizer parents with n <= {N_CAP}: no board-advancing child at d >= {MIN_GATE_D}",
                f"{totals[(move, 'enumerated')]} moves enumerated, {n_low} children nondominated at the "
                f"screen but at d <= {MIN_GATE_D - 1} (not gated, by design), {n_pass} children with "
                f"d >= {MIN_GATE_D} passed the gate, none of them nondominated on the stabilizer board",
            )
    summary = led.summary(status="completed")
    write_summary(summary, os.path.join(OUTDIR, "summary.json"))
    write_manifest(led.manifest(), os.path.join(OUTDIR, "manifest.json"))
    report = {
        "n_cap": N_CAP,
        "parents": len(parents),
        "seconds": round(time.time() - t0, 1),
        "enumerated": {f"{m}": c for (m, kind), c in totals.items() if kind == "enumerated"},
        "refused": {f"{m}: {why}": c for (m, why), c in refused.items()},
        "gated": gated,
        "gate_cap": GATE_CAP,
        "by_move": {m: dict(c) for m, c in by_move.items()},
        "min_gate_d": MIN_GATE_D,
        "finds": finds,
        "screened": screened_rows,
        "low_d_nondominated": low_d_rows,
        "staging": os.path.relpath(staging, ROOT),
    }
    with open(os.path.join(OUTDIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
        f.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("screened", "finds")}, indent=1))
    print(f"finds: {len(finds)}, board-advancing: {sum(1 for f in finds if f['board_advancing'])}")
    for f in finds:
        if f["board_advancing"]:
            print(f"  ADVANCING [[{f['n']},{f['k']},{f['d']}]] w={f['w']} {f['move']} of {f['parent']}  {f['file']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
