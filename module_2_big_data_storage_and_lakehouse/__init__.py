"""Module 2 public exports without loading optional legacy lakehouse modules."""

from importlib import import_module


_PUBLIC_EXPORTS = {
    "OperationalDatabaseManager": (
        ".step_2_1_sqlite_operational_store.db_manager",
        "OperationalDatabaseManager",
    ),
    "export_bronze_tomtom_incidents": (
        ".step_2_2_parquet_medallion_lakehouse.lakehouse_exporter",
        "export_bronze_tomtom_incidents",
    ),
    "export_to_parquet_lakehouse": (
        ".step_2_2_parquet_medallion_lakehouse.lakehouse_exporter",
        "export_to_parquet_lakehouse",
    ),
    "audit_silver": (
        ".step_2_2_parquet_medallion_lakehouse.silver_lakehouse_auditor",
        "audit_silver",
    ),
}

__all__ = [
    "OperationalDatabaseManager",
    "export_bronze_tomtom_incidents",
    "export_to_parquet_lakehouse",
    "audit_silver",
]


def __getattr__(name: str):
    """Resolve legacy public exports only when callers request them."""
    try:
        module_name, attribute_name = _PUBLIC_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
