import json
import subprocess
import sys

import pytest


LEGACY_MODULES = {
    "module_2_big_data_storage_and_lakehouse.step_2_1_sqlite_operational_store.db_manager",
    "module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.lakehouse_exporter",
    "module_2_big_data_storage_and_lakehouse.step_2_2_parquet_medallion_lakehouse.silver_lakehouse_auditor",
}


def test_concrete_webhdfs_import_does_not_load_legacy_lakehouse_modules():
    probe = """
import json
import sys
import module_2_big_data_storage_and_lakehouse.step_2_4_hdfs_history.webhdfs
legacy = [name for name in sys.modules if name in %r]
print(json.dumps({"legacy": legacy, "pandas": "pandas" in sys.modules}))
""" % sorted(LEGACY_MODULES)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {"legacy": [], "pandas": False}


def test_existing_top_level_exports_resolve_from_their_legacy_owners():
    from module_2_big_data_storage_and_lakehouse import (
        OperationalDatabaseManager,
        audit_silver,
        export_bronze_tomtom_incidents,
        export_to_parquet_lakehouse,
    )

    assert OperationalDatabaseManager.__module__.endswith("step_2_1_sqlite_operational_store.db_manager")
    assert export_bronze_tomtom_incidents.__module__.endswith("lakehouse_exporter")
    assert export_to_parquet_lakehouse.__module__.endswith("lakehouse_exporter")
    assert audit_silver.__module__.endswith("silver_lakehouse_auditor")


def test_unknown_top_level_export_preserves_attribute_error():
    import module_2_big_data_storage_and_lakehouse as storage

    with pytest.raises(AttributeError):
        storage.not_a_public_export
