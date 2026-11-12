"""
Adversarial tests for the circuit-tier verifier (RFC 0001, issue #505): it
must ACCEPT a valid circuit-tier artifact and REJECT every way a circuit
claim can be wrong -- a tampered witness, a stale DEM, non-canonical noise, a
circuit that is not a memory experiment of the declared code, an inflated
round count, an unpinned stim.

The known-good artifact is generated once per run from the board's
[[25,1,5]] surface entry with the toolkit's own builder + searcher (the same
loop a submitter runs), so these tests need no committed circuits/ artifact
and gate the trusted stack independently of any submission. The default
greedy schedule's d_circ is below d (a hook error -- the phenomenon the tier
exists to expose); that is fine here: these tests exercise the validity of
claims, not schedule quality. Each tamper then breaks exactly one thing and
asserts the specific check catches it.

Run: uv run pytest verify/test_circuit_verify.py
"""

import copy
import json
import os
import shutil

import pytest
import stim

import circuit_tools as ct
import circuit_verify as cv
from qldpc_verify import _matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DOC = json.load(open(os.path.join(ROOT, "codes", "25-1-5.json")))
N = BASE_DOC["n"]


@pytest.fixture(scope="module")
def seed(tmp_path_factory):
    """(doc, circuits_dir): a complete valid artifact -- both memory circuits
    with canonical noise, committed DEMs, and a circuit block whose witnesses
    the toolkit search found."""
    d = tmp_path_factory.mktemp("circuits")
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    doc = copy.deepcopy(BASE_DOC)
    doc["schema_version"] = "0.2"
    block = {"d_circ": {}, "rounds": 5, "stim_version": stim.__version__,
             "notes": "test artifact, default greedy schedule"}
    for basis in ("Z", "X"):
        skel = ct.build_css_memory(HX, HZ, rounds=5, basis=basis)
        noisy = ct.apply_noise(skel, N)
        dem = ct.derive_dem(noisy)
        H, L = ct.dem_matrices(dem)
        w, wit = ct.ris_dem(H, L, trials=8, seed=5)
        stem = os.path.join(d, f"memory_{basis.lower()}")
        open(stem + ".stim", "w").write(str(noisy) + "\n")
        open(stem + ".dem", "w").write(str(dem) + "\n")
        block["d_circ"][basis] = {"value": w, "confidence": "upper_bound",
                                  "witness": wit}
    doc["circuit"] = block
    return doc, str(d)


def _status(report, label):
    return next(c["ok"] for c in report["checks"] if c["check"] == label)


def _tampered_dir(seed_dir, tmp_path, filename, edit):
    d = tmp_path / "circuits"
    shutil.copytree(seed_dir, d)
    p = d / filename
    p.write_text(edit(p.read_text()))
    return str(d)


def test_generated_artifact_passes(seed):
    doc, d = seed
    report = cv.verify_circuit(doc, d)
    assert report["ok"], report
    want = min(doc["circuit"]["d_circ"][s]["value"] for s in ("X", "Z"))
    assert report["earned_d_circ"]["d_circ"] == {"value": want,
                                                 "tier": "upper_bound"}


def test_missing_files_rejected(seed, tmp_path):
    doc, _ = seed
    report = cv.verify_circuit(doc, str(tmp_path))
    assert not report["ok"]
    assert not _status(report, "X_circuit_files")


def test_tampered_witness_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    doc["circuit"]["d_circ"]["Z"]["witness"] = \
        doc["circuit"]["d_circ"]["Z"]["witness"][:-1]      # weight != value
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_witness_valid")

    w = doc["circuit"]["d_circ"]["Z"]["value"]
    doc["circuit"]["d_circ"]["Z"]["witness"] = list(range(w))  # detected junk
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_witness_valid")


def test_claim_above_code_distance_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    side = doc["circuit"]["d_circ"]["Z"]
    side["witness"] = side["witness"] + [side["witness"][-1] + 1]
    side["value"] = len(side["witness"])
    while side["value"] <= doc["distance"]["d"]:   # inflate past the clamp
        side["witness"].append(side["witness"][-1] + 1)
        side["value"] += 1
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_witness_valid")


def test_stale_dem_rejected(seed, tmp_path):
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.dem",
                      lambda t: t.replace("error(0.00", "error(0.01", 1))
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_dem_reproduces")


