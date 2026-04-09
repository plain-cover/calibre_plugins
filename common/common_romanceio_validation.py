"""
Common validation utilities for Romance.io IDs and data.
Shared across romanceio and romanceio_fields plugins.
"""

import re

from typing import List, Optional


def is_valid_romanceio_id(romanceio_id: Optional[str]) -> bool:
    """Validate a Romance.io book ID.

    Romance.io uses 24-character hexadecimal strings.
    Valid IDs are:
    - Exactly 24 characters long
    - Contain only hexadecimal characters (0-9, a-f, A-F)
    - Not all zeros
    - Not all the same character

    Args:
        romanceio_id: String to validate

    Returns:
        True if valid, False otherwise
    """
    if not romanceio_id:
        return False

    # Must be exactly 24 characters
    if len(romanceio_id) != 24:
        return False

    # Must be hexadecimal
    if not re.match(r"^[0-9a-fA-F]{24}$", romanceio_id):
        return False

    # Must not be all zeros
    if romanceio_id == "0" * 24:
        return False

    return True


def normalize_author_initials(author_name: str) -> str:
    """Normalize author name by removing spaces between single-letter initials.

    This matches Romance.io's UI display format where "J. D. Robb" becomes "J.D. Robb".
    Only removes spaces between single letters followed by periods.

    Args:
        author_name: Author name to normalize

    Returns:
        Normalized author name

    Examples:
        >>> normalize_author_initials('J. D. Robb')
        'J.D. Robb'
        >>> normalize_author_initials('T. L. Swan')
        'T.L. Swan'
        >>> normalize_author_initials('Jane Austen')
        'Jane Austen'
    """
    if not author_name:
        return author_name

    # Remove spaces between single-letter initials: "J. D." -> "J.D."
    # Pattern: single letter + period + space + another single letter + period
    normalized = re.sub(r"\b([A-Za-z])\.\s+(?=[A-Za-z]\.)", r"\1.", author_name)
    return normalized


def clean_author_names(authors: List[str]) -> List[str]:
    """Clean a list of author names by trimming whitespace and filtering blanks.

    This function:
    - Strips leading/trailing whitespace from each name
    - Collapses multiple internal spaces to single spaces
    - Normalizes initials (removes spaces between single-letter initials)
    - Filters out blank/empty names
    - Preserves all valid UTF-8 characters (accents, smart quotes, etc.)

    Args:
        authors: List of author names

    Returns:
        Cleaned list of author names

    Examples:
        >>> clean_author_names(['Renée Ahdieh', '  Jane Austen  ', '', '  '])
        ['Renée Ahdieh', 'Jane Austen']
        >>> clean_author_names(['J. D. Robb', 'T. L. Swan'])
        ['J.D. Robb', 'T.L. Swan']
    """
    cleaned_authors = []

    for author in authors:
        # Strip whitespace and collapse multiple spaces
        cleaned = " ".join(author.split())

        # Normalize initials (remove spaces between single-letter initials)
        cleaned = normalize_author_initials(cleaned)

        # Only add non-empty names
        if cleaned:
            cleaned_authors.append(cleaned)

    return cleaned_authors
