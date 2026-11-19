"""Verifier for measured logical-error-rate claims.

Usage:
    python verify/ler_verify.py codes/your-code.json [circuits-dir] [--all]

Exit code 0 iff every check passes for both bases. Prints a JSON report in the
shape of circuit_verify's. Needs ldpc (the `research` extra): a claim that
cannot be checked must not merge, so a missing decoder is a failure here, not
a skip.

An `ler` block rides inside `circuit`, so the circuit artifacts have already
passed circuit_verify in the same CI job; this file re-derives the DEM from
the committed .stim anyway (same pinned path) rather than trusting the .dem
on disk, so the two verifiers cannot be split apart by a later workflow edit.

Since schema 0.5 (issue #1278) a basis carries a LIST of points, one per
physical rate on the grid P_GRID, each {p, shots, failures, seed, decoder,
ler_per_round, ci95}; the committed circuit is at the canonical rate and the
circuit at another p is apply_noise(strip_noise(circuit), n, p), the same
recipe at a different rate. The pre-0.5 form, one object at p = 0.001, is read
as a one-point list and is still accepted on entries that declare schema 0.4
or earlier.

Checks, per basis:
  arithmetic   every point: p is on the grid, ler_per_round and ci95 recompute
               exactly from (failures, shots, rounds) via the pinned
               conversion and Wilson interval, the decoder is one of the
               registry (ler_tools.DECODERS; issue #5804) and admitted on
               this circuit,
               the claim meets the shot and failure floors (MIN_FAILURES is
               what makes the number a comparison rather than an order of
               magnitude) and is not saturated (a per-shot failure fraction
               above 1/2 reads as a per-round rate of 1/2 whatever the
               circuit does, so such a point says nothing); (rate, decoder)
               pairs are distinct across points
  replication  an independent re-sample decoded with the point's own decoder must
               agree with the claimed per-shot rate to within sampling error
               (|p_rep - p_claim| <= Z_GATE sigma of the replica). The
               replica is SIZED TO DISCRIMINATE, not to a fixed shot count:
               it targets REPLICA_FAILURES expected failures under the
               claimed rate, which puts the 4-sigma detection threshold near
               a factor 1.4 under-report independent of the rate. At PR time
               (mode "gate") the points are tried from the highest rate down
               inside one wall budget per basis and per decoder (LER_SECONDS;
               an entry carrying curves under several decoders pays the gate
               once per decoder, and each decoder must verify one point); the first
               point is the cheapest, since failures are most common there.
               A point the budget cannot check to the admissibility bound
               (a factor-2 under-report caught with power) is DEFERRED to the
               weekly post-merge replication (verify/ler_replicate.py, which
               runs mode "all" with a long budget per point and several
               seeds and writes receipts/ler/<slug>.json), and every lower
               point with it; at least one point must verify at PR time or
               the claim fails as unverifiable within budget. Statistical by
               design: the sampler is seed-deterministic but BP is float
               arithmetic, so bit-exact replication across platforms is not
               a promise the board can keep.

The claim is self-reported measurement, verified by re-measurement; there is
no clamp analogous to d_circ <= d because a rate has no code-level bound to
clamp to. The gaming direction is claiming a rate LOWER than the circuit
earns, and that is exactly what the replication test detects.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import circuit_tools as ct
import ler_tools as lt

P_GRID = (0.01, 0.005, 0.002, 0.001)   # admissible physical rates, high to low
LEGACY_SCHEMAS = ("0.1", "0.2", "0.3", "0.4")   # one object at p = 0.001
SATURATION = 0.5             # per-shot failure fraction above which the
                             # per-round conversion clamps and the point
                             # carries no information
REPLICA_FAILURES = 150       # expected failures the replica targets. With
                             # a floor claim (100 failures) and a full
                             # replica, the combined-variance 50%-power
                             # detection point lands near 1.5x; the
                             # admissibility bound below (2x) is the hard
                             # line the gate enforces
REPLICA_SHOTS_CAP = 2_000_000
LER_SECONDS = 120.0          # PR-time wall budget per basis, mirroring the
                             # circuit gate's refutation target
REPLICATE_SECONDS = 1800.0   # post-merge wall budget per point (all seeds)
REPLICATE_SEEDS = 3          # independent replicas per point, post-merge
REPLICA_SEED_SALT = 0x5EED1E12
Z_GATE = 4.0
MAX_DETECTABLE_FACTOR = 2.0  # admissibility: a factor-2 under-report must
                             # be caught with high power, not merely at even
                             # money, or the claim fails as unverifiable
                             # within budget
POWER_SIGMA = 2.0            # power margin for the admissibility test: the
                             # alternative's own spread (which scales like
                             # sqrt(f) of the null's replica term) must also
                             # clear the gate, so a boundary tamper is
                             # caught ~97.7% of the time, not ~50%

SIDE_FILES = {"X": "memory_x", "Z": "memory_z"}


def points_of(claim):
    """A basis's claim as a list of points (the pre-0.5 object becomes a
    one-point list). None for anything else."""
    if isinstance(claim, dict):
        return [claim]
    if isinstance(claim, list):
        return claim
    return None


def is_legacy_form(ler):
    """True when either basis still uses the pre-0.5 single-object form."""
    return any(isinstance(ler.get(s), dict) for s in ("X", "Z"))


def gate_point(points, decoder=lt.DECODER_ID):
    """The point the PR-time gate replicates first under ``decoder``: the
    highest rate measured with it. If the entry merged, this point verified at
    PR time (the gate tries rates from the top down and stops at the first it
    cannot afford, so a merged entry's top point is always a gate-verified
    one). The default is the reference decoder, the one the board's headline
    rate reads; pass None for the highest rate under any decoder."""
    pts = [q for q in points if isinstance(q, dict)
           and (decoder is None or q.get("decoder", lt.DECODER_ID) == decoder)]
    return max(pts, key=lambda q: q.get("p") or 0) if pts else None


def summary_rate(doc):
    """One number for an entry: the worse side's per-round rate at its gate
    point (the highest rate claimed under the reference decoder), or None
    without a measured tier under that decoder."""
    ler = (doc.get("circuit") or {}).get("ler")
    if not ler:
        return None
    vals = []
    for s in ("X", "Z"):
        pts = points_of(ler.get(s))
        g = gate_point(pts or [])
        if g is not None and isinstance(g.get("ler_per_round"), (int, float)):
            vals.append(g["ler_per_round"])
    return max(vals) if vals else None


def replica_size(p_claim):
    return min(max(lt.MIN_SHOTS, math.ceil(REPLICA_FAILURES / p_claim)),
               REPLICA_SHOTS_CAP)


def replica_verdict(claim_shots, p_claim, rep_fail, rep_done):
    """The replication statistics for one point: (admissible, agrees,
    detectable_factor, sigma). Variance of the DIFFERENCE statistic under an
    honest claim: both the claim and the replica are binomial draws, so both
    contribute (omitting the claim's term turns a nominal 4 sigma into ~2.5
    sigma of the real statistic at the failure floor)."""
    p_rep = rep_fail / rep_done
    var = max(p_claim * (1 - p_claim), 1.0 / rep_done) \
        * (1.0 / claim_shots + 1.0 / rep_done)
    sigma = math.sqrt(var)
    # The under-report factor whose detection is even money at Z_GATE: a
    # claim of p_true/f sits (f-1) p_claim below truth, so the mean crosses
    # the gate at f = 1 + Z_GATE sigma / p_claim (the 50%-power point).
    detectable = 1.0 + Z_GATE * sigma / p_claim
    # Admissibility with power: a factor-f tamper's replica fluctuates around
    # f * p_claim with spread ~sqrt(f) * sigma, so demanding
    # (f - 1) p >= Z_GATE sigma + POWER_SIGMA sqrt(f) sigma makes the
    # boundary factor caught with ~97.7% power rather than 50%.
    f = MAX_DETECTABLE_FACTOR
    needed = (Z_GATE + POWER_SIGMA * math.sqrt(f)) * sigma / p_claim
    admissible = needed <= (f - 1.0)
    agrees = abs(p_rep - p_claim) <= Z_GATE * sigma
    return admissible, agrees, detectable, sigma


def point_errors(point, rounds):
    """Arithmetic errors of one point (empty list iff the point is exact)."""
    errs = []
    p = point.get("p")
    if p not in P_GRID:
        errs.append(f"p={p} is not on the rate grid {list(P_GRID)}")
    if point.get("decoder") not in lt.DECODERS:
        errs.append(f"decoder={point.get('decoder')!r} is not in the registry "
                    f"({', '.join(lt.DECODERS)})")
    shots, failures = point.get("shots", 0), point.get("failures", -1)
    if shots < lt.MIN_SHOTS:
        errs.append(f"shots={shots} below the statistical floor "
                    f"{lt.MIN_SHOTS}")
    if not 0 <= failures <= shots:
        errs.append(f"failures={failures} outside [0, shots]")
    elif failures < lt.MIN_FAILURES:
        errs.append(f"failures={failures} below the floor "
                    f"{lt.MIN_FAILURES}: raise shots until the claim "
                    f"carries at least that many (a smaller count "
                    f"cannot resolve the prefactor comparisons this "
                    f"tier exists for)")
    elif shots and failures / shots > SATURATION:
        errs.append(f"failures/shots={failures / shots:.3f} exceeds "
                    f"{SATURATION:g}: the point is saturated (the per-round "
                    f"conversion clamps at 1/2), so it carries no "
                    f"information; drop it or measure at a lower p")
    if errs:
        return errs
    p_shot = failures / shots
    want = round(lt.per_round(p_shot, rounds), 9)
    lo, hi = lt.wilson_ci(failures, shots)
    want_ci = [round(lt.per_round(lo, rounds), 9),
               round(lt.per_round(hi, rounds), 9)]
    if abs(point.get("ler_per_round", -1) - want) > 1e-9:
        errs.append(f"ler_per_round={point.get('ler_per_round')} does not "
                    f"recompute ({want} from failures/shots/rounds)")
    got_ci = point.get("ci95") or [-1, -1]
    if (abs(got_ci[0] - want_ci[0]) > 1e-9
            or abs(got_ci[1] - want_ci[1]) > 1e-9):
        errs.append(f"ci95={got_ci} does not recompute ({want_ci})")
    return errs


def _circuit_at(circuit, n, p):
    """The committed circuit at physical rate p: the canonical recipe
    re-applied to the noiseless skeleton (at P_REF this is the committed
    circuit itself, which circuit_verify already checked)."""
    if p == ct.P_REF:
        return circuit
    return ct.apply_noise(ct.strip_noise(circuit), n, p=p)


def _dem_at(circuit, n, p):
    """The committed circuit's DEM at physical rate p (see _circuit_at)."""
    return ct.derive_dem(_circuit_at(circuit, n, p))


