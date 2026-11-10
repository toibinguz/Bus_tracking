# SPEC-17: Repository Directory Reconciliation

**Status:** READY FOR GOVERNANCE EXECUTION  
**Author:** `@architect`  
**Date:** 2026-11-10

## 1. Scope and evidence

This specification reconciles the repository layout with the files currently
present. It does not change application behavior or resurrect deleted legacy
tests.

Observed at audit time:

- `scripts/` contains exactly 15 operational entry points. It contains no
  `test_*` file and no legacy serving verifier.
- `experiments/` has the intended `eda/` and `hardware_gps/` partitions; the
  legacy `experiments/timbus/` directory is absent.
- `tests/` exists but has no files. No test implementation is present to move
  from `scripts/`.
- `archive/` is empty. `scratch/` has nine local files and is already ignored.
- Root `__pycache__/` exists and is ignored. `.pytest_cache/` exists and is
  ignored. Both are generated artefacts, not source.
- The former root document
  `docs/10_SPEC_DISTRIBUTED_BIG_DATA_LAKEHOUSE_HDFS_STORAGE_PLAN.md` is deleted
  while its successor is present at
  `docs/specs/10_DISTRIBUTED_HDFS_LAMBDA_STORAGE_AND_QUERY_SPEC.md`.

## 2. Decisions

| Item | Required action | Rationale |
| --- | --- | --- |
| `scripts/` | Keep unchanged. | Its observed contents match SPEC-06's operational-script allowlist. |
| `experiments/eda/`, `experiments/hardware_gps/` | Keep unchanged. | They are the completed target grouping from SPEC-06. |
| `experiments/audit_station_polyline_deviation.py` and its JSON report | Keep together at `experiments/` until a later taxonomy explicitly classifies this geometry audit. | Moving it by filename alone would be speculative. |
| `tests/` | Keep directory, but do not create placeholder tests. Assign test creation to `@blind_tester` from the active serving specs. | An empty test directory is a verification gap, not a directory-placement bug. |
| `archive/` | Remove only if the user confirms that no near-term archival workflow needs it. | It is empty; deletion is cosmetic and not required for correctness. |
| `scratch/`, root `__pycache__/`, `.pytest_cache/` | Do not commit. A coder may delete their local generated contents, but must not delete source. | These paths are already ignored and carry no repository contract. |
| `access_token_hf.txt` | Keep untracked and do not move into source or archive. Rotate/revoke it separately if it is a real credential. | `.gitignore` protects it from normal commits; credential rotation is outside directory cleanup. |
| documentation relocation | Update every internal link/index that still names the deleted root `docs/10_...` path to the existing `docs/specs/10_...` path, then stage the deletion and addition as one logical relocation. | Avoids a broken documentation navigation path. |

## 3. Required sequencing

1. `@leaf_coder`: make only the documentation-link correction and, if approved,
   remove local cache contents and the empty `archive/` directory.
2. `@blind_tester`: create black-box tests required by the active serving work
   (SPEC-16 §5), directly under `tests/`; do not recover historical TimBus or
   60-FPS tests from SPEC-06.
3. `@blind_tester`: run the resulting suite and report raw output. A passing
   result is mandatory before claiming `tests/` reconciled.
4. `@orchestrator`: review `git status --short` and confirm the DOC-10 move is
   represented as a rename/deletion-plus-addition, not an accidental loss.

## 4. Acceptance criteria

- `scripts/` contains only the 15 files listed in SPEC-06 §3.1.
- `Test-Path experiments/timbus` is `False`.
- No tracked file lives under `scratch/`, `__pycache__/`, or `.pytest_cache/`.
- No tracked Markdown link or plain-path reference targets the deleted root
  `docs/10_SPEC_DISTRIBUTED_BIG_DATA_LAKEHOUSE_HDFS_STORAGE_PLAN.md`.
- `tests/` contains only independently authored, runnable black-box tests;
  absence of tests is reported as incomplete rather than masked by placeholders.