def test_missing_noise_channel_rejected(seed, tmp_path):
    def drop_first_dep2(t):
        lines = t.splitlines()
        i = next(j for j, l in enumerate(lines)
                 if l.startswith("DEPOLARIZE2"))
        return "\n".join(lines[:i] + lines[i + 1:]) + "\n"
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim", drop_first_dep2)
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_noise_recipe_canonical")


def test_wrong_noise_rate_rejected(seed, tmp_path):
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim",
                      lambda t: t.replace("DEPOLARIZE2(0.001)",
                                          "DEPOLARIZE2(0.002)", 1))
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_noise_recipe_canonical")


def test_nondeterministic_detector_rejected(seed, tmp_path):
    def break_detector(t):
        i = t.index("DETECTOR rec[")
        j = t.index("\n", i)
        return t[:i] + "DETECTOR rec[-1]" + t[j:]   # lone data M: random
    doc, sd = seed
    d = _tampered_dir(sd, tmp_path, "memory_z.stim", break_detector)
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_detectors_deterministic")


def test_inflated_round_count_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    doc["circuit"]["rounds"] = 6            # circuit only performs 5
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "Z_code_binding")


def test_unpinned_stim_version_rejected(seed):
    doc, d = seed
    doc = copy.deepcopy(doc)
    doc["circuit"]["stim_version"] = "1.0.0"
    report = cv.verify_circuit(doc, d)
    assert not _status(report, "stim_version_pinned")


def test_stabilizer_observable_rejected(seed, tmp_path):
    """An observable that is a product of declared stabilizers protects
    nothing; binding must reject it even though it is deterministic."""
    doc, sd = seed
    text = open(os.path.join(sd, "memory_z.stim")).read()
    lines = [l for l in text.splitlines()
             if not l.startswith("OBSERVABLE_INCLUDE")]
    row = BASE_DOC["checks"]["Z"][0]        # final data M of qubit q: rec[q-n]
    lines.append("OBSERVABLE_INCLUDE(0) " +
                 " ".join(f"rec[{q - N}]" for q in row))
    d = tmp_path / "circuits"
    shutil.copytree(sd, d)
    noisy = stim.Circuit("\n".join(lines))
    (d / "memory_z.stim").write_text(str(noisy) + "\n")
    (d / "memory_z.dem").write_text(str(ct.derive_dem(noisy)) + "\n")
    report = cv.verify_circuit(doc, str(d))
    assert not _status(report, "Z_code_binding")


def test_tick_coarsening_rejected():
    """vprusso's #646 review: idle-data mechanisms scale with TICK layer
    count, so deleting TICKs -- pure annotations -- shed fault mechanisms and
    inflated d_circ while staying recipe-conformant. Coarsening that claims
    impossible simultaneity (a qubit operated on twice in one layer) must now
    be rejected; merging genuinely disjoint layers -- real pipelining --
    stays legal."""
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    skel = ct.build_css_memory(HX, HZ, rounds=2, basis="Z")
    lines = str(skel).splitlines()

    # all TICKs deleted: one giant "layer" reusing every ancilla
    coarse = stim.Circuit("\n".join(l for l in lines if l != "TICK"))
    noisy = ct.apply_noise(coarse, N)
    errs = ct.noise_recipe_errors(noisy, N)
    assert errs and "parallel" in errs[0]
    assert ct.derive_dem(noisy).num_errors < \
        ct.derive_dem(ct.apply_noise(skel, N)).num_errors      # the lever

    # merging two DISJOINT layers (MX on X-ancillas, then R on Z-ancillas)
    # is honest pipelining and must stay conformant
    i = next(j for j, l in enumerate(lines) if l.startswith("MX "))
    assert lines[i + 1] == "TICK" and lines[i + 2].startswith("R ")
    merged = stim.Circuit("\n".join(lines[:i + 1] + lines[i + 2:]))
    assert ct.noise_recipe_errors(ct.apply_noise(merged, N), N) == []


def test_dem_matches_unit():
    """Probabilities compare to float tolerance (last ulps are architecture-
    sensitive: an honest artifact from another machine must pass), but any
    structural difference -- and any real probability tamper -- must not."""
    a = stim.DetectorErrorModel("error(0.0044999999999999) D0 D1 L0")
    assert ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0045000000000001) D0 D1 L0"))          # ulp drift: honest
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0046) D0 D1 L0"))                      # real tamper
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0045) D0 D2 L0"))                      # structure
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        "error(0.0045) D0 D1"))                         # observable dropped
    assert not ct.dem_matches(a, a + stim.DetectorErrorModel(
        "error(0.0045) D1"))                            # extra mechanism


