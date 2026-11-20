import json

import check_orphans


def make_tree(
    tmp_path, *, with_code=True, with_circuits=True, circuit_block=False, stray_repro_dir=False, stray_repro_file=False
):
    root = tmp_path
    (root / "codes").mkdir(exist_ok=True)
    (root / "circuits").mkdir(exist_ok=True)
    if with_code:
        doc = {"provenance": {"authors": ["@a"]}}
        if circuit_block:
            doc["circuit"] = {"stim_version": "1.0"}
        (root / "codes" / "old.json").write_text(json.dumps(doc))
    if with_circuits:
        cdir = root / "circuits" / "old"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "memory_x.stim").write_text("# x\n")
        (cdir / "memory_z.stim").write_text("# z\n")
    if stray_repro_dir:
        (root / "repro" / "old").mkdir(parents=True, exist_ok=True)
    if stray_repro_file:
        (root / "repro").mkdir(exist_ok=True)
        (root / "repro" / "stray.txt").write_text("x")
    return root


def test_clean_tree(tmp_path):
    root = make_tree(tmp_path, with_code=True, with_circuits=True)
    assert check_orphans.audit(str(root), quiet=True) == 0


def test_orphaned_circuits_dir(tmp_path):
    root = make_tree(tmp_path, with_code=False, with_circuits=True)
    assert check_orphans.audit(str(root), quiet=True) == 1


def test_missing_circuits_for_circuit_tier(tmp_path):
    root = make_tree(tmp_path, with_code=True, with_circuits=False, circuit_block=True)
    assert check_orphans.audit(str(root), quiet=True) == 1


def test_missing_stim_file(tmp_path):
    root = make_tree(tmp_path, with_code=True, with_circuits=True, circuit_block=True)
    (root / "circuits" / "old" / "memory_z.stim").unlink()
    assert check_orphans.audit(str(root), quiet=True) == 1


def test_stray_repro_directory(tmp_path):
    root = make_tree(tmp_path, stray_repro_dir=True)
    assert check_orphans.audit(str(root), quiet=True) == 1


def test_stray_repro_file(tmp_path):
    root = make_tree(tmp_path, stray_repro_file=True)
    assert check_orphans.audit(str(root), quiet=True) == 1
