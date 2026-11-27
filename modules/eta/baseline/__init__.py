"""Lazy exports so Spark workers can import baseline_core without loading pandas/pyarrow."""

from importlib import import_module

_PUBLIC_EXPORTS = {
    "build_and_evaluate_baseline_matrix": (
        ".baseline_matrix_builder",
        "build_and_evaluate_baseline_matrix",
    ),
    "extract_bracketed_station_arrivals": (
        ".baseline_core",
        "extract_bracketed_station_arrivals",
    ),
}

__all__ = [
    "build_and_evaluate_baseline_matrix",
    "extract_bracketed_station_arrivals",
]


def __getattr__(name: str):
    try:
        module_name, attribute_name = _PUBLIC_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
