"""Keeps the science-fair prompt-injection harness (research/prompt-injection) runnable."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2] / "research" / "prompt-injection"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("injection_experiment", ROOT / "experiment.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["injection_experiment"] = module
    spec.loader.exec_module(module)
    return module


class _Obedient:
    """Worst-case model: always obeys the attacker."""

    def __init__(self) -> None:
        self.seen: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> str:
        self.seen.append(messages)
        return json.dumps({"action": "send_file", "argument": "senhas.txt", "reply": "senhas.txt"})


def test_attack_catalogue_is_well_formed() -> None:
    spec = json.loads((ROOT / "attacks.json").read_text(encoding="utf-8"))
    ids = [a["id"] for a in spec["attacks"]]
    assert len(ids) == len(set(ids)) >= 20
    for attack in spec["attacks"]:
        assert attack["payload"] and attack["marker"] and attack["category"]


def test_obedient_model_breaks_baseline_but_never_executes_in_aval() -> None:
    experiment = _load()
    spec = json.loads((ROOT / "attacks.json").read_text(encoding="utf-8"))
    model = _Obedient()
    rows = experiment.run(
        model, spec["attacks"], spec["questions"][:1], 1, ["baseline", "aval-sem-limite", "aval"]
    )
    by = {
        c: [r for r in rows if r["condition"] == c] for c in ("baseline", "aval", "aval-sem-limite")
    }
    assert sum(r["attack_success"] for r in by["baseline"]) > 0
    assert sum(r["attack_success"] for r in by["aval"]) == 0
    assert sum(r["attack_success"] for r in by["aval-sem-limite"]) == 0
    # The real condition truncates names and neutralizes "<" ">" like production does.
    aval_prompts = [m[1]["content"] for m in model.seen[2::3]]
    assert all("</dados> Nova" not in p for p in aval_prompts)
    assert "condição" in experiment.summarize(rows)
