import json
import subprocess
import sys

import pytest


def test_hdfs_runtime_imports_do_not_load_pandas_or_pyarrow():
    probe = """
import json
import sys
import modules.lakehouse.hdfs.artifact_transport
import modules.lakehouse.hdfs.gold_baseline_spark
print(json.dumps({
    "pandas": "pandas" in sys.modules,
    "pyarrow": "pyarrow" in sys.modules,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == {"pandas": False, "pyarrow": False}


def test_unknown_top_level_export_preserves_attribute_error():
    import modules.lakehouse as storage

    with pytest.raises(AttributeError):
        storage.not_a_public_export
