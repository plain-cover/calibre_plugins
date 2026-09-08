"""Live checks must distinguish a completed empty lookup from an access failure."""

from types import SimpleNamespace

import pytest

from common.metadata_live_checks import assert_no_identify_match, run_positive_identify


@pytest.mark.parametrize("outcome", ["empty", "match", "error", "cancel", "exception"])
def test_negative_identify_requires_successful_empty_result(outcome):
    def identify(_log, results, abort, **_query):
        if outcome == "match":
            results.put(object())
        if outcome == "cancel":
            abort.set()
        if outcome == "exception":
            raise RecursionError("broken lookup")
        return "All search methods failed" if outcome == "error" else None

    plugin = SimpleNamespace(identify=identify)
    if outcome == "empty":
        assert_no_identify_match(plugin, {"title": "Absent"}, None)
    else:
        with pytest.raises((AssertionError, RecursionError)):
            assert_no_identify_match(plugin, {"title": "Absent"}, None)


@pytest.mark.parametrize("error", [None, "403 and browser timeout"])
def test_positive_adapter_restores_identify_across_repeated_calls(error):
    original = lambda: error
    plugin = SimpleNamespace(identify=original)

    def runner(_name, _cases, modify_plugin):
        modify_plugin(plugin)
        # Calibre's stock runner otherwise returns normally when this is an error.
        plugin.identify()

    for _ in range(5):
        if error:
            with pytest.raises(AssertionError, match="Metadata lookup failed"):
                run_positive_identify(runner, "Romance.io", [])
        else:
            run_positive_identify(runner, "Romance.io", [])
        assert plugin.identify is original
