# SPEC-36: Spark NumPy runtime dependency for P2

**Status:** implementation directive after P1 acceptance and before P2.  
**Owner:** `@architect`  
**Scope:** Make the already-accepted SPEC-26 projection executable inside the
private Spark runtime.  This is not a new transform design.

## 1. Observed blocker

The P2 fixture, its HDFS Bronze object, and its immutable reference bundle
have been staged.  The real `spark-submit` process fails before the P2
transform because the accepted `project_route_events` boundary imports
`multi_route_projector`, which imports `numpy`, while the current
`apache/spark:3.5.4` image does not contain NumPy.

Do not solve this by copying geometry into Spark code, switching to a local
transform, or conditionally skipping projection.  Those alternatives would
invalidate SPEC-26 parity and SPEC-35's HDFS/Spark path.

## 2. Decision

Build one project-owned Spark image from the existing `apache/spark:3.5.4`
base and install exactly:

```text
numpy==1.24.4
```

The installation belongs in `infra/spark/Dockerfile` at image-build time, not
in a `spark-submit` command, an interactive container shell, or a mounted
workspace.  NumPy 1.24.4 is selected because it supports the current image's
Python 3.8 runtime.  The package is needed by the production P2 projection
itself, unlike the host-only timezone import rejected by SPEC-28.

No other Python package may be added in this change.  In particular, do not
add pandas, pyarrow, DuckDB, a second Python runtime, or a geometry fallback.

## 3. Required image boundary

The Dockerfile must:

1. retain `FROM apache/spark:3.5.4` and the existing HDFS XML copy;
2. switch to a user permitted to install Python packages only for the image
   build, then restore `USER spark`;
3. install the single pinned package with cache disabled; and
4. make the same image available to the Spark master, both workers, and the
   one-shot ingest/P2 submit service defined by Compose.

There must be no runtime `pip install`, no package download after container
start, and no dependency hidden in `/workspace`.

## 4. Reproducibility and supply-chain evidence

Before the first P2 execution, record under the timestamped P2 evidence
directory:

| Evidence | Required value |
| --- | --- |
| Dockerfile source hash | SHA-256 of `infra/spark/Dockerfile` used to build |
| Base declaration | literal `apache/spark:3.5.4` from that Dockerfile |
| Built image identity | `docker image inspect` immutable image ID/digest |
| Runtime interpreter | `python3 --version` in the Spark image |
| NumPy identity | `python3 -c "import numpy; print(numpy.__version__)"` = `1.24.4` |
| Projection probe | import `project_route_events` in the Spark image successfully |

The evidence records the exact image actually run; the tag alone is not
treated as immutable provenance.  Dependency upgrades require a separate
specification and rerun of P2 evidence.

## 5. P2 prerequisite acceptance

P2 may resume only when all of the following pass on the private cluster:

| ID | Pass condition |
| --- | --- |
| DEP-01 | Master and both workers use the rebuilt project Spark image. |
| DEP-02 | Python is the image runtime expected by the base image and NumPy reports exactly `1.24.4`. |
| DEP-03 | The accepted projection imports successfully; no SQLite/local telemetry is read during the probe. |
| DEP-04 | A submitted P2 job reaches the first declared HDFS Bronze read; a missing later transform failure is reported honestly, not replaced by a local success path. |
| DEP-05 | The recorded image/Dockerfile/package evidence is placed beside the P2 logs. |

After DEP-01--05, continue SPEC-35 unchanged.  The P2 implementation still
must prove its own Bronze-to-Silver/Gold, checkpoint, and validation criteria.
