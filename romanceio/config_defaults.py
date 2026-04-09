"""
Default configuration values for the romanceio plugin.

Kept in a separate module with no Qt or Calibre imports so they can be used
by tests without triggering the GUI environment.
"""

STORE_NAME = "Options"
KEY_GENRE_MAPPINGS = "genreMappings"
KEY_MAP_GENRES = "mapGenres"

DEFAULT_GENRE_MAPPINGS = {
    "contemporary": ["Romance", "Contemporary"],
    "dark romance": ["Romance", "Dark Romance"],
    "fantasy": ["Romance", "Fantasy"],
    "gay romance": ["Romance", "Gay Romance"],
    "historical": ["Romance", "Historical"],
    "lesbian romance": ["Romance", "Lesbian Romance"],
    "mystery": ["Romance", "Mystery"],
    "paranormal": ["Romance", "Paranormal"],
    "queer romance": ["Romance", "Queer Romance"],
    "science fiction": ["Romance", "Science Fiction"],
    "suspense": ["Romance", "Suspense"],
    "urban fantasy": ["Romance", "Urban Fantasy"],
    "young adult": ["Romance", "Young Adult"],
}
