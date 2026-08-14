# Examples

This directory contains folderized pyCircuit examples.

## Layout contract

Each example case `X` is a folder:
- `X/X.py`: design, defining a top-level `build` entrypoint in one of two forms:
  - cycle-aware: `def build(m: CycleAwareCircuit, domain: CycleAwareDomain, ...)`
  - classic: `@module def build(m: Circuit, ...)`
- `X/tb_X.py`: testbench (`@testbench def tb(...)`)
- `X/X_config.py`: default params + TB presets + `SIM_TIER`

`X/X.py` must also set `build.__pycircuit_name__ = "X"`.

`flows/tools/discover_examples.py` classifies entrypoints by parsing the AST, using
the same signature test as `pycircuit.cli`. Discovering zero cases is an error, not
an empty run: keep the two in sync when the authoring surface changes.

A directory that intentionally sits outside this contract (for example a C-API demo
driven by its own harness) must declare itself with a `.pyc-example-exempt` file
stating the reason. Anything else that defines a `build` entrypoint outside the
folderized layout fails discovery.

## Smoke checks

Compiler smoke (`emit + pycc`):

```bash
bash flows/scripts/run_examples.sh
```

Simulation smoke (strict normal-tier examples, C++ + Verilator):

```bash
bash flows/scripts/run_sims.sh
```

Nightly simulation smoke (normal + heavy tiers):

```bash
bash flows/scripts/run_sims_nightly.sh
```

Semantic closure lane (v4.0 deferred-decision regressions):

```bash
bash flows/scripts/run_semantic_regressions_v40.sh
```

## Refresh Procedure (pyc4.0)

Use a single run-id to refresh compile/sim evidence and decision coverage artifacts:

```bash
RUN_ID=20260303-pyc40-refresh
PYC_GATE_RUN_ID="${RUN_ID}" \
PYC_DECISION_STATUS_STRICT=1 \
bash flows/scripts/run_examples.sh
```

Strict decision coverage can also be invoked directly:

```bash
python3 flows/tools/check_decision_status.py \
  --status docs/gates/decision_status_v40.md \
  --out .pycircuit_out/gates/${RUN_ID}/decision_status_report.json \
  --require-no-deferred \
  --require-all-verified \
  --require-concrete-evidence \
  --require-existing-evidence
```

## Semantic smoke examples (v4.0)

- `xz_value_model_smoke`: validates v3 trace value payload (`value`, `known`, `z`) emission.
- `reset_invalidate_order_smoke`: validates reset/invalidate ordering in trace events.
- `net_resolution_depth_smoke`: validates hierarchical combinational depth propagation in a simple chain.

## Artifact policy

Generated artifacts are local-only and written under:
- `.pycircuit_out/`

They are intentionally not checked into git.

## Linx/board-related designs

Linx CPU / LinxCore / board bring-up examples are kept under `contrib/` and are
not part of the core example smoke gates.
