#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path


#: Marker file declaring that a directory is outside the folderized gate contract.
#: It must carry a non-empty reason so exemptions stay reviewable instead of silent.
EXEMPT_MARKER = ".pyc-example-exempt"


@dataclass(frozen=True)
class ExampleCase:
    name: str
    design: Path
    tb: Path
    config: Path
    tier: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _exempt_dirs(root: Path) -> list[Path]:
    return sorted(p.parent for p in root.rglob(EXEMPT_MARKER) if p.is_file())


def _is_exempt(path: Path, exempt: list[Path]) -> bool:
    return any(path == d or d in path.parents for d in exempt)


def _parse_sim_tier(cfg_path: Path) -> str:
    text = cfg_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(cfg_path))
    tier = None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if isinstance(tgt, ast.Name) and tgt.id == "SIM_TIER":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    tier = node.value.value
    if tier not in {"normal", "heavy"}:
        raise RuntimeError(f"{cfg_path}: SIM_TIER must be \"normal\" or \"heavy\"")
    return str(tier)


def _parse_pyc_name(design_path: Path) -> str | None:
    text = design_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(design_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        for tgt in node.targets:
            if (
                isinstance(tgt, ast.Attribute)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "build"
                and tgt.attr == "__pycircuit_name__"
            ):
                return str(node.value.value)
    return None


def _decorator_base_name(dec: ast.expr) -> str | None:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def entrypoint_kind(path: Path) -> str | None:
    """Classify a module as a pyCircuit design entrypoint.

    Returns ``"module"`` for a classic ``@module def build(m, ...)`` design,
    ``"cycle_aware"`` for a V5 ``def build(m, domain, ...)`` design, and ``None``
    when the file defines no top-level ``build`` entrypoint. The signature test
    mirrors ``pycircuit.cli.is_cycle_aware_entrypoint`` so discovery and the
    compiler agree on what is buildable.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != "build":
            continue
        if any(_decorator_base_name(d) == "module" for d in node.decorator_list):
            return "module"
        args = node.args.args
        if len(args) >= 2 and args[1].arg == "domain":
            return "cycle_aware"
    return None


def _looks_like_design(path: Path) -> bool:
    return entrypoint_kind(path) is not None


def _discover(root: Path) -> list[ExampleCase]:
    if not root.exists():
        raise RuntimeError(f"examples root not found: {root}")

    errs: list[str] = []
    cases: list[ExampleCase] = []
    names: set[str] = set()

    exempt = _exempt_dirs(root)
    for d in exempt:
        if not (d / EXEMPT_MARKER).read_text(encoding="utf-8").strip():
            errs.append(f"{d / EXEMPT_MARKER}: must state why this directory is outside the gate contract")

    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        if d.name == "__pycache__":
            continue
        if _is_exempt(d, exempt):
            continue
        name = d.name
        design = d / f"{name}.py"
        tb = d / f"tb_{name}.py"
        cfg = d / f"{name}_config.py"

        present = [design.exists(), tb.exists(), cfg.exists()]
        # A same-named module without a `build` entrypoint is a support file, not a design.
        if design.exists() and not _looks_like_design(design):
            continue
        if any(present) and not all(present):
            errs.append(f"{d}: malformed example folder (requires {name}.py, tb_{name}.py, {name}_config.py)")
            continue
        if not all(present):
            continue

        if name in names:
            errs.append(f"{d}: duplicate example name {name!r}")
            continue
        names.add(name)

        pyc_name = _parse_pyc_name(design)
        if pyc_name != name:
            errs.append(f"{design}: build.__pycircuit_name__ must be {name!r}, got {pyc_name!r}")
            continue

        try:
            tier = _parse_sim_tier(cfg)
        except Exception as e:
            errs.append(str(e))
            continue

        cases.append(ExampleCase(name=name, design=design, tb=tb, config=cfg, tier=tier))

    # Enforce hard-break layout: every design module under examples/ must belong to a discovered case.
    case_designs = {c.design.resolve() for c in cases}
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts:
            continue
        if py.name == "__init__.py":
            continue
        if py.name.startswith("tb_") or py.name.endswith("_config.py"):
            continue
        if py.name.startswith("emulate_"):
            continue
        if _is_exempt(py.parent, exempt):
            continue
        if not _looks_like_design(py):
            continue
        if py.resolve() not in case_designs:
            errs.append(
                f"{py}: design module is outside required folderized layout "
                f"(add tb_/config files, or declare the directory with {EXEMPT_MARKER})"
            )

    if errs:
        raise RuntimeError("\n".join(errs))
    return sorted(cases, key=lambda c: c.name)


def _emit_json(cases: list[ExampleCase]) -> None:
    payload = [
        {
            "name": c.name,
            "design": str(c.design),
            "tb": str(c.tb),
            "config": str(c.config),
            "tier": c.tier,
        }
        for c in cases
    ]
    print(json.dumps(payload, indent=2, sort_keys=True))


def _emit_tsv(cases: list[ExampleCase]) -> None:
    for c in cases:
        print(f"{c.name}\t{c.design}\t{c.tb}\t{c.config}\t{c.tier}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Discover and validate folderized pyCircuit examples.")
    ap.add_argument(
        "--root",
        default=str(_repo_root() / "designs" / "examples"),
        help="Examples root directory",
    )
    ap.add_argument(
        "--tier",
        choices=["all", "normal", "heavy"],
        default="all",
        help="Filter by simulation tier",
    )
    ap.add_argument(
        "--format",
        choices=["json", "tsv"],
        default="json",
        help="Output format",
    )
    ap.add_argument(
        "--min-cases",
        type=int,
        default=1,
        help="Fail if fewer than this many examples are discovered (before tier filtering)",
    )
    ns = ap.parse_args(argv)

    root = Path(ns.root).resolve()
    try:
        cases = _discover(root)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Discovering nothing means the layout contract drifted away from the compiler,
    # not that there is nothing to test. Never let that pass as success.
    if len(cases) < int(ns.min_cases):
        print(
            f"error: discovered {len(cases)} example(s) under {root}, expected at least {ns.min_cases}",
            file=sys.stderr,
        )
        return 1

    for d in _exempt_dirs(root):
        reason = (d / EXEMPT_MARKER).read_text(encoding="utf-8").strip().splitlines()[0]
        print(f"note: {d.relative_to(root)} exempt from example gate: {reason}", file=sys.stderr)

    if ns.tier != "all":
        cases = [c for c in cases if c.tier == ns.tier]

    if ns.format == "tsv":
        _emit_tsv(cases)
    else:
        _emit_json(cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
