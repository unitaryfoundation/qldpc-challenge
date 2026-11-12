#!/usr/bin/env python3
"""E-GLUE pair gluing using code-calculus v0.2 glue transformer."""
import argparse, datetime, json, os, sys, itertools

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
for _p in ("verify", os.path.join("research", "kit")):
    if os.path.join(ROOT, _p) not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, _p))
CC = "/home/mathys/github/code-calculus-dev"
if CC not in sys.path:
    sys.path.insert(0, CC)
os.environ.setdefault("QLDPC_RUN_ID", "cc-glue-css")
import coordination
from machine.priced_calculus import CodeState, DistanceLedger, apply_operation, export_challenge_entry

TODAY = datetime.date.today().isoformat()
CERT = {"move_words": ["U", "U"], "evidence": "experiment: glue probe"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-cap", type=int, default=20)
    ap.add_argument("--pairs", type=int, default=20)
    args = ap.parse_args()
    staging = coordination.staging_dir()
    os.makedirs(staging, exist_ok=True)
    import glob
    docs = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        d = json.load(open(p))
        if d.get("code_type") == "CSS" and d["n"] <= args.n_cap:
            docs.append((os.path.splitext(os.path.basename(p))[0], d))
    print(f"{len(docs)} CSS parents with n <= {args.n_cap}", flush=True)
    # try gluing pairs with disjoint qubit namespaces via relabeling not possible; use small parents only
    tried = 0; gated = 0; finds = 0
    for (s1, d1), (s2, d2) in itertools.combinations(docs, 2):
        if tried >= args.pairs:
            break
        tried += 1
        st1 = CodeState.from_challenge(d1)
        st2 = CodeState.from_challenge(d2)
        # relabel second state qubits to avoid overlap: shift by n1
        # CodeState Q are tuples; rebuild? Simpler: skip if overlap
        if set(st1.Q) & set(st2.Q):
            # shift second state qubits by st1.n()
            shift = st1.n()
            newQ = tuple(q + shift for q in st2.Q)
            # rebuild rows
            from machine.priced_calculus import Row
            new_rows = []
            for r in st2.rows:
                new_rows.append(Row(r.id + "_2", r.sector, tuple(q + shift for q in r.support)))
            st2 = CodeState(newQ, tuple(new_rows), frozenset(r.id + "_2" for r in st2.rows))
        try:
            glued = st1.glue(st2, seam_certificate=CERT)
        except Exception as e:
            continue
        # export requires ledger witnesses; build a ledger from parent? Use a dummy interval ledger
        try:
            ld1 = DistanceLedger.from_challenge(st1, d1)
        except Exception:
            continue
        # We cannot easily build a glued ledger; skip export for now
        print(f"  glued {s1}+{s2}: n={glued.n()} k={glued.k()}", flush=True)
    print(f"tried={tried} gated={gated} finds={finds}", flush=True)


if __name__ == "__main__":
    main()
