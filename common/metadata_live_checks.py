"""Strict adapters for Calibre's live metadata tests (maintainer tools only)."""

from contextlib import ExitStack
from queue import Queue
from threading import Event
from unittest.mock import patch
from typing import Any


def run_positive_identify(test_runner, plugin_name, cases):
    """Calibre can return normally after identify reports an error; fail instead."""
    with ExitStack() as patches:

        def modify_plugin(plugin):
            original = plugin.identify

            def checked_identify(*args, **kwargs):
                error = original(*args, **kwargs)
                if error is not None:
                    raise AssertionError(f"Metadata lookup failed: {error}")
                return error

            patches.enter_context(patch.object(plugin, "identify", checked_identify))

        test_runner(plugin_name, cases, modify_plugin=modify_plugin)


def assert_no_identify_match(plugin, query, log):
    """A successful, uncancelled identify with an empty queue proves no match."""
    results: Queue[Any] = Queue()
    abort = Event()
    error = plugin.identify(log, results, abort, **query)
    if error is not None:
        raise AssertionError(f"Cannot confirm no match: {error}")
    if abort.is_set():
        raise AssertionError("Cannot confirm no match: lookup was cancelled or timed out")
    if not results.empty():
        raise AssertionError("Expected no match but identify returned metadata")


def run_negative_identify(plugin_name, query):
    from calibre.customize.ui import all_metadata_plugins
    from calibre.ebooks.metadata.sources.test import init_test

    plugin = next(p for p in all_metadata_plugins() if p.name == plugin_name)
    _, _, log = init_test(plugin_name)
    assert_no_identify_match(plugin, query, log)