def replicate_point(dem, point, *, budget, seeds=1, circuit=None):
    """Re-measure one point. `budget` is wall seconds for the whole point,
    split evenly across `seeds` independent replicas whose counts are pooled
    (the per-seed values are returned too, so a reader can see the spread).
    Returns a dict with the pooled statistics and a `status` of
    "verified", "failed" (replica disagrees), or "unverifiable" (the budget
    could not afford a replica that catches a factor-2 under-report)."""
    shots, failures = point["shots"], point["failures"]
    p_claim = failures / shots
    want = replica_size(p_claim)
    per_seed = max(1, want // max(1, seeds))
    runs = []
    for i in range(seeds):
        seed = (point["seed"] ^ REPLICA_SEED_SALT ^ (i * 0x9E3779B1)) \
            & 0x7FFFFFFF
        fail, done = lt.measure_failures(dem, per_seed, seed,
                                         max_seconds=budget / max(1, seeds),
                                         decoder=point.get("decoder", lt.DECODER_ID),
                                         circuit=circuit)
        runs.append({"seed": seed, "shots": done, "failures": fail})
    rep_done = sum(r["shots"] for r in runs)
    rep_fail = sum(r["failures"] for r in runs)
    if rep_done == 0:
        return {"status": "unverifiable", "replica_shots": 0,
                "replica_failures": 0, "runs": runs, "detectable_factor": None}
    admissible, agrees, detectable, sigma = replica_verdict(
        shots, p_claim, rep_fail, rep_done)
    status = ("unverifiable" if not admissible
              else "verified" if agrees else "failed")
    return {"status": status, "p": point["p"], "claimed_p_shot": p_claim,
            "replica_shots": rep_done, "replica_failures": rep_fail,
            "replica_p_shot": rep_fail / rep_done, "sigma": sigma,
            "detectable_factor": round(detectable, 3), "runs": runs}


def verify_ler(doc, circuits_dir, *, mode="gate", budget=None, seeds=None):
    """Check the doc's circuit.ler block; returns a report dict, report['ok']
    is the verdict.

    mode "gate" (PR time): per basis, points from the highest rate down
    inside `budget` seconds (default LER_SECONDS); the first point the
    budget cannot check to the admissibility bound is deferred, with every
    point below it, and at least one point must verify.
    mode "all" (post-merge): every point, `budget` seconds each (default
    REPLICATE_SECONDS) split across `seeds` replicas (default
    REPLICATE_SEEDS); nothing is deferred, an unaffordable point is reported
    as unverifiable. report["computed"][side]["points"] carries every
    point's replication record, keyed by its rate as a string, which is what
    ler_replicate.py writes into the receipt."""
    report = {"ok": True, "checks": [], "computed": {}}

    def record(label, ok, detail=""):
        report["checks"].append({"check": label, "ok": bool(ok),
                                 "detail": detail})
        if not ok:
            report["ok"] = False

    circ = doc.get("circuit") or {}
    ler = circ.get("ler")
    if not ler:
        record("ler_block_present", False, "no circuit.ler block")
        return report
    try:
        import ldpc  # noqa: F401
    except ImportError:
        record("decoder_available", False,
               "ldpc is not installed; an ler claim cannot be verified "
               "(install the `research` extra)")
        return report
    rounds = circ.get("rounds")
    n = doc["n"]
    if mode not in ("gate", "all"):
        raise ValueError("mode must be 'gate' or 'all'")
    if budget is None:
        budget = LER_SECONDS if mode == "gate" else REPLICATE_SECONDS
    if seeds is None:
        seeds = 1 if mode == "gate" else REPLICATE_SEEDS

    if is_legacy_form(ler):
        record("ler_form", doc.get("schema_version") in LEGACY_SCHEMAS,
               "pre-0.5 single-point form, read as one point at p = 0.001"
               if doc.get("schema_version") in LEGACY_SCHEMAS else
               f"schema {doc.get('schema_version')} entries carry "
               f"circuit.ler.<basis> as a list of points (issue #1278)")

    for side in ("X", "Z"):
        points = points_of(ler.get(side))
        if not points:
            record(f"{side}_ler_claimed", False, "side missing or empty")
            continue

        # -- arithmetic: every point must be internally exact ---------------
        errs = []
        seen = []
        for point in points:
            perr = point_errors(point, rounds)
            errs += [f"p={point.get('p')}: {e}" for e in perr]
            pair = (point.get("p"), point.get("decoder"))
            if pair in seen:
                errs.append(f"p={pair[0]} under decoder {pair[1]!r} appears twice")
            seen.append(pair)
        record(f"{side}_ler_arithmetic", not errs, "; ".join(errs) or
               f"{len(points)} point(s) recompute exactly at p = "
               f"{', '.join(str(q['p']) for q in sorted(points, key=lambda q: -q['p']))}")
        if errs:
            continue

        # -- replication: re-measure with independent seeds -----------------
        base = os.path.join(circuits_dir, SIDE_FILES[side])
        try:
            import stim
            circuit = stim.Circuit.from_file(base + ".stim")
        except Exception as e:
            record(f"{side}_ler_replicated", False,
                   f"could not load committed circuit: {e}")
            continue
        results = {}
        verified, failed, deferred = [], [], []
        import time
        decoders = [d for d in lt.DECODERS
                    if any(q.get("decoder") == d for q in points)]
        for decoder in decoders:
            group = sorted((q for q in points if q.get("decoder") == decoder),
                           key=lambda q: -q["p"])
            label = "" if decoder == lt.DECODER_ID else f"_{decoder}"
            admitted, why = lt.decoder_admits(decoder, circuit)
            if not admitted:
                for q in group:
                    results[lt.point_key(q["p"], decoder)] = {
                        "status": "inadmissible", "p": q["p"],
                        "decoder": decoder, "detail": why}
                record(f"{side}_ler_decoder{label}", False, why)
                continue
            deadline = time.monotonic() + budget if mode == "gate" else None
            dec_deferred = []
            for point in group:
                p = point["p"]
                key = lt.point_key(p, decoder)
                if mode == "gate":
                    left = deadline - time.monotonic()
                    if dec_deferred or left <= 0:
                        dec_deferred.append(p)
                        results[key] = {"status": "deferred", "p": p,
                                        "decoder": decoder}
                        continue
                    res = replicate_point(_dem_at(circuit, n, p), point,
                                          budget=left, seeds=1,
                                          circuit=_circuit_at(circuit, n, p))
                    if res["status"] == "unverifiable":
                        res["status"] = "deferred"
                        dec_deferred.append(p)
                else:
                    res = replicate_point(_dem_at(circuit, n, p), point,
                                          budget=budget, seeds=seeds,
                                          circuit=_circuit_at(circuit, n, p))
                res["decoder"] = decoder
                results[key] = res
                if res["status"] == "verified":
                    verified.append((p, decoder))
                elif res["status"] == "failed":
                    failed.append((p, decoder))
            deferred.extend((p, decoder) for p in dec_deferred)

            def fmt(p, decoder=decoder):
                r = results[lt.point_key(p, decoder)]
                return (f"p={p}: replica {r['replica_failures']}/"
                        f"{r['replica_shots']} = {r['replica_p_shot']:.4g} vs "
                        f"claimed {r['claimed_p_shot']:.4g}, detects >= "
                        f"{r['detectable_factor']}x")
            dec_failed = [p for p, d in failed if d == decoder]
            dec_verified = [p for p, d in verified if d == decoder]
            if dec_failed:
                record(f"{side}_ler_replicated{label}", False,
                       f"{decoder}: replica disagrees with the claim beyond "
                       f"{Z_GATE:g} sigma at " + "; ".join(fmt(p) for p in dec_failed))
                continue
            if mode == "gate" and not dec_verified:
                record(f"{side}_ler_replicated{label}", False,
                       f"{decoder}: unverifiable within budget: no point could be "
                       f"checked to the factor-{MAX_DETECTABLE_FACTOR:g} admissibility "
                       f"bound in {budget:.0f} s (tried p = "
                       f"{', '.join(str(p) for p in dec_deferred)}). The claim may be "
                       f"honest, but this gate cannot check it; add a point at a "
                       f"higher rate, where failures are common")
                continue
            unverifiable = [q["p"] for q in group
                            if results[lt.point_key(q["p"], decoder)]["status"]
                            == "unverifiable"]
            detail = f"{decoder}: verified at " + "; ".join(fmt(p) for p in dec_verified)
            if dec_deferred:
                detail += (f" | deferred to the post-merge replication: p = "
                           f"{', '.join(str(p) for p in dec_deferred)}")
            if unverifiable:
                detail += (f" | unverifiable within {budget:.0f} s per point: "
                           f"p = {', '.join(str(p) for p in unverifiable)}")
            record(f"{side}_ler_replicated{label}", True, detail)
            for p in dec_deferred:
                record(f"{side}_ler_p{p}{label}_deferred", True,
                       "left to verify/ler_replicate.py (weekly, long budget); "
                       "pending on the board until its receipt lands")
        report["computed"][side] = {"points": results, "mode": mode}
    return report


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    mode = "all" if "--all" in argv else "gate"
    argv = [a for a in argv if a != "--all"]
    path = argv[0]
    doc = json.load(open(path))
    slug = os.path.splitext(os.path.basename(path))[0]
    circuits_dir = (argv[1] if len(argv) > 1 else
                    os.path.join(os.path.dirname(os.path.abspath(path)),
                                 "..", "circuits", slug))
    report = verify_ler(doc, circuits_dir, mode=mode)
    print(json.dumps(report, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
