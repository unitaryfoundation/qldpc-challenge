"""The Lean binding tool: the entry's matrices in and out of Lean literals, and the QECLean relabeling (issue #7254)."""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "formal"))

import lean_binding as L  # noqa: E402

FIXTURE = os.path.join(_HERE, "formal", "fixtures", "lean_qec_ae8bdd15.json")


def _entry(slug):
    with open(os.path.join(_ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


def _pinned():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def _lean_source(names):
    """Rebuild the pinned Lean-QEC definitions as source text."""
    fx = _pinned()["literals"]
    return "\n".join(f"def {n} : BitVec ({fx[n]['rows']} * {fx[n]['cols']}) := 0x{fx[n]['hex']}" for n in names) + "\n"


def test_encode_and_decode_are_inverse():
    rows = [[0, 3], [1], [], [2, 3]]
    v = L.encode(rows, 4)
    assert v == (1 << 0 | 1 << 3) | (1 << 5) | (1 << 14 | 1 << 15)
    assert L.decode(v, 4, 4) == rows
    with pytest.raises(ValueError):
        L.encode([[4]], 4)
    with pytest.raises(ValueError):
        L.decode(1 << 16, 4, 4)


@pytest.mark.parametrize("slug,name", [("72-12-6", "BB72"), ("144-12-12", "BB144")])
def test_the_pinned_lean_qec_literals_are_the_board_entries_row_for_row(slug, name):
    """What the 72-12-6 formal certificate's note says in a sentence, checked.

    The same binding holds for the development's BB144.
    """
    doc = _entry(slug)
    rep = L.check(doc, _lean_source([f"{name}_X", f"{name}_Z"]), name=name)
    assert rep["ok"], rep["problems"]
    assert rep["checks_sha256"] == L.checks_sha256(doc)
    if slug == "72-12-6":
        with open(os.path.join(_ROOT, "certs", "72-12-6.json"), encoding="utf-8") as f:
            cert = json.load(f)
        assert cert["verification"]["checks_sha256"] == rep["checks_sha256"]


@pytest.mark.parametrize("slug,name", [("72-12-6", "BB72"), ("144-12-12", "BB144")])
def test_emit_regenerates_the_pinned_literals_from_the_entry(slug, name):
    """The generator the fieldnote of 2026-10-04 asked for.

    The Lean definition comes from the JSON, so the two cannot drift.
    """
    fx = _pinned()["literals"]
    text = L.emit(_entry(slug), name, slug=slug)
    got = L.literals_in(text)
    for side in ("X", "Z"):
        rows, cols, value = got[f"{name}_{side}"]
        assert (rows, cols) == (fx[f"{name}_{side}"]["rows"], fx[f"{name}_{side}"]["cols"])
        assert value == int(fx[f"{name}_{side}"]["hex"], 16)
    assert f"checks_sha256 {L.checks_sha256(_entry(slug))}" in text


def test_check_names_a_tampered_literal_and_a_reordered_one():
    doc = _entry("72-12-6")
    text = L.emit(doc, "BB72")
    line = next(ln for ln in text.splitlines() if ln.startswith("def BB72_X"))
    flipped = line[:-1] + ("0" if line[-1] != "0" else "1")  # one bit of the last row
    rep = L.check(doc, text.replace(line, flipped), name="BB72")
    assert not rep["ok"] and "different X matrix" in rep["problems"][0]
    wide = text.replace("def BB72_X : BitVec (36 * 72) := 0x", "def BB72_X : BitVec (36 * 72) := 0x1")
    rep = L.check(doc, wide, name="BB72")
    assert not rep["ok"] and "bits above 36 * 72" in rep["problems"][0]
    xs, zs = L.rows_of(doc)
    swapped = L.literal("BB72_X", xs[::-1], 72) + "\n" + L.literal("BB72_Z", zs, 72)
    rep = L.check(doc, swapped, name="BB72")
    assert not rep["ok"] and "same rows in another order" in rep["problems"][0] and rep["rowspace_equal_X"] is True
    rep = L.check(doc, text, x_name="Nope_X", z_name="BB72_Z")
    assert "no literal named 'Nope_X'" in rep["problems"][0]


def test_parse_construction_reads_the_boards_bb_strings():
    assert L.parse_construction(
        "Bivariate bicycle code, orders (12, 6), A=x**3 + y**2 + y, B=x**2 + x + y**3 (periodic)."
    ) == (
        12,
        6,
        [(3, 0), (0, 2), (0, 1)],
        [(2, 0), (1, 0), (0, 3)],
    )
    assert L.parse_poly("x^7 + x^2 + 1") == [(7, 0), (2, 0), (0, 0)]
    with pytest.raises(ValueError):
        L.parse_construction("hypergraph product")


def test_the_qeclean_relabeling_carries_the_chain_complex_onto_the_gross_entry():
    """QECLean numbers qubits 2 * (a * m + b) + block and the entry block * l * m + (a * m + b).

    That permutation alone carries one onto the other: no reflection.
    """
    doc = _entry("144-12-12")
    rec = L.relabel(doc, "Gross")
    assert (rec["l"], rec["m"]) == (12, 6)
    assert rec["rows_identical"] is True and rec["rowspace_equal"] is True
    assert sorted(rec["map"]) == list(range(144)) and all(rec["inverse"][rec["map"][q]] == q for q in range(144))
    assert rec["map"][0] == 0 and rec["map"][1] == 72 and rec["map"][2] == 1
    assert "def Gross_fromQECLean : Fin 144 → Fin 144 := ![0, 72, 1, 73," in rec["lean"]
    assert "def Gross_toQECLean : Fin 144 → Fin 144 := ![" in rec["lean"]


def test_the_relabeling_also_holds_for_the_72_qubit_base_code():
    rec = L.relabel(_entry("72-12-6"), "BB72")
    assert rec["rows_identical"] is True


def test_the_command_emits_checks_and_relabels(tmp_path, capsys):
    entry = os.path.join(_ROOT, "codes", "144-12-12.json")
    out = tmp_path / "BB144.lean"
    assert L.main(["emit", entry, "--name", "BB144", "--out", str(out)]) == 0
    assert L.main(["check", entry, "--lean", str(out), "--name", "BB144"]) == 0
    assert "row for row" in capsys.readouterr().out
    other = os.path.join(_ROOT, "codes", "72-12-6.json")
    assert L.main(["check", other, "--lean", str(out), "--name", "BB144"]) == 1
    assert "is 72 x 144" in capsys.readouterr().out
    table = tmp_path / "Gross.lean"
    rec = tmp_path / "gross.json"
    assert L.main(["relabel", entry, "--name", "Gross", "--out", str(table), "--json", str(rec)]) == 0
    assert "Gross_fromQECLean" in table.read_text(encoding="utf-8")
    assert json.loads(rec.read_text(encoding="utf-8"))["rows_identical"] is True
