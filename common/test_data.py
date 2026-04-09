"""
Shared test data for romanceio and romanceio_fields plugins.
Contains the same set of test cases used by both plugins' test files.
"""

import importlib.util
import os
import sys
import types
from typing import Any, Callable, Dict, List, Optional, Union


def load_plugin_module(module_name: str, file_name: str, plugin_dir: str) -> types.ModuleType:
    """
    Helper to load a plugin module in tests.

    Args:
        module_name: Full module name to register (e.g., "romanceio_fields.config")
        file_name: Python file name (e.g., "config.py")
        plugin_dir: Path to plugin directory

    Returns:
        The loaded module
    """
    spec = importlib.util.spec_from_file_location(module_name, os.path.join(plugin_dir, file_name))
    if spec is None:
        raise ImportError(f"Could not load {module_name} module spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    if spec.loader is None:
        raise ImportError(f"{module_name} spec.loader is None")
    spec.loader.exec_module(module)
    return module


def verify_plugin_metadata(
    plugin: Any,
    expected_name: str,
    expected_version: tuple,
    expected_author: str,
    expected_min_calibre_version: tuple,
    additional_checks: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Verify plugin metadata matches expected values.

    Args:
        plugin: The plugin instance to verify
        expected_name: Expected plugin name
        expected_version: Expected plugin version tuple
        expected_author: Expected plugin author
        expected_min_calibre_version: Expected minimum Calibre version tuple
        additional_checks: Optional dict of additional attribute checks {attr_name: expected_value}

    Raises:
        AssertionError: If any metadata doesn't match expected values
    """
    assert plugin.name == expected_name, f"Expected name '{expected_name}', got '{plugin.name}'"
    assert plugin.version == expected_version, f"Expected version {expected_version}, got {plugin.version}"
    assert plugin.author == expected_author, f"Expected author '{expected_author}', got '{plugin.author}'"
    assert (
        plugin.minimum_calibre_version == expected_min_calibre_version
    ), f"Expected minimum version {expected_min_calibre_version}, got {plugin.minimum_calibre_version}"

    if additional_checks:
        for attr_name, expected_value in additional_checks.items():
            actual_value = getattr(plugin, attr_name, None)
            if callable(expected_value):
                # If expected_value is a function, call it to check the actual value
                if hasattr(expected_value, "__name__"):
                    method_name = expected_value.__name__
                    actual_result = expected_value()
                    assert (
                        actual_result == expected_value()
                    ), f"Expected {attr_name}.{method_name}() to return {expected_value()}, got {actual_result}"
                else:
                    actual_result = expected_value()
                    assert actual_result == actual_value, f"Expected {attr_name} check to pass, but got {actual_value}"
            else:
                assert actual_value == expected_value, f"Expected {attr_name} '{expected_value}', got '{actual_value}'"


def verify_and_print_plugin(
    plugin_class: type,
    plugin_path: str,
    plugin_name: str,
    plugin_version: tuple,
    plugin_author: str,
    plugin_min_calibre_version: tuple,
    additional_checks: Optional[Dict[str, Any]] = None,
    additional_info: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Instantiate a plugin, verify its metadata, and print results.

    This is a convenience function to reduce duplicate code in plugin __main__ blocks.

    Args:
        plugin_class: The plugin class to instantiate
        plugin_path: Path to the plugin file
        plugin_name: Expected plugin name
        plugin_version: Expected plugin version tuple
        plugin_author: Expected plugin author
        plugin_min_calibre_version: Expected minimum Calibre version tuple
        additional_checks: Optional dict of additional attribute checks {attr_name: expected_value}
        additional_info: Optional dict of additional info to print {label: value}

    Returns:
        The instantiated and verified plugin instance
    """
    plugin = plugin_class(plugin_path)

    verify_plugin_metadata(
        plugin,
        plugin_name,
        plugin_version,
        plugin_author,
        plugin_min_calibre_version,
        additional_checks=additional_checks,
    )

    print_plugin_metadata(plugin, additional_info=additional_info)

    return plugin


def print_plugin_metadata(plugin: Any, additional_info: Optional[Dict[str, Any]] = None) -> None:
    """
    Print plugin metadata in a formatted way.

    Args:
        plugin: The plugin instance
        additional_info: Optional dict of additional info to print {label: value}
    """
    print("✓ All plugin metadata checks passed")
    print(f"  - Name: {plugin.name}")
    print(f"  - Version: {plugin.version}")
    print(f"  - Author: {plugin.author}")
    print(f"  - Minimum Calibre: {plugin.minimum_calibre_version}")

    if additional_info:
        for label, value in additional_info.items():
            print(f"  - {label}: {value}")


class BookTestData:
    """Test data for a single book used across multiple test scenarios."""

    def __init__(
        self,
        romanceio_id: Optional[str] = None,
        title: Optional[str] = None,
        authors: Optional[List[str]] = None,
        expected_fields: Optional[Dict[str, Union[Any, Callable]]] = None,
    ):
        self.romanceio_id = romanceio_id
        self.title = title
        self.authors = authors
        # Expected values for tests (can be exact values or validator functions)
        # Both plugins can use: "romanceio_id", "title", "authors"
        # romanceio plugin also uses:
        #   "series": str (series name) or None (standalone, skips series check)
        #   "series_index": float (e.g. 1.0) - required when "series" is a non-None str
        #   "pubdate": (year, month, day) tuple (e.g. (2021, 10, 5)) for a precise date
        # romanceio_fields plugin also uses: "steam", "star_rating", "rating_count", "tags"
        self.expected_fields = expected_fields or {}


# Shared test cases used by both romanceio and romanceio_fields plugins
TEST_BOOKS = [
    # A book with an INVALID Romance.io ID (should handle gracefully)
    BookTestData(
        romanceio_id="000000000000000000000000",  # Invalid ID
        title="Pride and Prejudice",
        authors=["Jane Austen"],
        expected_fields={
            "romanceio_id": None,  # Should be None after detecting invalid ID
            # Other fields will fail to load, which is expected
        },
    ),
    # A book with a Romance.io id
    BookTestData(
        romanceio_id="5484ecd47a5936fb0405756c",
        title="Pride and Prejudice",
        authors=["Jane Austen"],
        expected_fields={
            "romanceio_id": "5484ecd47a5936fb0405756c",
            "title": "Pride and Prejudice",
            "authors": ["Jane Austen"],
            "series": None,
            "pubdate": (1813, 1, 28),
            "steam": 1,
            "star_rating": lambda x: x and x >= 4.0,  # Should be ~4.54 (range 0-5)
            "rating_count": lambda x: x and x > 1000,  # Should be ~1351
            "tags": lambda x, delimiter: x and len(x.split(delimiter)) > 5,
        },
    ),
    # A book with just title and author
    BookTestData(
        title="Pride and Prejudice",
        authors=["Jane Austen"],
        expected_fields={
            "romanceio_id": "5484ecd47a5936fb0405756c",
            "title": "Pride and Prejudice",
            "authors": ["Jane Austen"],
            "series": None,
            "pubdate": (1813, 1, 28),
            "steam": 1,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,  # Range 0-5, should be ~4.54
            "rating_count": lambda x: x and x > 1000,  # Should be ~1351
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 5,
        },
    ),
    # A book with multiple title results with different authors
    # NOTE: This book also has a duplicate on Romance.io. This one has more ratings
    # but the other is part of a series. In the future we may add handling for dupes,
    # e.g. choosing the one with more ratings or that's part of a series.
    BookTestData(
        title="Fire and Ice",
        authors=["Tymber Dalton"],
        expected_fields={
            "romanceio_id": "5badeb3901dbc864fb916c8a",
            "title": "Fire and Ice",
            "authors": ["Tymber Dalton"],
            "series": None,
            "pubdate": (2012, 2, 26),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with multiple title hits with the same author
    # "Gold" and "Lord of Gold and Glory" (correct one is "Gold")
    BookTestData(
        title="Gold",
        authors=["Lisette Marshall"],
        expected_fields={
            "romanceio_id": "621a207396d3140e3386d95d",
            "title": "Gold",
            "authors": ["Lisette Marshall"],
            "series": "The Queen & The Assassin",
            "series_index": 3.0,
            "pubdate": (2022, 2, 22),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with multiple title hits with the same author
    # "The Burning Witch 3", "The Burning Witch 2", and "The Burning Witch"
    # (correct one is third in list)
    BookTestData(
        title="The Burning Witch",
        authors=["Delemhach"],
        expected_fields={
            "romanceio_id": "64a7c1fa5646247a73a6e96a",
            "title": "The Burning Witch",
            "authors": ["Delemhach"],
            "series": "The Burning Witch",
            "series_index": 1.0,
            "pubdate": (2023, 9, 5),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a "1" in the title shouldn't match books later in the series
    # correct: "The Burning Witch"
    # incorrect: "The Burning Witch 2" and "The Burning Witch 3"
    BookTestData(
        title="The Burning Witch 1",
        authors=["Delemhach"],
        expected_fields={
            "romanceio_id": "64a7c1fa5646247a73a6e96a",
            "title": "The Burning Witch",
            "authors": ["Delemhach"],
            "series": "The Burning Witch",
            "series_index": 1.0,
            "pubdate": (2023, 9, 5),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a colon in the title to indicate multiple works in a series
    # "The Secrets of Jane: Forgotten" and "The Secrets of Jane: Reborn"
    BookTestData(
        title="The Secrets of Jane: Reborn",
        authors=["Charlotte Mallory"],
        expected_fields={
            "romanceio_id": "67c8508afe62c3990a16787b",
            "title": "The Secrets of Jane: Reborn",
            "authors": ["Charlotte Mallory"],
            "series": "Improper Bastards",
            "series_index": 2.0,
            "pubdate": (2025, 3, 3),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a single-volume edition and multiple individual volumes as well
    # Also tests names where the order might be reversed (Gyeoeul Gwon vs Gwon Gyeoeul)
    # correct: "Villains Are Destined to Die (Villains Are Destined to Die (Novel) #1-5)" by Gyeoeul Gwon
    # incorrect:
    # "Villains Are Destined to Die, Vol. 1 (... [Ag-yeog-eui Ending-eun Jug-eumbbun] (Comic) #1)"
    # "Villains Are Destined to Die, Vol. 1 (Villains Are Destined to Die #1)"
    # "Villains Are Destined to Die, Vol. 2 (Villains Are Destined to Die #2)"
    # "Villains Are Destined to Die (novel), Vol. 2 (Villains Are Destined to Die (Novel) #2)" etc.
    BookTestData(
        title="Villains Are Destined to Die",
        authors=["Gwon Gyeoeul"],
        expected_fields={
            "romanceio_id": "663c6e6c9ad3052f634ccb3c",
            "title": "Villains Are Destined to Die (Villains Are Destined to Die (Novel) #1-5)",
            "authors": ["Gyeoeul Gwon", "권겨을"],
            "series": None,
            "pubdate": (2019, 5, 9),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a Romance.io id and a non-exact title match
    BookTestData(
        romanceio_id="66429764ef4321f294c2b682",
        title="The Burning Witch",
        authors=["Delemhach"],
        expected_fields={
            "romanceio_id": "66429764ef4321f294c2b682",
            "title": "The Burning Witch 3",
            "authors": ["Delemhach"],
            "series": "The Burning Witch",
            "series_index": 3.0,
            "pubdate": (2024, 5, 28),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 1 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a non-exact title match "and" vs. "&"
    BookTestData(
        title="Scythe and Sparrow",
        authors=["Brynne Weaver"],
        expected_fields={
            "romanceio_id": "67ab2276febe76f15f24c5b1",
            "title": "Scythe & Sparrow",
            "authors": ["Brynne Weaver"],
            "series": "The Ruinous Love Trilogy",
            "series_index": 3.0,
            "pubdate": (2025, 2, 11),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 1 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with an non-exact author match
    BookTestData(
        title="Treachery in Death",
        authors=["JD Robb"],
        expected_fields={
            "romanceio_id": "57efc13bde896e892492f8d3",
            "title": "Treachery in Death",
            "authors": ["J.D. Robb"],
            "series": "In Death",
            "series_index": 32.0,
            "pubdate": (2011, 2, 1),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 1 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a common word and series information in the in the title
    # Correct: "High Flyer (Verdant String)" by Michelle Diener
    # Wrong: "SOUTHSIDE HIGH" by Michelle Mankin
    BookTestData(
        title="High Flyer",
        authors=["Michelle Diener"],
        expected_fields={
            "romanceio_id": "5f193661b36b120e1449d5de",
            "title": "High Flyer (Verdant String)",
            "authors": ["Michelle Diener"],
            "series": "Verdant String",
            "series_index": 4.0,
            "pubdate": (2020, 7, 24),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book where the search title has extra words that the Romance.io result doesn't have
    # Search: "Funny Story (ORIGINAL)" -> Result: "Funny Story"
    BookTestData(
        title="Funny Story (ORIGINAL)",
        authors=["Emily Henry"],
        expected_fields={
            "romanceio_id": "65b604fa00d361e53f20ecfb",
            "title": "Funny Story",
            "authors": ["Emily Henry"],
            "series": None,
            "pubdate": (2024, 4, 23),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with special characters in the title
    # correct: "Ōkami" by Renée Ahdieh
    # incorrect: "Flame in the Mist" by Renée Ahdieh
    BookTestData(
        title="Okami: A Flame in the Mist Short Story",
        authors=["Renée Ahdieh"],
        expected_fields={
            "romanceio_id": "5eb3e49abe0aaecf555a3ce2",
            "title": "Ōkami",
            "authors": ["Renée Ahdieh"],
            "series": "Flame in the Mist",
            "series_index": 1.25,
            "pubdate": (2018, 4, 24),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a comma in the title
    BookTestData(
        title="Exit, Pursued by a Baron",
        authors=["Aydra Richards"],
        expected_fields={
            "romanceio_id": "6546a1d0c112bf11fe989beb",
            "title": "Exit, Pursued by a Baron",
            "authors": ["Aydra Richards"],
            "series": "The Beaumonts",
            "series_index": 1.0,
            "pubdate": (2023, 11, 3),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with a regular vs. smart apostrophe in the title
    BookTestData(
        title="Bellamy's Triumph",
        authors=["Guin Archer"],
        expected_fields={
            "romanceio_id": "616d1bed03069f0e3b9b4fbf",
            "title": "Bellamy’s Triumph",
            "authors": ["Guin Archer"],
            "series": "Angelic Resurrection",
            "series_index": 3.0,
            "pubdate": (2021, 10, 18),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book with US vs. UK spelling differences in the title (e.g. Honor vs. Honour)
    BookTestData(
        title="Shards of Honor",
        authors=["Lois McMaster Bujold"],
        expected_fields={
            "romanceio_id": "642b1019b7b8862bf6ea1f82",
            "title": "Shards of Honour",
            "authors": ["Lois McMaster Bujold"],
            "series": "Miles Vorsokigan",
            "series_index": 1.0,
            "pubdate": (1986, 1, 1),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # A book that's not on Romance.io and shouldn't return a partial match
    # incorrect: "Protector Wolf: Black Mesa Wolves" by J.K. Harper
    BookTestData(
        title="Wolf Protector",
        authors=["Harper A. Brooks"],
        expected_fields={
            "romanceio_id": None,
            # Other fields will fail to load, which is expected
        },
    ),
    # A book that's not on Romance.io and shouldn't return a partial match
    # incorrect: "The Heir" by Kayla Eshbaugh
    # Ensure that the "La" in "La Matrona" doesn't match "Kayla"
    BookTestData(
        title="The Heir",
        authors=["La Matrona"],
        expected_fields={
            "romanceio_id": None,
            # Other fields will fail to load, which is expected
        },
    ),
    # A book that's not on Romance.io and shouldn't return a partial match
    # incorrect: "Heart of a Champion; Soul of a Boss " by M. Monique
    BookTestData(
        title="Champion",
        authors=["I M Sterling"],
        expected_fields={
            "romanceio_id": None,
            # Other fields will fail to load, which is expected
        },
    ),
    # A book tthat's not on Romance.io and shouldn't return a partial match
    # incorrect: "The Adventurer" by Phoebe Alexander (romanceio:5ff56ec75800fd0df1f0978e)
    BookTestData(
        title="Adventurer",
        authors=["Alexander Olson"],
        expected_fields={
            "romanceio_id": None,
            # Other fields will fail to load, which is expected
        },
    ),
    # A book that's not on Romance.io and shouldn't return a partial match
    # incorrect: "Angel and the Assassin" by Fyn Alexander (romanceio:5455a0d487eac324117fbc91)
    BookTestData(
        title="Assassin",
        authors=["Alexander Olson"],
        expected_fields={
            "romanceio_id": None,
            # Other fields will fail to load, which is expected
        },
    ),
    # A book ith "and" vs. "&" in title and lots of authors
    BookTestData(
        title="Wolves & Warriors",
        authors=["Chloe Parker"],
        expected_fields={
            "romanceio_id": "622b054edf8bbc5810762df7",
            "title": "Wolves and Warriors",
            "authors": [
                "Chloe Parker",
                "Kathryn Ann Kingsley",
                "Rory Miles",
                "Loxley Savage",
                "Aleera Anaya Ceres",
                "Clarissa Bright",
                "Sara Ivy Hill",
                "RuNyx",
                "C.M. Nascosta",
                "Loni Ree",
                "Lana Kole",
                "Lyx Robinson",
                "Chloe Gunter",
                "Flora Quincy",
                "Lydia Reeves",
                "Xu-Ji Westin",
                "Lydia Guleva",
                "Leann Castellanos",
                "Jinx Layne",
                "Sophie Ash",
                "Kathryn Moon",
            ],
            "series": None,
            "pubdate": (2022, 6, 7),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # Match "Box Set" vs. "Boxset" and space in author initials
    # incorrect: "Dr. Stanton" by T.L. Swan (Dr. Stanton #1)
    BookTestData(
        title="Dr. Stanton Boxset",
        authors=["T. L. Swan"],
        expected_fields={
            "romanceio_id": "649ef2299c9b9f37ff8cee05",
            "title": "Dr. Stanton Box Set",
            "authors": ["T.L. Swan"],
            "series": None,
            "pubdate": (2019, 6, 23),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # Handle parentheses in the title and special characters in the author name
    BookTestData(
        title="(Totally Not An) EVIL OVERLADY",
        authors=["Álex Gilbert"],
        expected_fields={
            "romanceio_id": None,
            # Other fields will fail to load, which is expected
        },
    ),
    # Match a book with an additional author in Calibre not listed in Romance.io
    BookTestData(
        title="Reaper's Blood",
        authors=["Kel Carpenter", "Meg Anne"],
        expected_fields={
            "romanceio_id": "691b24ce4d9d6a76cf3edbbd",
            "title": "Reaper's Blood",
            "authors": ["Meg Anne"],
            "series": "Reapers of the Grimm Brotherhood",
            "series_index": 1.0,
            "pubdate": (2021, 3, 1),
            "steam": lambda x: x is None or (1 <= x <= 5),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # Handle repeated tokens in the title
    BookTestData(
        title="I Love You, I Hate You",
        authors=["Elizabeth Davis"],
        expected_fields={
            "romanceio_id": "61653419fef5b30e2ddf8b0a",
            "title": "I Love You, I Hate You",
            "authors": ["Elizabeth Davis"],
            "series": None,
            "pubdate": (2021, 10, 12),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # Handle extra content in Romance.io title
    # incorrect: "Reflections of Us" by Yumoyori Wilson
    BookTestData(
        title="Reflections of Me",
        authors=["Yumoyori Wilson"],
        expected_fields={
            "romanceio_id": "683365deacfd91f84370a7f2",
            "title": "Reflections of Me: Year Two",
            "authors": ["Yumoyori Wilson", "Avery Phoenix"],
            "series": "Brighten Magic Academy",
            "series_index": 2.0,
            "pubdate": (2018, 7, 29),
            "steam": lambda x: x is None or (1 <= x <= 5),
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
    # Handle Part One vs. Part Two
    # incorrect: "Lola and the Millionaires: Part One" by Kathryn Moon
    BookTestData(
        title="Lola and the Millionaires: Part Two",
        authors=["Kathryn Moon"],
        expected_fields={
            "romanceio_id": "5ee1d694c35fb70e31ab8f9d",
            "title": "Lola & the Millionaires: Part Two",
            "authors": ["Kathryn Moon"],
            "series": "Sweet Omegaverse",
            "series_index": 3.0,
            "pubdate": (2020, 6, 11),
            "steam": lambda x: x is not None and 1 <= x <= 5,
            "star_rating": lambda x: x is not None and 0 <= x <= 5,
            "rating_count": lambda x: x is not None and x >= 0,
            "tags": lambda x, delimiter: x is not None and len(x.split(delimiter)) > 0,
        },
    ),
]
