"""Regression guards for folderized example discovery.

Discovery once classified designs by grepping for the string ``@module``. After the
cycle-aware (V5) rewrite no example carried that string any more, so discovery
returned zero cases *and exit code 0* -- which silently emptied the example loops in
`run_examples.sh`, `run_sims.sh`, and `run_sims_nightly.sh`. These tests pin down the
two properties that failure violated: entrypoint classification must follow the
compiler's dispatch, and discovering nothing must be an error.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = REPO_ROOT / "designs" / "examples"


def _load_discover():
    path = REPO_ROOT / "flows" / "tools" / "discover_examples.py"
    spec = importlib.util.spec_from_file_location("pyc_discover_examples", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


discover = _load_discover()


def _write_example(d: Path, name: str, design_src: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.py").write_text(design_src, encoding="utf-8")
    (d / f"tb_{name}.py").write_text("def tb(t):\n    pass\n", encoding="utf-8")
    (d / f"{name}_config.py").write_text('SIM_TIER = "normal"\n', encoding="utf-8")
    return d / f"{name}.py"


CYCLE_AWARE_SRC = """
def build(m, domain, width: int = 8) -> None:
    pass


build.__pycircuit_name__ = "{name}"
"""

CLASSIC_SRC = """
from pycircuit import module


@module
def build(m, width: int = 8) -> None:
    pass


