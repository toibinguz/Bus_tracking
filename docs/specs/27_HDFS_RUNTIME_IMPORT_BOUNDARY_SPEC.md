# SPEC-27: HDFS runtime import boundary

**Status:** proposed.  This is a narrow prerequisite for SPEC-25 P1/P2.

## 1. Decision

The HDFS/Spark runtime shall use the standard Apache Spark image with the
repository mounted read-only.  It shall **not** install `pandas`, `pyarrow`, or
other legacy local-lakehouse dependencies merely to import the WebHDFS client.

The only permitted code change is a lazy public-export boundary in
`module_2_big_data_storage_and_lakehouse/__init__.py`.  Importing a concrete
submodule such as
`module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.webhdfs` must
not import any of the following legacy modules:

```text
step_2_2_parquet_medallion_lakehouse.lakehouse_exporter
step_2_2_parquet_medallion_lakehouse.silver_lakehouse_auditor
step_2_1_sqlite_operational_store.db_manager
```

Existing top-level public names (`OperationalDatabaseManager`, both export
functions, and `audit_silver`) remain supported.  They may be resolved lazily
only when requested.  No behavior within the legacy modules is changed.

## 2. Rationale and rejected alternative

The import failure is caused by the package initializer, not by WebHDFS or
Spark.  Installing the complete local analytics stack into the Spark image
would obscure that boundary, enlarge the distributed runtime, and couple P1
to frozen legacy exports.  A new project-specific image is deferred unless a
future Spark transform explicitly needs a dependency absent from the standard
image.

This decision does not allow a local-directory substitute for HDFS, nor does
it make the local Parquet exporter a distributed processing dependency.

## 3. Required interface behavior

1. The package initializer must define no eager imports of the three modules
   above.
2. `from module_2_big_data_storage_and_lakehouse import <existing_public_name>`
   must preserve the current public API and resolve its owning module only for
   that requested name.
3. Unknown attributes retain normal `AttributeError` behavior.
4. P1 uploader code imports its concrete `step_2_4_hdfs_history` modules; it
   must not rely on a legacy top-level export.
5. The Compose mount remains read-only and the Spark image must not receive a
   hidden `pip install` step for local-lakehouse packages.

## 4. Acceptance evidence

All checks are required before P1 is accepted:

| ID | Evidence |
| --- | --- |
| IM-01 | A unit test starts a fresh Python interpreter, imports the WebHDFS concrete module, and proves the three legacy module names and `pandas` are absent from `sys.modules`. |
| IM-02 | In the existing host test environment, each existing top-level public export remains importable and resolves to its prior owner. |
| IM-03 | `docker compose -f docker-compose.hdfs.yml exec spark-master` runs the IM-01 import probe successfully with `/workspace` as its source path. |
| IM-04 | P1 uploads a closed spool object to WebHDFS after IM-03; its receipt and remote SHA-256 match. |
| IM-05 | Image history/Dockerfile and Compose config show no installation of `pandas`/`pyarrow` into the Spark image and no writable project mount. |

An import workaround that catches `ImportError`, changes `sys.path` to a local
copy, or conditionally switches storage is a failure.

## 5. Follow-on boundary

Spark P2 may add only dependencies that are directly needed by its specified
distributed transform, with a separate spec naming the package, image change,
and reproduction command.  Such a decision cannot be bundled into this
import-boundary fix.
