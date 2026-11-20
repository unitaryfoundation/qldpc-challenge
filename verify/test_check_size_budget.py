import check_size_budget


def test_clean_small_tree(tmp_path):
    (tmp_path / "circuits" / "x").mkdir(parents=True)
    (tmp_path / "circuits" / "x" / "memory_x.stim").write_text("x")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text("y")
    assert check_size_budget.audit(str(tmp_path), quiet=True) == 0


def test_oversized_file(tmp_path):
    (tmp_path / "circuits").mkdir()
    big = tmp_path / "circuits" / "huge.stim"
    big.write_bytes(b"x" * (check_size_budget.MAX_CIRCUIT_FILE_BYTES + 1))
    assert check_size_budget.audit(str(tmp_path), quiet=True) == 1


def test_circuits_budget_exceeded(tmp_path, monkeypatch):
    (tmp_path / "circuits").mkdir()
    # Force a tiny budget.
    monkeypatch.setattr(check_size_budget, "CIRCUITS_BUDGET_BYTES", 1)
    (tmp_path / "circuits" / "a.stim").write_text("xx")
    assert check_size_budget.audit(str(tmp_path), quiet=True) == 1