def test_witness_errors_unit():
    dem = stim.DetectorErrorModel("""
        error(0.1) D0 L0
        error(0.1) D0
        error(0.1) D1
    """)
    assert ct.witness_errors(dem, [0, 1], 2) == []
    assert ct.witness_errors(dem, [0], 1)            # detected
    assert ct.witness_errors(dem, [1, 2], 2)         # flips nothing
    assert ct.witness_errors(dem, [0, 1], 3)         # weight mismatch
    assert ct.witness_errors(dem, [1, 0], 2)         # not sorted
    assert ct.witness_errors(dem, [0, 9], 2)         # out of range


def test_search_matches_witness_check():
    """The toolkit loop an agent runs: build, search, self-check -- the same
    arithmetic CI applies."""
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    skel = ct.build_css_memory(HX, HZ, rounds=2, basis="Z")
    noisy = ct.apply_noise(skel, N)
    assert ct.noise_recipe_errors(noisy, N) == []
    dem = ct.derive_dem(noisy)
    H, L = ct.dem_matrices(dem)
    w, wit = ct.ris_dem(H, L, trials=8, seed=3)
    assert w is not None and w <= 5      # rounds-truncated: can only be <= d
    assert ct.witness_errors(dem, wit, w) == []


def test_dem_lint_clean_on_reference():
    """The reference builder's DEM must pass all three structural checks
    (issue #690); a false positive here would block every honest entry."""
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    dem = ct.derive_dem(ct.apply_noise(
        ct.build_css_memory(HX, HZ, rounds=2, basis="Z"), N))
    assert ct.dem_lint(dem) == []


def test_dem_lint_detectability():
    # a mechanism flipping an observable with no detector = d_circ 1
    dem = stim.DetectorErrorModel("""
        error(0.001) D0 L0
        error(0.001) L0
        error(0.001) D0
    """)
    errs = ct.dem_lint(dem)
    assert any(e.startswith("detectability") and "[1]" in e for e in errs), errs


def test_dem_lint_observable_coverage():
    # L1 declared (via the max observable index) but never flipped
    dem = stim.DetectorErrorModel("""
        error(0.001) D0 L0
        detector D1
        logical_observable L1
    """)
    errs = ct.dem_lint(dem)
    assert any(e.startswith("observable_coverage") and "[1]" in e
               for e in errs), errs


def test_dem_lint_probability_bounds():
    # stim refuses NaN at parse time, so construct the edge cases it allows:
    # an exact-zero and an exact-one probability are both meaningless priors.
    dem = stim.DetectorErrorModel("""
        error(0) D0 L0
        error(1) D0
        error(0.001) D0 L0
    """)
    errs = ct.dem_lint(dem)
    assert any(e.startswith("probability_bounds") and "[0, 1]" in e
               for e in errs), errs


def test_dem_lint_gates_the_verifier(seed, monkeypatch):
    """A structurally broken derived DEM must fail circuit_verify at the new
    step 5.5 and stop before the witness check."""
    doc, cdir = seed
    monkeypatch.setattr(ct, "dem_lint",
                        lambda dem, cols=None: [
                            "detectability: injected failure"])
    rep = cv.verify_circuit(doc, cdir)
    assert not rep["ok"]
    bad = {c["check"]: c["detail"] for c in rep["checks"] if not c["ok"]}
    assert any(k.endswith("_dem_structure") for k in bad), bad
    checked = [c["check"] for c in rep["checks"]]
    assert not any(k.endswith("_witness_valid") for k in checked), (
        "witness check ran on a malformed DEM")


# ------------------------------------------------- issue #5409: same verdicts
#
# The circuit tier costs time in proportion to the mechanisms it walks, and
# issue #5409 removed walks without changing what any of them decides. The
# tests below hold the faster code to the slower code it replaced, on DEMs
# built here rather than on board entries, so they keep meaning the same
# thing whatever is merged.

