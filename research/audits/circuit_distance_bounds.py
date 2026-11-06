#!/usr/bin/env python3
r"""Certified circuit-distance lower bounds for the circuit tier, through tropidist (issue #4717).

Every circuit-tier entry records d_circ as a witnessed upper bound: a fault
set the verifier checked, found by a randomized search that cannot say the
set is the lightest. tropidist (github.com/Fanerst/tropidist, arXiv:2611.08247)
proves lower bounds on the same problem by exhaustive search, and for a CSS
memory experiment it first reduces the problem to the detectors of the memory
basis and collapses the rounds, which is where most of its reach comes from.
Both reductions key on detector coordinates of the form (check, 0, round,
type), and the board's committed circuits carry none, so this script adds
them in memory before handing a circuit over:

    check  the index of the ancilla qubit the detector's measurements belong
           to (a flag qubit counts as its own check, so collapsing over the
           rounds groups each flag with itself);
    round  how many times that ancilla had been measured before, so repeated
           rounds line up whatever the gate schedule; a closure detector that
           also reads data qubits sits one round after the last extraction.
           Detectors of the other type than the memory basis are shifted one
           round later: the tool takes the type present at round 0 as the
           memory basis and refuses a circuit with both types there, which a
           flag measured from the first round on produces, and those rows are
           dropped by its sector reduction before anything reads their round;
    type   0 for an ancilla measured in the X basis and 3 for the Z basis,
           the two classes the tool's sector reduction separates. A flag
           qubit (an ancilla that touches no data qubit) is typed by its own
           measurement basis, by the basis of the check it protects, or by the
           memory basis, in that order, the first that makes the sector
           reduction exact under the tool's own sector_is_exact test; when
           none does, the tool searches the full detector error model.

The tool's record gives a proved lower bound and the lightest fault set it
found. A lower bound equal to the claimed d_circ makes that basis exact
together with the committed witness. A fault set lighter than the claim is a
refutation candidate: it is mapped back to the committed .dem's error indices
and checked with verify/circuit_tools.witness_errors before it is reported.
Nothing here edits codes/ or circuits/; the output is a dated record under
research/audits/.

    uv run python research/audits/circuit_distance_bounds.py --tropidist /path/to/tropidist \
        [--slugs 48-4-7 ...] [--tlim 60] [--threads 2] [--jobs 4] \
        [--out research/audits/circuit_distance_bounds-<date>.json]

The record is resumable: entries already in --out are skipped.
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
import circuit_tools as CT  # noqa: E402

CODES = os.path.join(ROOT, "codes")
CIRCUITS = os.path.join(ROOT, "circuits")
SIDE_FILES = {"X": "memory_x", "Z": "memory_z"}
TYPE_X, TYPE_Z = 0, 3
MEASURE = {"M": "Z", "MR": "Z", "MX": "X", "MRX": "X"}
TWO_QUBIT = {"CX", "CNOT", "ZCX", "CZ", "ZCZ", "CY", "ZCY", "XCX", "XCY", "XCZ", "YCX", "YCY", "YCZ",
             "SWAP", "ISWAP", "CXSWAP", "SWAPCX", "SQRT_XX", "SQRT_YY", "SQRT_ZZ"}
FLAG_POLICIES = ("basis", "check", "memory")
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------- the circuit
def measurements(circuit, n):
    """Per measurement index: (qubit, basis, how many times that qubit was measured before)."""
    out, count = [], {}
    for inst in circuit.flattened():
        basis = MEASURE.get(inst.name)
        if basis is None:
            if inst.name in ("MY", "MRY", "MPP"):
                raise ValueError(f"{inst.name} measurements are not supported")
            continue
        for t in inst.targets_copy():
            q = t.value
            out.append((q, basis, count.get(q, 0)))
            count[q] = count.get(q, 0) + 1
    return out


def ancilla_roles(circuit, n):
    """Return {ancilla: ("check", basis) | ("flag", basis, partner_check)} from the two-qubit gates and measurements.

    A check ancilla touches a data qubit in some two-qubit gate; a flag touches
    only other ancillas. The basis is that of the qubit's measurements.
    """
    touches_data, partners, basis = {}, {}, {}
    for inst in circuit.flattened():
        if inst.name in TWO_QUBIT:
            ts = [t.value for t in inst.targets_copy()]
            for a, b in zip(ts[::2], ts[1::2]):
                for q, other in ((a, b), (b, a)):
                    if q >= n:
                        if other < n:
                            touches_data[q] = True
                        else:
                            partners.setdefault(q, set()).add(other)
        b = MEASURE.get(inst.name)
        if b is not None:
            for t in inst.targets_copy():
                if t.value >= n:
                    basis.setdefault(t.value, b)
    roles = {}
    for q in sorted(basis):
        if touches_data.get(q):
            roles[q] = ("check", basis[q])
    for q in sorted(basis):
        if q in roles:
            continue
        checks = [p for p in partners.get(q, ()) if p in roles]
        roles[q] = ("flag", basis[q], checks[0] if checks else None)
    return roles


def detector_coordinates(circuit, n, basis, flag_policy="basis"):
    """Return one (check, 0, round, type) per detector, in detector order."""
    meas = measurements(circuit, n)
    roles = ancilla_roles(circuit, n)
    memory_type = TYPE_Z if basis == "Z" else TYPE_X

    def type_of(q):
        role = roles.get(q)
        if role is None:
            raise ValueError(f"qubit {q} is measured but has no role")
        if role[0] == "check" or flag_policy == "basis":
            return TYPE_Z if role[1] == "Z" else TYPE_X
        if flag_policy == "check" and role[2] is not None:
            return TYPE_Z if roles[role[2]][1] == "Z" else TYPE_X
        return memory_type

    coords, midx = [], 0
    for inst in circuit.flattened():
        if inst.name in MEASURE:
            midx += len(inst.targets_copy())
        if inst.name != "DETECTOR":
            continue
        refs = [meas[midx + t.value] for t in inst.targets_copy()]
        anc = sorted({r[0] for r in refs if r[0] >= n})
        if len(anc) != 1:
            raise ValueError(f"detector {len(coords)} references {len(anc)} ancillas; expected one")
        q = anc[0]
        rnd = max(r[2] for r in refs if r[0] >= n)
        if any(r[0] < n for r in refs):
            rnd += 1
        typ = type_of(q)
        if typ != memory_type:
            rnd += 1
        coords.append((q, 0, rnd, typ))
    return coords


def annotate(circuit, n, basis, flag_policy="basis"):
    """Return a copy of ``circuit`` whose DETECTOR instructions carry (check, 0, round, type) coordinates."""
    import stim
    coords = detector_coordinates(circuit, n, basis, flag_policy)
    out = stim.Circuit()
    i = 0
    for inst in circuit.flattened():
        if inst.name == "DETECTOR":
            out.append("DETECTOR", inst.targets_copy(), [float(x) for x in coords[i]])
            i += 1
        else:
            out.append(inst)
    return out


# ---------------------------------------------------------------------------- the tool
def tropidist_root(path=None):
    root = path or os.environ.get("TROPIDIST_ROOT")
    if not root:
        return None
    root = os.path.abspath(root)
    if not os.path.isfile(os.path.join(root, "bench", "common.py")):
        raise RuntimeError(f"{root} is not a tropidist checkout (no bench/common.py)")
    return root


def tropidist_commit(root):
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _bench(root):
    """Import the tool's bench/common module from the checkout."""
    for p in (root, os.path.join(root, "bench")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import common  # noqa: F401  (tropidist's bench/common.py)
    return common


def export_instance(root, circuit, directory, basis, slug):
    """Export the annotated circuit as a tool instance; return the reduction used.

    Tries the sector and time-collapse export first (exact only when every
    sector column lifts); falls back to the full detector error model.
    """
    common = _bench(root)
    parent, name = os.path.split(directory)
    meta = {"family": "qldpc-challenge", "description": f"circuits/{slug}/{SIDE_FILES[basis]}.stim",
            "source": slug}
    try:
        out = common.export_circuit_instance(name, circuit, [], dict(meta), root=parent, high=(basis == "Z"))
    except Exception:
        common.export_dem_instance(name, circuit, dict(meta), root=parent)
        return "full"
    for variant in out["variants"]:
        prob = common.to_cdist(common.load(directory, variant))
        out["variants"][variant].update(common.export_problem(directory, variant, prob,
                                                              common.lattice_perms(prob)))
    common.write_meta(directory, out)
    return "sector+collapse"


def run_pipeline(root, directory, out_path, *, tlim, threads):
    """Run the tool's benchmark pipeline (the configuration of python -m cdist) on an exported instance."""
    cmd = [sys.executable, os.path.join(root, "bench", "adapters", "ours_pipeline.py"), "--instance", directory,
           "--variant", "full", "--threads", str(int(threads)), "--time-limit", str(float(tlim)),
           "--config", "dp=2", "--out", out_path]
    proc = subprocess.run(cmd, cwd=root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if not os.path.exists(out_path):
        tail = (proc.stderr or "").strip().splitlines()
        raise RuntimeError("the pipeline wrote no record" + (f": {tail[-1]}" if tail else ""))
    with open(out_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------- witnesses
def _read_mtx_columns(path):
    """Columns of a MatrixMarket pattern file as frozensets of 0-based row indices."""
    with open(path, encoding="utf-8") as f:
        header = f.readline()
        if not header.startswith("%%MatrixMarket"):
            raise ValueError(f"{path} is not MatrixMarket")
        line = f.readline()
        while line.startswith("%"):
            line = f.readline()
        _, ncols, _ = map(int, line.split())
        cols = [set() for _ in range(ncols)]
        for line in f:
            if line.strip():
                r, c = map(int, line.split()[:2])
                cols[c - 1].add(r - 1)
    return [frozenset(c) for c in cols]


def map_witness(directory, witness, dem):
    """Map the tool's witness (columns of its full problem) to indices of the committed DEM's error instructions.

    The tool's full problem is the same undecomposed DEM with equal mechanisms
    merged, so each column's (detectors, observables) pair names a mechanism;
    the first committed error instruction with that pair stands for it.
    Returns the sorted index list, or None when a column has no match.
    """
    h = _read_mtx_columns(os.path.join(directory, "full.H.mtx"))
    lab = _read_mtx_columns(os.path.join(directory, "full.L.mtx"))
    index = {}
    for j, (ds, ls) in enumerate(CT.dem_columns(dem)):
        index.setdefault((frozenset(ds), frozenset(ls)), j)
    out = []
    for c in witness:
        j = index.get((h[c], lab[c]))
        if j is None:
            return None
        out.append(j)
    return sorted(out)


# ---------------------------------------------------------------------------- one entry
def bound_basis(root, slug, doc, basis, *, tlim, threads, work_dir):
    """Run the tool on one memory basis; return the per-basis record."""
    import stim
    n = doc["n"]
    claim = int(doc["circuit"]["d_circ"][basis]["value"])
    base = os.path.join(CIRCUITS, slug, SIDE_FILES[basis])
    circuit = stim.Circuit.from_file(base + ".stim")
    rec = {"claim": claim}
    reduction, policy = "full", None
    directory = os.path.join(work_dir, f"{slug}-{basis}")
    for pol in FLAG_POLICIES:
        try:
            annotated = annotate(circuit, n, basis, pol)
        except ValueError as e:
            rec["annotation_error"] = str(e)
            annotated = None
            break
        if os.path.isdir(directory):
            import shutil
            shutil.rmtree(directory)
        reduction = export_instance(root, annotated, directory, basis, slug)
        if reduction != "full":
            policy = pol
            break
    if annotated is None:
        export_instance(root, circuit, directory, basis, slug)
    rec.update(reduction=reduction, flag_policy=policy)
    t0 = time.time()
    try:
        tool = run_pipeline(root, directory, os.path.join(work_dir, f"{slug}-{basis}.json"), tlim=tlim,
                            threads=threads)
    except RuntimeError as e:
        rec.update(status="error", note=str(e), seconds=round(time.time() - t0, 1))
        return rec
    lb, ub = tool.get("lower_bound"), tool.get("upper_bound")
    rec.update(lower_bound=lb, upper_bound=ub, status=tool.get("status"),
               seconds=round(float(tool.get("seconds") or time.time() - t0), 1),
               mechanisms=tool.get("cols"), detectors=tool.get("rows"))
    if ub is not None and int(ub) < claim:
        with open(base + ".dem", encoding="utf-8") as f:
            dem = stim.DetectorErrorModel(f.read())
        mapped = map_witness(directory, tool.get("witness") or [], dem)
        errs = CT.witness_errors(dem, mapped, int(ub)) if mapped is not None else ["no mapping to the committed .dem"]
        rec.update(witness=mapped, witness_errors=errs,
                   verdict="refuted" if mapped is not None and not errs else "error")
    elif lb is not None and int(lb) > claim:
        rec.update(verdict="error", note=f"lower bound {lb} exceeds the verified claim {claim}")
    elif lb is not None and int(lb) == claim:
        rec["verdict"] = "exact"
    else:
        rec["verdict"] = "open"
    return rec


def bound_entry(root, slug, *, tlim, threads, work_dir):
    with open(os.path.join(CODES, slug + ".json"), encoding="utf-8") as f:
        doc = json.load(f)
    out = {"slug": slug, "n": doc["n"], "k": doc["k"], "d": doc["distance"]["d"],
           "rounds": doc["circuit"].get("rounds"), "bases": {}}
    for basis in ("X", "Z"):
        out["bases"][basis] = bound_basis(root, slug, doc, basis, tlim=tlim, threads=threads, work_dir=work_dir)
    verdicts = {b["verdict"] for b in out["bases"].values()}
    out["verdict"] = ("refuted" if "refuted" in verdicts else "error" if "error" in verdicts
                      else "exact" if verdicts == {"exact"} else "open")
    out["d_circ_lower_bound"] = min((b.get("lower_bound") or 0) for b in out["bases"].values())
    return out


# ---------------------------------------------------------------------------- the run
def circuit_slugs():
    return sorted(os.path.splitext(f)[0] for f in os.listdir(CODES)
                  if f.endswith(".json") and os.path.isdir(os.path.join(CIRCUITS, os.path.splitext(f)[0])))


def load_record(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def summarize(entries):
    verdicts = {}
    reductions = {}
    for e in entries:
        verdicts[e["verdict"]] = verdicts.get(e["verdict"], 0) + 1
        for b in e["bases"].values():
            reductions[b.get("reduction")] = reductions.get(b.get("reduction"), 0) + 1
    return {"entries": len(entries), "verdicts": verdicts, "reductions": reductions}


def tightened_doc(doc, entry, *, by, date, record_name):
    """Return the entry's codes/ document with every refuted basis lowered to the verified fault set.

    The shape is the circuit refutation binding of verify/check_authorship.py:
    the refuted side's value, witness, and upper_bound confidence change,
    the rest of the circuit block stays, and provenance.notes gains a
    sentence naming the refuter. Returns None when no basis is refuted.
    """
    import copy
    out = copy.deepcopy(doc)
    sentences = []
    for basis in ("X", "Z"):
        b = entry["bases"].get(basis) or {}
        if b.get("verdict") != "refuted" or b.get("witness_errors"):
            continue
        weight = len(b["witness"])
        out["circuit"]["d_circ"][basis] = {"value": weight, "confidence": "upper_bound",
                                           "witness": [int(i) for i in b["witness"]]}
        sentences.append(f"the {basis}-memory circuit has an undetected logical fault set of weight {weight} "
                         f"in its committed detector error model (claimed {b['claim']}), with a proved lower "
                         f"bound of {b['lower_bound']}")
    if not sentences:
        return None
    note = (f" Circuit fault distance corrected on {date} by {by}: " + "; ".join(sentences)
            + f". Found by tropidist (arXiv:2611.08247) through research/audits/{record_name}.")
    prov = out.setdefault("provenance", {})
    prov["notes"] = (prov.get("notes") or "") + note
    return out


def write_tightenings(record, out_dir, *, by, record_name):
    """Write one corrected codes/<slug>.json per refuted entry under out_dir; return the slugs written."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for e in record["entries"]:
        if e.get("verdict") != "refuted":
            continue
        with open(os.path.join(CODES, e["slug"] + ".json"), encoding="utf-8") as f:
            doc = json.load(f)
        new = tightened_doc(doc, e, by=by, date=record["date"], record_name=record_name)
        if new is None:
            continue
        with open(os.path.join(out_dir, e["slug"] + ".json"), "w", encoding="utf-8") as f:
            json.dump(new, f, indent=2)
            f.write("\n")
        written.append(e["slug"])
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tighten", default=None, metavar="OUT_DIR",
                    help="write the corrected codes/ documents of the refuted entries in --out to this directory "
                         "and exit (no tool run)")
    ap.add_argument("--by", default="@vprusso", help="the refuter's handle written into provenance.notes")
    ap.add_argument("--tropidist", default=None, help="the checkout to run (default: $TROPIDIST_ROOT)")
    ap.add_argument("--slugs", nargs="*", default=None, help="entries to run (default: every circuit tier)")
    ap.add_argument("--tlim", type=float, default=60.0, help="seconds per basis (default 60)")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--jobs", type=int, default=1, help="entries run at once")
    ap.add_argument("--out", default=None,
                    help="record path (default research/audits/circuit_distance_bounds-<date>.json)")
    a = ap.parse_args(argv)
    today = datetime.date.today().isoformat()
    out_path = a.out or os.path.join(HERE, f"circuit_distance_bounds-{today}.json")
    if a.tighten:
        record = load_record(out_path)
        if record is None:
            print(f"no record at {out_path}", file=sys.stderr)
            return 2
        written = write_tightenings(record, a.tighten, by=a.by, record_name=os.path.basename(out_path))
        print("corrected documents written: " + (" ".join(written) or "none"))
        return 0
    root = tropidist_root(a.tropidist)
    if root is None:
        print("no tropidist checkout: pass --tropidist or set TROPIDIST_ROOT", file=sys.stderr)
        return 2
    record = load_record(out_path) or {"date": today, "tool": "tropidist", "commit": tropidist_commit(root),
                                        "paper": "arXiv:2611.08247", "tlim_per_basis": a.tlim, "threads": a.threads,
                                        "entries": []}
    done = {e["slug"] for e in record["entries"]}
    slugs = [s for s in (a.slugs or circuit_slugs()) if s not in done]
    work = tempfile.mkdtemp(prefix="circuit-bounds-")

    def one(slug):
        try:
            return bound_entry(root, slug, tlim=a.tlim, threads=a.threads, work_dir=work)
        except Exception as e:      # one broken entry must not end the run
            return {"slug": slug, "verdict": "error", "note": f"{type(e).__name__}: {e}", "bases": {}}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for entry in ex.map(one, slugs):
            with _LOCK:
                record["entries"].append(entry)
                record["summary"] = summarize(record["entries"])
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(record, f, indent=1, sort_keys=True)
                    f.write("\n")
            bits = " ".join(f"{b}:{v.get('lower_bound')}/{v.get('claim')}({v.get('reduction', '?')[:4]})"
                            for b, v in sorted(entry.get("bases", {}).items()))
            print(f"{entry['slug']}: {entry['verdict']} {bits}", flush=True)
    print(json.dumps(record.get("summary")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