build.__pycircuit_name__ = "{name}"
"""


class TestEntrypointKind:
    def test_cycle_aware_entrypoint_without_module_decorator(self, tmp_path: Path) -> None:
        # The exact shape that the old text-matching detector missed.
        p = tmp_path / "d.py"
        p.write_text("def build(m, domain, width: int = 8) -> None:\n    pass\n", encoding="utf-8")
        assert "@module" not in p.read_text(encoding="utf-8")
        assert discover.entrypoint_kind(p) == "cycle_aware"

    def test_classic_module_entrypoint(self, tmp_path: Path) -> None:
        p = tmp_path / "d.py"
        p.write_text("@module\ndef build(m, width: int = 8) -> None:\n    pass\n", encoding="utf-8")
        assert discover.entrypoint_kind(p) == "module"

    @pytest.mark.parametrize(
        "decorator",
        ["@module", "@module()", "@pycircuit.module", "@pyc.module()"],
    )
    def test_module_decorator_spellings(self, tmp_path: Path, decorator: str) -> None:
        p = tmp_path / "d.py"
        p.write_text(f"{decorator}\ndef build(m, width: int = 8) -> None:\n    pass\n", encoding="utf-8")
        assert discover.entrypoint_kind(p) == "module"

    def test_support_module_is_not_a_design(self, tmp_path: Path) -> None:
        p = tmp_path / "d.py"
        p.write_text("def helper(m, domain):\n    pass\n", encoding="utf-8")
        assert discover.entrypoint_kind(p) is None

    def test_second_parameter_must_be_named_domain(self, tmp_path: Path) -> None:
        p = tmp_path / "d.py"
        p.write_text("def build(m, width: int = 8) -> None:\n    pass\n", encoding="utf-8")
        assert discover.entrypoint_kind(p) is None

    def test_unparseable_file_is_not_a_design(self, tmp_path: Path) -> None:
        p = tmp_path / "d.py"
        p.write_text("def build(m, domain:\n", encoding="utf-8")
        assert discover.entrypoint_kind(p) is None

    def test_agrees_with_cli_dispatch(self) -> None:
        # Discovery must classify exactly what `pycircuit.cli` knows how to compile.
        cli = pytest.importorskip("pycircuit.cli")

        def cycle_aware(m, domain, width=8):
            pass

        def classic(m, width=8):
            pass

        assert cli.is_cycle_aware_entrypoint(cycle_aware) is True
        assert cli.is_cycle_aware_entrypoint(classic) is False


class TestDiscovery:
    def test_repo_examples_are_discovered(self) -> None:
        # The original bug: zero cases reported as success.
        cases = discover._discover(EXAMPLES_ROOT)
        assert cases, "no examples discovered; the layout contract drifted from the compiler"

    def test_every_conforming_directory_is_discovered(self) -> None:
        exempt = discover._exempt_dirs(EXAMPLES_ROOT)
        expected = {
            d.name
            for d in EXAMPLES_ROOT.iterdir()
            if d.is_dir()
            and not discover._is_exempt(d, exempt)
            and (d / f"{d.name}.py").is_file()
            and (d / f"tb_{d.name}.py").is_file()
            and (d / f"{d.name}_config.py").is_file()
        }
        found = {c.name for c in discover._discover(EXAMPLES_ROOT)}
        assert found == expected

    def test_every_discovered_design_is_classifiable(self) -> None:
        for c in discover._discover(EXAMPLES_ROOT):
            assert discover.entrypoint_kind(c.design) is not None, c.design

    def test_cycle_aware_folder_is_discovered(self, tmp_path: Path) -> None:
        _write_example(tmp_path / "toy", "toy", CYCLE_AWARE_SRC.format(name="toy"))
        assert [c.name for c in discover._discover(tmp_path)] == ["toy"]

    def test_classic_folder_is_discovered(self, tmp_path: Path) -> None:
        _write_example(tmp_path / "toy", "toy", CLASSIC_SRC.format(name="toy"))
        assert [c.name for c in discover._discover(tmp_path)] == ["toy"]

    def test_stray_design_outside_folder_layout_fails(self, tmp_path: Path) -> None:
        _write_example(tmp_path / "toy", "toy", CYCLE_AWARE_SRC.format(name="toy"))
        (tmp_path / "loose.py").write_text("def build(m, domain):\n    pass\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="outside required folderized layout"):
            discover._discover(tmp_path)

    def test_exempt_marker_excuses_a_directory(self, tmp_path: Path) -> None:
        _write_example(tmp_path / "toy", "toy", CYCLE_AWARE_SRC.format(name="toy"))
        demo = tmp_path / "demo"
        demo.mkdir()
        (demo / "demo.py").write_text("def build(m, domain):\n    pass\n", encoding="utf-8")
        (demo / discover.EXEMPT_MARKER).write_text("C-API demo, not a gate case.\n", encoding="utf-8")
        assert [c.name for c in discover._discover(tmp_path)] == ["toy"]

    def test_exempt_marker_requires_a_reason(self, tmp_path: Path) -> None:
        _write_example(tmp_path / "toy", "toy", CYCLE_AWARE_SRC.format(name="toy"))
        demo = tmp_path / "demo"
        demo.mkdir()
        (demo / "demo.py").write_text("def build(m, domain):\n    pass\n", encoding="utf-8")
        (demo / discover.EXEMPT_MARKER).write_text("   \n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="must state why"):
            discover._discover(tmp_path)


class TestCliContract:
    def test_empty_root_is_an_error_not_success(self, tmp_path: Path, capsys) -> None:
        rc = discover.main(["--root", str(tmp_path), "--format", "tsv"])
        assert rc == 1
        assert "expected at least" in capsys.readouterr().err

    def test_min_cases_can_be_relaxed_explicitly(self, tmp_path: Path) -> None:
        assert discover.main(["--root", str(tmp_path), "--format", "tsv", "--min-cases", "0"]) == 0

    def test_repo_examples_exit_zero(self) -> None:
        assert discover.main(["--root", str(EXAMPLES_ROOT), "--format", "tsv"]) == 0

    def test_heavy_tier_filter_does_not_trip_min_cases(self) -> None:
        # min-cases applies to discovery, not to the tier filter: an empty tier is legal.
        assert discover.main(["--root", str(EXAMPLES_ROOT), "--tier", "heavy", "--format", "tsv"]) == 0
