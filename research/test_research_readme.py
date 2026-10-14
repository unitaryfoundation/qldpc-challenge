"""research/README.md is the map of the top-level scripts (issue #3383): a new one must be listed."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "README.md"), encoding="utf-8") as f:
    README = f.read()


def test_every_top_level_script_is_in_the_manifest():
    scripts = sorted(f for f in os.listdir(HERE)
                     if f.endswith(".py") and not f.startswith(("test_", "_")))
    missing = [s for s in scripts if f"`{s}`" not in README]
    assert not missing, f"add to research/README.md: {missing}"


def test_the_manifest_names_no_script_that_is_gone():
    named = set(re.findall(r"`([A-Za-z0-9_]+\.py)`", README))
    gone = sorted(s for s in named if not os.path.exists(os.path.join(HERE, s)))
    assert not gone, gone
