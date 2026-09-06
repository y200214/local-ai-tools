"""Stable legacy entry points; implementation lives in a domain package."""

import importlib
import runpy
import sys


def expose(module_name: str, namespace: dict) -> None:
    legacy_name = namespace["__name__"]
    if legacy_name == "__main__":
        runpy.run_module(module_name, run_name="__main__")
        return
    implementation = importlib.import_module(module_name)
    # Keep old and new imports identical, including monkeypatches and module state.
    namespace.update(vars(implementation))
    sys.modules[legacy_name] = implementation
