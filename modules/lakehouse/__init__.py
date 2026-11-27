"""Module 2 public exports without eagerly loading Spark or HDFS transport modules."""

from importlib import import_module


_PUBLIC_EXPORTS = {}

__all__ = []


def __getattr__(name: str):
    """Resolve public exports lazily on demand."""
    try:
        module_name, attribute_name = _PUBLIC_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