def _dem_items(rng, tags=False):
    """A small DEM as [name, tag, args, targets] rows, using every form a
    derived model can: several targets, repeated targets, separators, an
    error with no target, detector and observable declarations with and
    without coordinates, and (with `tags`) tags holding text that looks
    like DEM."""
    def tag():
        if not tags or rng.random() < 0.5:
            return ""
        return rng.choice(["t", "a b", "error(0.5) L0", "p(q) r", "D3 L1 ^",
                           "x\\nerror(0.5) D1 L0", "\\C \\B"])

    def error():
        toks = []
        for _ in range(rng.randint(1, 3)):
            part = [f"D{rng.randrange(30)}" for _ in range(rng.randint(0, 4))]
            part += [f"L{rng.randrange(3)}" for _ in range(rng.randint(0, 2))]
            rng.shuffle(part)
            if part:
                toks += (["^"] if toks else []) + part
        p = rng.choice([0.001, 0.25, rng.uniform(1e-6, 0.5)])
        return ["error", tag(), [p], toks]

    items = []
    for _ in range(rng.randint(3, 12)):
        r = rng.random()
        if r < 0.75:
            items.append(error())
        elif r < 0.85:
            items.append(["detector", tag(),
                          [float(rng.randrange(9)), rng.uniform(0, 3)],
                          [f"D{rng.randrange(30)}"]])
        elif r < 0.92:
            items.append(["detector", tag(), [], [f"D{rng.randrange(30)}"]])
        else:
            items.append(["logical_observable", tag(), [],
                          [f"L{rng.randrange(3)}"]])
    return items


def _dem(items):
    """The stim model of _dem_items rows."""
    return stim.DetectorErrorModel("\n".join(
        name + (f"[{tag}]" if tag else "")
        + (f"({', '.join(repr(a) for a in args)})" if args else "")
        + "".join(" " + t for t in toks)
        for name, tag, args, toks in items))


def _dem_matches_before_5409(derived, committed, rtol=1e-9, atol=1e-12):
    """dem_matches as it stood before the fast path: the oracle."""
    da = list(derived.flattened())
    ca = list(committed.flattened())
    if len(da) != len(ca):
        return False
    for x, y in zip(da, ca):
        if x.type != y.type:
            return False
        if [str(t) for t in x.targets_copy()] != \
           [str(t) for t in y.targets_copy()]:
            return False
        ax, ay = x.args_copy(), y.args_copy()
        if len(ax) != len(ay) or any(
                abs(a - b) > rtol * max(abs(a), abs(b)) + atol
                for a, b in zip(ax, ay)):
            return False
    return True


def _perturbed(rng, items):
    """`items` with one thing changed, and the name of the change."""
    out = [[name, tag, list(args), list(toks)]
           for name, tag, args, toks in items]
    errors = [row for row in out if row[0] == "error"]
    kind = rng.choice(["none", "ulp", "rate", "target", "reorder", "drop",
                       "swap_lines", "tag", "type", "extra", "separator"])
    row = rng.choice(errors) if errors else None
    toks = row[3] if row else []
    if row is None:
        kind = "none" if kind not in ("swap_lines", "type", "extra") else kind
    elif kind == "ulp":
        row[2][0] *= 1 + 3e-13
    elif kind == "rate":
        row[2][0] *= 1 + 1e-6
    elif kind == "target" and toks:
        j = rng.choice([j for j, t in enumerate(toks) if t != "^"])
        toks[j] = toks[j][0] + str(int(toks[j][1:]) + 1)
    elif kind == "reorder" and toks and "^" not in toks:
        row[3] = toks[1:] + toks[:1]
    elif kind == "drop" and toks and "^" not in toks:
        del toks[rng.randrange(len(toks))]
    elif kind == "separator":
        row[3] = [t for t in toks if t != "^"]
    elif kind == "tag":
        row[1] = "" if row[1] else "added"
    if kind == "swap_lines" and len(out) > 1:
        j = rng.randrange(len(out) - 1)
        out[j], out[j + 1] = out[j + 1], out[j]
    elif kind == "type":
        other = rng.choice(out)
        if other[0] == "detector":
            other[0], other[2], other[3] = "logical_observable", [], ["L1"]
        elif other[0] == "logical_observable":
            other[0], other[3] = "detector", ["D1"]
    elif kind == "extra":
        out.append(["error", "", [0.125], ["D2"]])
    if out == [[name, tag, list(args), list(toks)]
               for name, tag, args, toks in items]:
        kind = "none"                # the row drawn had nothing to change
    return out, kind


