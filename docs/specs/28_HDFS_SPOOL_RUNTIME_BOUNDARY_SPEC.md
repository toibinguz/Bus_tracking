# SPEC-28: HDFS spool runtime boundary

**Status:** proposed.  This is a narrow prerequisite to SPEC-25 P1 and follows
SPEC-27.

## 1. Decision

Do **not** replace the standard `apache/spark:3.5.4` image, install a newer
Python, or add a `backports.zoneinfo` dependency.  The failure is not a Spark
processing requirement: the Spark-container import probe imports `webhdfs`,
which currently imports the host-only spool module solely to reuse receipt and
SHA-256 helpers.  `zoneinfo` is therefore pulled in accidentally by Python
3.8, even though Spark neither creates a spool window nor derives a bus
operation date.

The implementation shall extract the timezone-free closed-artifact helpers
(`file_sha256`, `receipt_path`, `load_receipt`, and `write_receipt`) into one
private HDFS-history artifact/receipt module.  Both `spool` and `webhdfs` may
import that module.  `webhdfs` must not import `spool`; it remains executable
in the standard Spark image.  The spool module remains the **host-side** owner
of window construction, atomic close/fsync, and `ZoneInfo("Asia/Ho_Chi_Minh")`.

No second implementation of hashing or receipt writing is permitted.  Moving
the helpers must preserve their bytes, JSON keys/order, suffixes, and atomic
replace behavior.

## 2. Rationale and rejected alternatives

`zoneinfo` was introduced in Python 3.9.  Adding a new Python runtime or a
backport package to the Spark image would make a host-ingestion concern appear
to be a distributed Spark requirement, increase image drift, and violate the
minimal standard-image decision in SPEC-27.  A fixed-offset replacement is
also rejected: it would conceal timezone policy in a compatibility branch.

This is not a claim that Spark may ignore timezone policy.  Future P2 Spark
transforms must set their SQL session timezone explicitly and receive a
separate transform spec; P1's WebHDFS import does not derive `dt` or `hr`.

## 3. Required boundaries

| Runtime | Allowed responsibility | Forbidden responsibility |
| --- | --- | --- |
| Host crawler/uploader | `ZoneInfo`, `hour_partition`, atomic spool close, calling WebHDFS | Spark-local or local-directory HDFS fallback |
| Shared artifact helper | hash and receipt serialization only; no datetime/timezone imports | partition derivation or network I/O |
| Spark image | import/use WebHDFS client and later read HDFS paths | importing `spool`, relying on host Python version, installing compatibility packages |

The uploader still accepts only a closed spool path.  Its `dt=.../hr=...`
components remain created by the host spool writer; it must not recompute them.

## 4. Acceptance evidence

| ID | Required evidence |
| --- | --- |
| TZ-01 | Existing host spool tests prove the same `Asia/Ho_Chi_Minh` partition and receipt bytes before/after extraction. |
| TZ-02 | A fresh interpreter importing `webhdfs` has neither the spool module nor `zoneinfo` in `sys.modules`. |
| TZ-03 | The existing Spark-container IM-03 probe succeeds from read-only `/workspace` without installing Python packages or changing the image base. |
| TZ-04 | A host-created closed spool object uploads over real WebHDFS; local and remote SHA-256 plus receipt match (SPEC-27 IM-04). |
| TZ-05 | Tests prove the original atomic receipt write/collision behavior; `git diff --check` is clean. |

Failure of TZ-01--TZ-05 blocks P1 acceptance.  It may not be bypassed by
conditional imports, an in-module fixed timezone, or a local success path.

## 5. Follow-on P2 constraint

Before a Spark SQL transform writes Silver/Gold, its specification must name
the Spark SQL timezone and test its `dt` derivation against the canonical host
fixture.  This decision only unblocks the P1 import/upload boundary.
