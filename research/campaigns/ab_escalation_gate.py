"""A/B campaign: baseline fixed-ladder vs the escalation gate (AUTORESEARCH.md 3b).

Working output. Gitignored by the ``_*.py`` rule; state lives under
``research/candidates/ab_gate/``. Both arms screen the same BB pool with the
same seed, take the same survivors, and run the same ladder depth schedule
under the same per-candidate trial cap, each with an independent ladder:

  * ``init``       -- screen once, pick survivors, freeze the shared bar,
                      snapshot both arms.
  * ``base``       -- the 2026-09-20 behavior: chase every survivor through
                      the full ladder; stop only at the cap.
  * ``gate-next``  -- advance every pending gate candidate one rung, write
                      one brief per rung boundary for the harness (jev_decide).
  * ``gate-apply`` -- read the harness's verdict JSONs, enforce them through
                      escalation.apply_verdict, journal, advance.
  * ``report``     -- the comparison: trials spent per arm, dispositions,
                      and where each ladder first settled (the 2026-09-20
                      metric).

Nothing here judges a code: the bar is a synthetic campaign target shared by
both arms, NOT a board bar. All readings are upper bounds witnessed by found
logicals, and every rung is persisted before anything is decided.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # research/
sys.path.insert(0, os.path.join(ROOT, "kit"))

import escalation as E
from bb import build_bb
from search import sample_bb, screen, efficiency
from surrogate import distance_rand, prepare_distance_search

STATE_DIR = os.path.join(ROOT, "candidates", "ab_gate")
POOL_SPEC = dict(num=200, l_range=(3, 7), m_range=(3, 7), weight=3, seed=11,
                 n_range=(30, 130))
SCREEN_TRIALS = 800
LADDER = (2_000, 20_000, 100_000, 400_000)
CAP = sum(LADDER)
SEED = 11


def _load():
    path = os.path.join(STATE_DIR, "state.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def _eff(n, k, d):
    return round(efficiency(n, k, d), 4)


def init_pool():
    cands = list(sample_bb(**POOL_SPEC))
    recs = screen(cands, trials=SCREEN_TRIALS, seed=SEED, backend="numpy")
    # Survivors spread across the ranking, so both arms see doomed, live, and
    # borderline ladders rather than only winners.
    picks, seen = [], set()
    for r in recs[:2] + recs[len(recs) // 2 - 1: len(recs) // 2 + 1] + recs[-2:]:
        if r["fingerprint"] not in seen:
            seen.add(r["fingerprint"])
            picks.append(r)
    effs = sorted(r["efficiency"] for r in picks)
    if len(picks) < 6:
        raise SystemExit(
            f"only {len(picks)} survivors from {len(recs)} screened records -- "
            "pool too tight for a spread campaign; widen POOL_SPEC, do not "
            "proceed with a vacuous A/B")
    bar = round((effs[len(effs) // 2 - 1] + effs[len(effs) // 2]) / 2, 1)

    def snap():
        return [{"spec": r["spec"], "n": r["n"], "k": r["k"],
                 "fingerprint": r["fingerprint"],
                 "screen_eff": r["efficiency"], "screen_d": r["d"],
                 "ladder": [], "spent": 0, "disposition": "pending",
                 "level": 0, "repeats": 0, "brief_id": None}
                for r in picks]

    state = {"bar": bar, "ladder": list(LADDER), "cap": CAP,
             "pool_size": len(recs),
             "base": snap(), "gate": snap()}
    _save(state)
    print(f"pool screened: {len(recs)} unique; campaign bar={bar}")
    for c in state["base"]:
        print(f"  [[{c['n']},{c['k']},<={c['screen_d']}]] "
              f"screen_eff={c['screen_eff']} fp={c['fingerprint']}")


def _run_rung(c, trials):
    """One RIS rung; the reading is an upper bound witnessed by the logical found."""
    spec = c["spec"]
    HX, HZ = build_bb(spec["l"], spec["m"], spec["A"], spec["B"])
    prep = prepare_distance_search(HX, HZ)
    d = int(distance_rand(HX, HZ, trials=trials,
                          seed=SEED + 1000 * c["repeats"] + len(c["ladder"]) * 7919
                          + int(c["fingerprint"], 16),
                          backend="numpy", prepared=prep))
    c["ladder"].append({"trials": trials, "d": d, "fresh": True,
                        "label": f"rung{len(c['ladder'])}+{c['repeats']}r"})
    c["spent"] += trials
    return d


def _brief_for(state, c):
    rungs = [(r["trials"], r["d"], r["fresh"]) for r in c["ladder"]]
    return E.rung_brief(
        c["n"], c["k"], rungs, bar=state["bar"], family="bb",
        spec={"l": c["spec"]["l"], "m": c["spec"]["m"],
              "A": c["spec"]["A"], "B": c["spec"]["B"]},
        next_rung_trials=state["ladder"][min(c["level"], len(state["ladder"]) - 1)],
        budget_remaining=state["cap"] - c["spent"])


def arm_base():
    state = _load()
    assert state, "run init first"
    for c in state["base"]:
        if c["disposition"] != "pending":
            continue
        for trials in state["ladder"]:
            if c["spent"] >= state["cap"]:
                break
            _run_rung(c, min(trials, state["cap"] - c["spent"]))
        best = min(r["d"] for r in c["ladder"])
        above = best * best * c["k"] / c["n"] >= state["bar"]
        c["disposition"] = "above-bar" if above else "below-bar"
        print(f"base [[{c['n']},{c['k']}]] best<={best} "
              f"eff={_eff(c['n'], c['k'], best)} spent={c['spent']} "
              f"-> {c['disposition']}", flush=True)
        _save(state)
    _save(state)


def gate_next():
    state = _load()
    assert state, "run init first"
    bdir = os.path.join(STATE_DIR, "briefs")
    os.makedirs(bdir, exist_ok=True)
    n_briefs = 0
    for c in state["gate"]:
        if c["disposition"] != "pending":
            continue
        if c["spent"] >= state["cap"]:
            c["disposition"] = "exhausted"
            print(f"gate [[{c['n']},{c['k']}]] exhausted at {c['spent']}")
            continue
        trials = min(state["ladder"][c["level"]], state["cap"] - c["spent"])
        _run_rung(c, trials)
        brief = _brief_for(state, c)
        c["brief_id"] = brief["id"]
        with open(os.path.join(bdir, f"{brief['id']}.json"), "w",
                  encoding="utf-8") as f:
            json.dump(brief, f, indent=1, sort_keys=True)
        best = min(r["d"] for r in c["ladder"])
        print(f"gate [[{c['n']},{c['k']}]] rung({trials}T) best<={best} "
              f"eff={_eff(c['n'], c['k'], best)} spent={c['spent']} "
              f"brief={brief['id']}")
        n_briefs += 1
    _save(state)
    print(f"\n{n_briefs} brief(s) await jev_decide in {bdir}")


def gate_apply():
    state = _load()
    assert state, "run init first"
    jpath = os.path.join(STATE_DIR, "escalation.jsonl")
    vdir = os.path.join(STATE_DIR, "verdicts")
    acted = 0
    for c in state["gate"]:
        if c["disposition"] != "pending" or not c["brief_id"]:
            continue
        verdict = None
        vpath = os.path.join(vdir, f"{c['brief_id']}.json")
        if os.path.exists(vpath):
            with open(vpath, encoding="utf-8") as f:
                verdict = json.load(f)
        brief = _brief_for(state, c)
        assert brief["id"] == c["brief_id"], "state drifted from brief"
        d = E.apply_verdict(brief, verdict,
                            budget_remaining=state["cap"] - c["spent"])
        # Harness policy (not the verdict): a candidate that has produced 3
        # identical fresh-seed readings has a settled bound; replaying the
        # same depth again buys nothing, so the harness itself advances the
        # depth. And when the ladder ARITHMETICALLY proves the bar is
        # unreachable (bound can only fall, best already below d_needed,
        # stable across fresh seeds, nothing frontier-flagged), the harness
        # abandons on its own authority even over a Jev hold -- that fence
        # is exactly the condition under which abandoning destroys nothing.
        if (d["action"] != "abandon-ladder"
                and E._abandon_is_proven_safe(brief["facts"])
                and brief["facts"]["flat_fresh_rungs_at_best"] >= 3):
            d = dict(d, action="abandon-ladder",
                     reason=d["reason"] + "; harness: ladder proven below "
                     "bar (bound can only fall), abandoning on its own "
                     "authority")
            c["disposition"] = "abandoned"
        elif (d["action"] == "hold-deepen"
                and brief["facts"]["flat_fresh_rungs_at_best"] >= 3
                and c["level"] < len(state["ladder"]) - 1):
            d = dict(d, action="promote-next-rung",
                     reason=d["reason"] + "; harness: bound settled over "
                     "3 fresh rungs, advancing depth on its own authority")
            c["level"] = min(c["level"] + 1, len(state["ladder"]) - 1)
            c["repeats"] = 0
        elif d["action"] == "abandon-ladder":
            c["disposition"] = "abandoned"
        elif d["action"] == "promote-next-rung":
            c["level"] = min(c["level"] + 1, len(state["ladder"]) - 1)
            c["repeats"] = 0
        else:
            c["repeats"] += 1
        E.append_journal(d, brief, path=jpath)
        print(f"gate [[{c['n']},{c['k']}]] {d['action']} ({d['reason']})")
        acted += 1
    _save(state)
    print(f"{acted} decision(s) enforced")


def report():
    state = _load()
    assert state, "run init first"
    bar = state["bar"]

    def settle_rung(c):
        best = min(r["d"] for r in c["ladder"])
        return next((i for i, r in enumerate(c["ladder"]) if r["d"] == best), None)

    print(f"campaign bar (synthetic, shared): {bar}\n")
    for arm in ("base", "gate"):
        total = sum(c["spent"] for c in state[arm])
        print(f"== {arm}: {total} trials spent "
              f"(envelope {state['cap'] * len(state[arm])})")
        for c in state[arm]:
            if not c["ladder"]:
                print(f"  [[{c['n']},{c['k']}]] no rungs")
                continue
            best = min(r["d"] for r in c["ladder"])
            above = best * best * c["k"] / c["n"] >= bar
            print(f"  [[{c['n']},{c['k']}]] best<={best} "
                  f"eff={_eff(c['n'], c['k'], best)} "
                  f"{'ABOVE' if above else 'below'}-bar | {c['disposition']} "
                  f"spent={c['spent']} settled_at_rung={settle_rung(c)} "
                  f"ladder={[r['d'] for r in c['ladder']]}")
        print()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "init":
        init_pool()
    elif cmd == "base":
        arm_base()
    elif cmd == "gate-next":
        gate_next()
    elif cmd == "gate-apply":
        gate_apply()
    elif cmd == "report":
        report()
    else:
        print("usage: _ab_escalation.py init|base|gate-next|gate-apply|report")


if __name__ == "__main__":
    main()