def test_dem_matches_decides_as_the_slow_comparison_did():
    """The fast path may only skip work: on every pair, including pairs that
    differ in one target, one rate, one line's position or one tag, the
    verdict is the one the target-by-target string comparison reached."""
    import random
    rng = random.Random(5409)
    verdicts = {}
    for case in range(600):
        items = _dem_items(rng, tags=case % 3 == 0)
        other, kind = _perturbed(rng, items)
        a, b = _dem(items), _dem(other)
        want = _dem_matches_before_5409(a, b)
        assert ct.dem_matches(a, b) == want, (kind, items, other)
        assert ct.dem_matches(b, a) == _dem_matches_before_5409(b, a)
        verdicts.setdefault(kind, set()).add(want)
    # the generator must have produced both outcomes, or this proves nothing
    assert verdicts["none"] == {True} and verdicts["ulp"] == {True}, verdicts
    assert verdicts["tag"] == {True}, verdicts
    for kind in ("rate", "target", "extra", "drop", "separator", "type"):
        assert verdicts[kind] == {False}, (kind, verdicts)
    for kind in ("reorder", "swap_lines"):     # equal neighbours may swap
        assert False in verdicts[kind], (kind, verdicts)


def test_dem_matches_looks_past_the_instructions_that_are_equal():
    """A difference after a run of exactly equal instructions is still found,
    and a difference stim's equality sees but the comparison never read (a
    tag) still is not one."""
    a = stim.DetectorErrorModel("""
        error(0.001) D0 D1
        error(0.0044999999999999) D1 D2 L0
        error(0.001) D2 D3
        detector(1, 2) D3
    """)
    same = "error(0.001) D0 D1\nerror(0.0045000000000001) D1 D2 L0\n"
    assert ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 D3\ndetector(1, 2) D3"))
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 D4\ndetector(1, 2) D3"))      # last error
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 D3\ndetector(1, 2) D4"))      # last line
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D3 D2\ndetector(1, 2) D3"))      # target order
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 L3\ndetector(1, 2) D3"))      # D3 is not L3
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 ^ D3\ndetector(1, 2) D3"))    # a separator
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.002) D2 D3\ndetector(1, 2) D3"))      # the rate
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 D3\ndetector(1, 3) D3"))      # a coordinate
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 D3\ndetector(1) D3"))         # one fewer
    assert not ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error(0.001) D2 D3\nlogical_observable L3"))  # the type
    assert ct.dem_matches(a, stim.DetectorErrorModel(
        same + "error[tag](0.001) D2 D3\ndetector(1, 2) D3"))
    # same targets and the same argument under another instruction type
    assert not ct.dem_matches(
        stim.DetectorErrorModel("error(0.001) D0\nerror(0.5) D3"),
        stim.DetectorErrorModel("error(0.001) D0\ndetector(0.5) D3"))


def test_given_columns_change_no_verdict():
    """dem_lint and witness_errors take the columns the caller already read;
    with them or without, the answer is the same list."""
    import random
    rng = random.Random(54090)
    seen = set()
    for _ in range(200):
        dem = _dem(_dem_items(rng))
        cols = ct.dem_columns(dem)
        lint = ct.dem_lint(dem)
        assert ct.dem_lint(dem, cols) == lint
        seen.add(bool(lint))
        for _ in range(4):
            k = rng.randint(0, min(3, len(cols)))
            wit = sorted(rng.sample(range(len(cols) + 1), k))
            if rng.random() < 0.2:
                wit = wit[::-1]
            value = k + rng.choice([0, 0, 1])
            plain = ct.witness_errors(dem, wit, value)
            assert ct.witness_errors(dem, wit, value, cols) == plain
            seen.add(tuple(e.split()[1] for e in plain))
    assert seen >= {True, False, ()}, seen     # clean and failing, both ways
    dem = stim.DetectorErrorModel("error(0.1) D0 L0\nerror(0.1) D0")
    assert ct.witness_errors(dem, [0, 1], 2, ct.dem_columns(dem)) == []


def test_the_mechanisms_are_walked_once_per_basis(seed, monkeypatch):
    """verify_circuit reads the columns of each derived DEM once and hands
    them to the lint and to the witness check (issue #5409: each used to
    read them again)."""
    doc, cdir = seed
    walks = []
    real = ct.dem_columns
    monkeypatch.setattr(ct, "dem_columns",
                        lambda dem: walks.append(dem.num_errors) or real(dem))
    rep = cv.verify_circuit(doc, cdir)
    assert rep["ok"], [c for c in rep["checks"] if not c["ok"]]
    assert len(walks) == 2, walks


