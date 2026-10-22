"""The attack lab: every "beyond one prompt" result, gathered from real runs.

Runs the guided demo, the MCP / tool-poisoning scenarios, the multi-turn attacks and
the obfuscation evaluation, offline and deterministic, and returns them in one
document that the web page (and the landing page's headline numbers) are built from.
Nothing here is typed in by hand: change an attack or a defence and the page changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


def run_lab(attacks_path: Path = Path("datasets/security/attacks.yaml"),
            base_dir: Optional[Path] = None, seed: int = 7) -> Dict[str, Any]:
    from ragprobe.demo import run_demo
    from ragprobe.security.detector import get_detector
    from ragprobe.security.mcp import run_mcp
    from ragprobe.security.multiturn import run_multiturn
    from ragprobe.security.obfuscation import evaluate

    demo = run_demo(Path(attacks_path), base_dir=base_dir, seed=seed)
    mcp = run_mcp(["none", "detector", "tool-policy", "layered"], seed=seed)
    multiturn = run_multiturn(["none", "detector", "layered"], seed=seed)
    obfuscation = evaluate(get_detector("heuristic"))
    return {"kind": "lab", "demo": demo, "mcp": mcp, "multiturn": multiturn,
            "obfuscation": obfuscation, "facts": facts(demo, mcp, multiturn, obfuscation)}


def facts(demo: Dict[str, Any], mcp: Dict[str, Any], multiturn: Dict[str, Any],
          obfuscation: Dict[str, Any]) -> Dict[str, Any]:
    """The few headline numbers the landing page quotes."""
    stages = demo["stages"]
    rows = {r["obfuscation"]: r for r in obfuscation["rows"]}
    zero = rows.get("zero-width", {})
    return {
        "demo_grade_before": stages[0]["grade"], "demo_grade_after": stages[-1]["grade"],
        "demo_asr_before": stages[0]["asr"], "demo_asr_after": stages[-1]["asr"],
        "mcp_undefended": mcp["by_defense"]["none"]["asr"],
        "mcp_policy": mcp["by_defense"]["tool-policy"]["asr"],
        "multiturn_undefended": multiturn["by_defense"]["none"]["asr"],
        "multiturn_layered": multiturn["by_defense"]["layered"]["asr"],
        "obfuscation_raw": zero.get("recall_raw"),
        "obfuscation_normalized": zero.get("recall_normalized"),
    }
