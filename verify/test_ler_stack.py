"""The LER-stack list in verify.yml must be the import closure of ler_verify.

verify.yml re-measures every circuit.ler claim on the board when a PR or a
merge touches the stack that measures one, and runs the cheaper --ler-base
pass otherwise. The stack is listed by hand in the verify job's LER_STACK env
(the measured-rate tier of verify_all.py, ler_verify.py and what it imports,
the accelerator build, the decoder pin, and the dependency pins), and the list
and the imports live in different files. This pins the two together: a new
import in the LER code fails here until the list names it, and a module the
LER code stopped importing fails here until the list drops it.
"""

import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "verify.yml")

# The measured-rate tier's entry point, and the orchestrator that calls it.
_ENTRY = "ler_verify"
_ORCHESTRATOR = "verify/verify_all.py"
# An imported name with no verify/<name>.py behind it: the optional C++
# accelerator and the files `make fast` builds it from.
_BUILT = {"gf2_fast": ("verify/gf2_fast.cpp", "verify/setup_gf2_fast.py")}
# What can change a measurement without being imported: the decoder pin that
# ler_tools mirrors, the dependency pins, and the accelerator build recipe.
_FIXED = ("decode", "pyproject.toml", "uv.lock", "Makefile")


def imported_names(path):
    """Return the top-level module names a Python file imports anywhere in its text."""
    names = set()
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line.startswith("import "):
                for part in line[len("import "):].split(","):
                    names.add(part.split(" as ")[0].strip().split(".")[0])
            elif line.startswith("from "):
                names.add(line.split()[1].split(".")[0])
    return {n for n in names if n}


def ler_stack_files():
    """Return the verify/ files reachable by import from ler_verify, plus the accelerator sources."""
    seen, todo, files = set(), [_ENTRY], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join(_HERE, name + ".py")
        if os.path.isfile(path):
            files.add("verify/" + name + ".py")
            todo.extend(imported_names(path))
        elif name in _BUILT:
            files.update(_BUILT[name])
    return files


def workflow_ler_stack():
    """Return the LER_STACK entries of the verify workflow and the workflow text."""
    with open(_WORKFLOW, encoding="utf-8") as f:
        text = f.read()
    match = re.search(r"^\s+LER_STACK:\s*(.+?)\s*$", text, re.M)
    assert match, f"{_WORKFLOW}: no LER_STACK env entry; update this test"
    return match.group(1).split(), text


def test_the_workflow_list_is_the_import_closure():
    listed, _ = workflow_ler_stack()
    expected = ler_stack_files() | {_ORCHESTRATOR} | set(_FIXED)
    assert set(listed) == expected, (
        f"LER_STACK in .github/workflows/verify.yml lists {sorted(set(listed) - expected)} that the "
        f"LER code does not import and misses {sorted(expected - set(listed))} that it does; update "
        f"the list and re-pin verify/validator_manifest.json, which hashes that workflow."
    )
    assert len(listed) == len(set(listed)), f"LER_STACK repeats an entry: {listed}"


def test_both_diff_rules_read_the_list():
    _, text = workflow_ler_stack()
    assert text.count('...HEAD -- $LER_STACK; then') == 2, (
        "the pull_request and push diff rules in verify.yml must both diff against $LER_STACK"
    )


def test_the_closure_is_the_measuring_code_only():
    files = ler_stack_files()
    assert {"verify/ler_verify.py", "verify/ler_tools.py", "verify/circuit_tools.py", "verify/gf2.py"} <= files
    assert files.isdisjoint({"verify/qldpc_verify.py", "verify/circuit_verify.py", "verify/gate_changed.py"})
    for path in files:
        assert os.path.isfile(os.path.join(_ROOT, path)), path