def test_columns_read_from_text_are_the_columns():
    """dem_columns reads the text stim prints for the flattened model. The
    walk over stim's objects is the definition, and the two agree on every
    form a model can take, repeat blocks and detector shifts included; a
    tagged error is left to the walk."""
    import random
    rng = random.Random(54091)
    read = declined = 0
    for case in range(400):
        items = _dem_items(rng, tags=case % 4 == 0)
        dem = _dem(items)
        if case % 5 == 0:
            dem = stim.DetectorErrorModel(
                f"repeat 3 {{\n{dem}\nshift_detectors 7\n}}\n{dem}")
        flat = dem.flattened()
        want = ct._columns_from_instructions(flat)
        assert len(want) == flat.num_errors
        assert ct.dem_columns(dem) == want, items
        text = ct._columns_from_text(flat)
        if any(name == "error" and tag for name, tag, _, _ in items):
            assert text is None, items
            declined += 1
        else:
            assert text == want, items
            read += 1
    assert read > 200 and declined > 40, (read, declined)


class _Printed:
    """Stands in for a flattened DEM that prints as the given text."""

    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


def test_text_reader_declines_a_line_it_cannot_read():
    assert ct._columns_from_text(_Printed(
        "error(0.1) D0 ^ L1 D2\ndetector(1, 2) D5\nerror(0.5)\n"
        "logical_observable L0\nerror(0.25) L2 L2")) == [
            ([0, 2], [1]), ([], []), ([], [2, 2])]
    for text in ("error[t](0.1) D0",          # a tag
                 "error D0",                  # no argument
                 "error(0.1 D0",              # no closing parenthesis
                 "error(0.1) D0 X3",          # another kind of target
                 "error(0.1) D0 rec[-1]",
                 "error(0.1) D0 ^^",
                 "error(0.1) D0 Dx",          # not an index
                 "error(0.1) D0 D",
                 "error(0.1) L1.5"):
        assert ct._columns_from_text(_Printed(text)) is None, text
        assert ct._columns_from_text(_Printed(
            "error(0.1) D0\n" + text + "\nerror(0.1) D1")) is None, text


def test_dem_columns_falls_back_to_the_walk(monkeypatch):
    """Whatever the text reader returns, dem_columns answers with the
    columns: a refusal, or a column count stim does not confirm, sends it to
    the walk over stim's objects."""
    dem = stim.DetectorErrorModel(
        "error(0.1) D0 L0\nerror(0.2) D1 ^ D2\ndetector D3")
    want = [([0], [0]), ([1, 2], [])]
    assert ct.dem_columns(dem) == want
    for wrong in (None, [], want[:1], want + [([9], [])]):
        with monkeypatch.context() as m:
            m.setattr(ct, "_columns_from_text", lambda flat, w=wrong: w)
            assert ct.dem_columns(dem) == want, wrong
    # text that looks like DEM inside a tag adds no column and hides none
    tagged = stim.DetectorErrorModel(
        "error[x\\nerror(0.5) L1](0.1) D0 L0\nerror(0.2) D1")
    assert ct._columns_from_text(tagged.flattened()) is None
    assert ct.dem_columns(tagged) == [([0], [0]), ([1], [])]
    quiet = stim.DetectorErrorModel(
        "detector[x\\nerror(0.5) L1] D0\nerror(0.2) D1")
    assert ct._columns_from_text(quiet.flattened()) == [([1], [])]
    assert ct.dem_columns(quiet) == [([1], [])]


def test_dem_columns_reads_plain_models_from_text(monkeypatch):
    """The point of the text reader is that the walk does not run: on a model
    without tags, which every derived DEM of a canonical circuit is, the walk
    is never reached."""
    def walk(flat):
        raise AssertionError("the object walk ran on a plain model")
    monkeypatch.setattr(ct, "_columns_from_instructions", walk)
    HX = _matrix(BASE_DOC["checks"]["X"], N)
    HZ = _matrix(BASE_DOC["checks"]["Z"], N)
    dem = ct.derive_dem(ct.apply_noise(
        ct.build_css_memory(HX, HZ, rounds=2, basis="Z"), N))
    cols = ct.dem_columns(dem)
    assert len(cols) == dem.num_errors > 100
    H, L = ct.dem_matrices(dem)
    assert H.shape == (dem.num_detectors, len(cols))
    assert all(sorted(H[:, j].nonzero()[0]) == sorted(set(ds))
               for j, (ds, _) in enumerate(cols))
