"""
Helper to search Romance.io and extract book ID.
Shared between romanceio and romanceio_fields plugins.
"""

import re
import string
import unicodedata
from typing import Optional, List, Dict, Any, Callable

try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote  # type: ignore

try:
    from lxml.html import fromstring
except ImportError:
    fromstring = None  # type: ignore[assignment]  # Will fail if HTML parsing is actually needed

try:
    from .common_romanceio_fetch_helper import sanitize_html_for_lxml
except ImportError:
    sanitize_html_for_lxml = None  # type: ignore[assignment]  # Will fail if HTML parsing is actually needed

try:
    from calibre.utils.icu import lower  # type: ignore[misc]
except ImportError:
    # Fallback for when running outside Calibre environment
    # Match calibre's signature: lower(x) -> str
    def lower(x: Any) -> str:
        """Fallback lowercase function when calibre.utils.icu is not available."""
        if isinstance(x, bytes):
            x = x.decode("utf-8")
        elif not isinstance(x, str):
            x = str(x)
        return x.lower()


_TEXTUAL_TO_DIGIT = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "thirteen": "13",
    "fourteen": "14",
    "fifteen": "15",
    "sixteen": "16",
    "seventeen": "17",
    "eighteen": "18",
    "nineteen": "19",
    "twenty": "20",
}


def _text_number_to_digit(text):
    """
    Convert textual number to its digit equivalent.
    Example: "One" -> "1", "Two" -> "2", "Twenty" -> "20"
    Returns the original text if not a recognized number word.
    """
    if not text:
        return text
    return _TEXTUAL_TO_DIGIT.get(text.lower(), text)


def _normalize_for_matching(text):
    """
    Normalize text for matching by removing accents and diacritics.
    Also remove apostrophes and normalize common US/UK spelling differences.
    Also removes spaces between single-letter initials (e.g., "T. L." -> "T.L.").
    Example: "Ōkami" -> "Okami", "Renée" -> "Renee", "Bellamy's" -> "Bellamys"
    Example: "Honour" -> "Honor", "Colour" -> "Color"
    Example: "T. L. Swan" -> "T.L. Swan"
    """
    if not text:
        return ""
    text = (
        text.replace("'", "")  # Regular apostrophe U+0027
        .replace("\u2019", "")  # Right single quotation mark (smart apostrophe)
        .replace("\u2018", "")  # Left single quotation mark
        .replace("\u201c", "")  # Left double quotation mark
        .replace("\u201d", "")  # Right double quotation mark
    )
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    # Normalize common US/UK spelling differences (UK -> US) - lowercase for simplicity
    # Also normalize compound words like "boxset" to "box set"
    text = (
        text.lower()
        .replace("honour", "honor")
        .replace("colour", "color")
        .replace("favour", "favor")
        .replace("flavour", "flavor")
        .replace("boxset", "box set")
        .replace("box-set", "box set")
    )
    # Remove spaces between single-letter initials (e.g., "t. l. swan" -> "t.l. swan")
    # This handles author names like "T. L. Swan" vs "T.L. Swan"
    text = re.sub(r"\b([a-z])\.\s+(?=[a-z]\.)", r"\1.", text)
    return text


def _clean_title_for_matching(title):
    """
    Clean title by removing subtitles and parentheticals.
    This is used for consistent matching - we want to match against
    the main title only, not subtitles.

    Example: "Okami: A Flame in the Mist Short Story" -> "Okami"
    Example: "High Flyer (Verdant String)" -> "High Flyer"
    Example: "(Totally Not An) EVIL OVERLADY" -> "(Totally Not An) EVIL OVERLADY" (keep if starts with paren)
    """
    if not title:
        return ""

    # Split on colon first (handles subtitle after colon)
    main_part = title.split(":")[0].strip()

    # Only remove parenthetical if it's not at the start of the title
    # This preserves titles like "(Totally Not An) EVIL OVERLADY"
    if not main_part.startswith("("):
        main_part = main_part.split("(")[0].strip()

    return main_part


def _split_title_parts(title):
    """
    Split title into main title and subtitle.
    Returns (main_title, subtitle)

    Example: "Okami: A Flame in the Mist Short Story" -> ("Okami", "A Flame in the Mist Short Story")
    """
    if not title:
        return ("", "")

    # Split on colon or opening parenthesis
    if ":" in title:
        parts = title.split(":", 1)
        return (parts[0].strip(), parts[1].strip() if len(parts) > 1 else "")
    if "(" in title:
        parts = title.split("(", 1)
        subtitle = parts[1].rstrip(")").strip() if len(parts) > 1 else ""
        return (parts[0].strip(), subtitle)
    return (title.strip(), "")


def _tokens_in_order(search_tokens, result_text_normalized):
    """
    Check if search tokens appear in the result text in the same order.
    Returns True if all tokens are found and appear in order, False otherwise.

    Example:
        search_tokens = ["wolf", "protector"]
        result = "wolf protector" -> True
        result = "protector wolf" -> False
        result = "the wolf is a protector" -> True (can have words between)
    """
    if not search_tokens:
        return True

    # Find the position of each token in the result text
    # For duplicate tokens, we need to search AFTER the last position
    last_pos = 0
    for token in search_tokens:
        token_normalized = lower(_normalize_for_matching(token))
        pattern = r"\b" + str(re.escape(token_normalized)) + r"\b"
        # Search starting from position after last match
        match = re.search(pattern, str(result_text_normalized[last_pos:]))
        if not match:
            return False

        # Update absolute position for next token (match.start() is relative to slice)
        last_pos = last_pos + match.start() + len(match.group())

    return True


def create_title_author_matcher(orig_title, title_tokens, author_tokens):
    """
    Create a matcher function that checks if a result matches the search criteria
    and returns a match score.

    Args:
        orig_title: Original search title
        title_tokens: List of tokenized title words
        author_tokens: List of tokenized author words

    Returns:
        Function that takes (result_title, result_authors) and returns (is_match, score)
        where score is the number of matching tokens (higher is better)
    """

    def get_match_score(result_title, result_authors):
        """Check if result matches and return match quality score."""
        result_authors_str = lower(" ".join(result_authors))

        # Split search title into main title and subtitle for weighted matching
        search_main, _ = _split_title_parts(orig_title)

        # Normalize both search and result for accent-insensitive matching
        search_main_normalized = lower(_normalize_for_matching(search_main))
        result_title_normalized = lower(_normalize_for_matching(result_title))

        # Author matching with scoring
        # - Highest priority: last name matches (typically surname)
        # - Secondary: first name matches
        # - Handle reversed names (e.g., "Gyeoeul Gwon" vs "Gwon Gyeoeul")
        # - Penalty: extra characters in result author that aren't in search author
        # - Use word boundaries to prevent partial matches (e.g., "La" in "Kayla")
        author_score = 0
        if author_tokens:
            result_authors_str_val = str(result_authors_str)

            # Last name match (most important) - use word boundaries
            last_name = str(lower(author_tokens[-1]))
            last_name_pattern = r"\b" + str(re.escape(last_name)) + r"\b"
            last_name_match = bool(re.search(last_name_pattern, result_authors_str_val))

            if last_name_match:
                author_score += 100

            # First name match (if we have multiple tokens) - use word boundaries
            first_name_match = False
            if len(author_tokens) > 1:
                first_name = str(lower(author_tokens[0]))
                first_name_pattern = r"\b" + str(re.escape(first_name)) + r"\b"
                first_name_match = bool(re.search(first_name_pattern, result_authors_str_val))
                if first_name_match:
                    author_score += 50

            # If no match yet, check if names are reversed
            # e.g., "Gyeoeul Gwon" (search) vs. "Gwon Gyeoeul" (result)
            # IMPORTANT: Require BOTH names to be present to avoid false matches like
            # "Alexander Olson" matching "Phoebe Alexander" (where only "Alexander" matches)
            if not last_name_match and len(author_tokens) >= 2:
                # Check if first token appears in result (might be last name in reversed order)
                first_token = str(lower(author_tokens[0]))
                first_token_pattern = r"\b" + str(re.escape(first_token)) + r"\b"
                first_token_in_result = bool(re.search(first_token_pattern, result_authors_str_val))

                # Check if last token also appears (confirming reversed names)
                last_token_in_result = bool(re.search(last_name_pattern, result_authors_str_val))

                # Only treat as reversed names if BOTH tokens are present
                if first_token_in_result and last_token_in_result:
                    author_score += 100  # Treat as last name match
                    author_score += 50  # Bonus for both names present
                    last_name_match = True

            # Penalty for extra characters (indicates different author)
            # Only apply if we don't have an exact match for the full author name
            # This allows multi-author books while catching typos like "Smith" vs "Smithson"
            search_author_str = str(lower(" ".join(author_tokens)))

            # Check if exact author name appears in result (handles multi-author books)
            has_exact_match = search_author_str in result_authors_str_val

            if not has_exact_match:
                # Calculate penalty for extra characters
                extra_chars = 0
                for char in result_authors_str_val:
                    if char not in search_author_str and char.isalnum():
                        extra_chars += 1
                author_score -= extra_chars

            # Must have at least one name token match to be valid
            if author_score < 100:
                return (False, 0)

            # Additional validation for names with initials/short tokens
            # If search has 3+ tokens (e.g., "I M Sterling"), require last name match
            # This prevents "I M Sterling" from matching "M. Monique"
            if len(author_tokens) >= 3:
                # Check if any tokens are very short (initials like "I", "M")
                has_short_tokens = any(len(token) <= 2 for token in author_tokens[:-1])
                if has_short_tokens and not last_name_match:
                    # Has initials but last name didn't match - reject
                    return (False, 0)

        if author_score < 0:
            return (False, 0)

        # Early validation: Check for part number mismatches in full title (not just tokens)
        # This catches "Part One" vs "Part Two" even when tokenization strips the subtitle
        orig_title_lower = lower(orig_title)
        result_title_lower = lower(result_title)

        search_part_match = re.search(
            r"part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)",
            str(orig_title_lower),
            re.IGNORECASE,
        )
        result_part_match = re.search(
            r"part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)",
            str(result_title_lower),
            re.IGNORECASE,
        )

        if search_part_match and result_part_match:
            search_part = search_part_match.group(1).lower()
            result_part = result_part_match.group(1).lower()
            search_part_num = _text_number_to_digit(search_part)
            result_part_num = _text_number_to_digit(result_part)

            if search_part_num != result_part_num:
                # Different parts - this is the wrong book in the series
                return (False, 0)

        # Title match - count matching tokens bidirectionally
        if not title_tokens:
            return (True, 0)

        # Get result title tokens
        result_title_tokens = _get_title_tokens(result_title)

        # Separate numeric tokens from word tokens for special handling
        # Include textual numbers like "One", "Two", "Three" as numeric tokens
        search_numbers = []
        search_words = []
        for t in title_tokens:
            if not t:
                continue
            digit_val = _text_number_to_digit(t)
            if (t and t.isdigit()) or (digit_val and digit_val.isdigit()):
                search_numbers.append(digit_val if (digit_val and digit_val.isdigit()) else t)
            else:
                search_words.append(t)

        result_numbers = []
        result_words = []
        for t in result_title_tokens:
            if not t:
                continue
            digit_val = _text_number_to_digit(t)
            if (t and t.isdigit()) or (digit_val and digit_val.isdigit()):
                result_numbers.append(digit_val if (digit_val and digit_val.isdigit()) else t)
            else:
                result_words.append(t)

        # Check if all search WORD tokens are in result (ignoring numbers)
        # Use normalized text for accent-insensitive matching
        # For duplicate words, we only need to check if they exist, not count occurrences
        search_words_in_result = 0
        search_words_in_result_main = 0  # Track main title matches separately
        search_words_unique = list(dict.fromkeys(search_words))  # Remove duplicates while preserving order
        for token in search_words_unique:
            token_normalized = lower(_normalize_for_matching(token))
            pattern = r"\b" + str(re.escape(token_normalized)) + r"\b"
            if re.search(pattern, str(result_title_normalized)):
                search_words_in_result += 1
                # Check if this token is from main title (higher weight)
                if re.search(pattern, str(search_main_normalized)):
                    search_words_in_result_main += 1

        # Check if all result WORD tokens are in search (ignoring numbers)
        # Match against full search title (main + subtitle) with normalization
        result_words_in_search = 0
        result_words_in_main = 0  # Track how many result words match main title
        search_full_normalized = lower(_normalize_for_matching(orig_title))
        result_words_unique = list(dict.fromkeys(result_words))  # Remove duplicates
        for token in result_words_unique:
            token_normalized = lower(_normalize_for_matching(token))
            pattern = r"\b" + str(re.escape(token_normalized)) + r"\b"
            if re.search(pattern, str(search_full_normalized)):
                result_words_in_search += 1
                # Check if token matches main title (higher priority than subtitle)
                if search_main and re.search(pattern, str(search_main_normalized)):
                    result_words_in_main += 1

        # Match if either:
        # 1. All search words are in result (handles "High Flyer" -> "High Flyer (Verdant String)")
        # 2. All result words are in search (handles "Funny Story (ORIGINAL)" -> "Funny Story")
        # Note: We ignore number tokens for initial matching and use unique words for comparison
        all_search_words_in_result = search_words_in_result == len(search_words_unique)
        all_result_words_in_search = result_words_in_search == len(result_words_unique)

        if not (all_search_words_in_result or all_result_words_in_search):
            return (False, 0)

        # Additional check: tokens must appear in the same order
        # This prevents "Wolf Protector" from matching "Protector Wolf"
        if all_search_words_in_result:
            # Check if search tokens appear in result in the same order
            if not _tokens_in_order(search_words, result_title_normalized):
                return (False, 0)

        if all_result_words_in_search:
            # Check if result tokens appear in search in the same order
            if not _tokens_in_order(result_words, search_full_normalized):
                return (False, 0)

        # Calculate match quality score - prefer matches with more tokens
        # Prioritize: exact match > exact main title match > all search in result > all result in search
        # Also prioritize matches on main title over subtitle matches

        # Check for exact match on full title (with normalization)
        if result_title_normalized == search_full_normalized:
            score = 1000 + max(len(title_tokens), len(result_title_tokens))
        # Check for exact match on main title only (handles "Gold" matching "Gold" not "Lord of Gold and Glory")
        elif result_title_normalized == search_main_normalized:
            score = 900 + len(title_tokens)
        elif all_search_words_in_result and all_result_words_in_search:
            score = 500 + max(search_words_in_result, result_words_in_search)
            # Bonus if result words primarily match main title (not subtitle)
            if search_main and len(result_words) > 0:
                main_title_ratio = result_words_in_main / len(result_words)
                score += int(main_title_ratio * 200)  # Up to +200 for 100% main title match
        elif all_search_words_in_result:
            score = 300 + search_words_in_result
            # Bonus if search tokens are from main title
            if len(search_words) > 0:
                main_ratio = search_words_in_result_main / len(search_words)
                score += int(main_ratio * 100)  # Up to +100 for main title tokens
        else:  # all_result_words_in_search
            score = 200 + result_words_in_search
            # Bonus if result words match main title rather than subtitle
            if len(result_words) > 0:
                main_title_ratio = result_words_in_main / len(result_words)
                score += int(main_title_ratio * 150)  # Up to +150 for main title match

        # Handle series numbers specially
        # If search has "1" and result has no number, give bonus (likely the base book)
        # If search has "1" and result has "1", give bonus (exact match)
        # If search has "1" and result has "2", "3", etc., give penalty (wrong book)
        # If search has high number (>1) and result has no number, reject (sequel that doesn't exist)
        if search_numbers:
            if not result_numbers:
                # Check if search is asking for book 1 (or contains "1")
                # "The Burning Witch 1" matching "The Burning Witch" is correct
                # But "Mark of the Fool 8" matching "Mark of the Fool" is wrong
                if "1" in search_numbers:
                    # Search for "The Burning Witch 1", result is "The Burning Witch" - likely correct!
                    score += 150
                else:
                    # Search for sequel (2+) but result has no number - probably wrong match
                    # Reject this match as it's likely looking for a nonexistent sequel
                    return (False, 0)
            elif search_numbers == result_numbers:
                # Numbers match exactly
                score += 100
            else:
                # Numbers don't match - probably wrong book in series
                score -= 300

        # Add author score to prioritize better author matches
        score += author_score

        return (True, score)

    return get_match_score


def search_for_romanceio_id(title, authors, fetch_page_func, log_func=print):
    """
    Search Romance.io for a book and return its romanceio_id.

    Args:
        title: Book title
        authors: List of author names
        fetch_page_func: Function to fetch pages (e.g., fetch_helper.fetch_page)
        log_func: Logging function (defaults to print)

    Returns:
        romanceio_id (str) or None if not found (but search completed successfully)

    Raises:
        RuntimeError: If page fetch fails or HTML parsing fails (technical failures)
    """
    # Build search query
    query_url = _build_search_query(title, authors)
    if not query_url:
        error_msg = "search_for_romanceio_id: Could not build search query"
        log_func(error_msg)
        raise RuntimeError(error_msg)

    log_func(f"Searching Romance.io: {query_url}")

    raw_html = fetch_page_func(query_url, wait_for_element="book-results", max_wait=30)
    if not raw_html:
        error_msg = "Failed to fetch Romance.io search page"
        log_func(error_msg)
        raise RuntimeError(error_msg)

    try:
        root = fromstring(sanitize_html_for_lxml(raw_html))  # type: ignore[misc]
    except (ValueError, TypeError, OSError) as e:
        error_msg = f"Failed to parse Romance.io search page HTML: {e}"
        log_func(error_msg)
        raise RuntimeError(error_msg) from e

    romanceio_id = _parse_search_results(root, title, authors, log_func)

    return romanceio_id


def parse_search_results_for_id_and_cover(root, orig_title, orig_authors, log_func=print):
    """
    Parse Romance.io search results HTML and extract romanceio_id, title, authors, and cover URL.

    Args:
        root: lxml HTML root element
        orig_title: Original search title
        orig_authors: List of original author names
        log_func: Logging function (defaults to print)

    Returns:
        Tuple of (romanceio_id, title, authors, cover_url) or None if no match found
    """
    # Use the same parsing logic as _parse_search_results to get the best match ID
    best_match_data = _parse_search_results_with_details(root, orig_title, orig_authors, log_func)

    if not best_match_data:
        return None

    romanceio_id, title, authors = best_match_data

    # Extract cover URL for this specific book
    results = root.xpath('//ul[@id="book-results"]//li[@class="has-background"]')
    for result in results:
        url_elem = result.xpath('.//div[@class="flexbox"]//div[@class="col"]//h3//a')
        if url_elem:
            book_url = url_elem[0].get("href")
            match = re.search(r"/books/([a-f0-9]+)", book_url)
            if match and match.group(1) == romanceio_id:
                # Found the matching result, extract cover
                cover_url = None
                img_elem = result.xpath('.//img[contains(@class, "img-cover")]')
                if img_elem:
                    cover_url = img_elem[0].get("data-src") or img_elem[0].get("src")
                    if cover_url:
                        # Convert small to large cover
                        cover_url = cover_url.replace("/small/", "/large/")

                log_func(f"Match found: {title} by {authors} (Romance.io ID: {romanceio_id})")
                return (romanceio_id, title, authors, cover_url)

    # If we couldn't find the cover, still return the match without it
    log_func(f"Match found: {title} by {authors} (Romance.io ID: {romanceio_id})")
    return (romanceio_id, title, authors, None)


def build_search_string(title, authors):
    """
    Build Romance.io search query string from title and authors.
    This is used by both HTML search and JSON API search.

    Args:
        title: Book title
        authors: List of author names (or single author string)

    Returns:
        URL-encoded search string (e.g., "pride+prejudice+jane+austen") or None
    """
    if not title and not authors:
        return None

    # Tokenize title (remove common words, keep significant terms)
    title_tokens = _get_title_tokens(title)

    # Get first author
    author_tokens = []
    if authors:
        first_author = authors[0] if isinstance(authors, list) else authors
        author_tokens = first_author.split()

    # Combine tokens
    tokens = title_tokens + author_tokens

    # URL encode
    encoded_tokens = [quote(t.encode("utf-8") if isinstance(t, str) else t) for t in tokens]
    query_string = "+".join(encoded_tokens)

    return query_string


def _build_search_query(title, authors):
    """Build Romance.io search URL from title and authors."""
    query_string = build_search_string(title, authors)
    if not query_string:
        return None
    return f"https://www.romance.io/search?q={query_string}"


def _get_title_tokens(title):
    """Extract significant words from title."""
    if not title:
        return []

    title = _clean_title_for_matching(title)

    # Split into words and remove very short words
    words = title.split()

    # Strip punctuation from each word
    words = [w.strip(string.punctuation) for w in words if w.strip(string.punctuation)]

    # Filter out common articles and prepositions, but keep numbers and meaningful short words
    # Keep important pronouns as they're grammatically significant in titles
    stop_words = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
    }
    # Preserve meaningful short pronouns that distinguish titles
    preserved_short_words = {"i", "me", "us", "we"}
    # Keep meaningful words: longer than 2 chars (excluding stop words), digits, or preserved pronouns
    significant_words = []
    for w in words:
        # Keep if: long enough (>2) and not a stop word, OR is a digit, OR is a preserved pronoun
        if (len(w) > 2 and w.lower() not in stop_words) or w.isdigit() or w.lower() in preserved_short_words:
            significant_words.append(w)

    # If we filtered everything, just use the original words
    if not significant_words:
        significant_words = words

    return significant_words


def _parse_search_results(root, orig_title, orig_authors, log_func):
    """
    Parse Romance.io search results HTML and extract romanceio_id.

    Returns the ID of the best matching book, preferring exact title matches
    and omnibus editions over individual volumes.
    """
    result = _parse_search_results_with_details(root, orig_title, orig_authors, log_func)
    return result[0] if result else None


def _parse_search_results_with_details(root, orig_title, orig_authors, log_func):
    """
    Parse Romance.io search results HTML and extract romanceio_id with title and authors.

    Returns tuple of (romanceio_id, title, authors) for the best matching book,
    preferring exact title matches and omnibus editions over individual volumes.
    """
    # Find search result items
    results = root.xpath('//ul[@id="book-results"]//li[@class="has-background"]')
    log_func(f"Found {len(results)} search results")

    if not results:
        return None

    # Tokenize for matching
    title_tokens = _get_title_tokens(orig_title)

    # For multi-author books, try to match any of the authors
    # This handles cases where Calibre has multiple authors but Romance.io only lists one
    all_author_tokens = []
    if orig_authors:
        authors_list = orig_authors if isinstance(orig_authors, list) else [orig_authors]
        for author in authors_list:
            all_author_tokens.append(author.split())

    # If no authors, use empty tokens
    if not all_author_tokens:
        all_author_tokens = [[]]

    # Collect all matches and find the best one by score
    best_match = None
    best_score = -1
    orig_title_lower = lower(orig_title)

    # Check if original title has series info (e.g., "#1", "Book 1", "Vol. 1", "Part One", or just "1" at end)
    # This includes standalone numbers like "The Burning Witch 1"
    has_series_info = bool(
        re.search(
            r"#\d+|book\s+\d+|vol\.?\s*\d+|part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)|\b\d+$",
            str(orig_title_lower),
            re.IGNORECASE,
        )
    )

    # Check if search title is looking for first book (has "1" or "One" in any form)
    search_for_first = bool(
        re.search(
            r"#1\b|book\s+1\b|vol\.?\s*1\b|part\s+one\b|\b1$",
            str(orig_title_lower),
            re.IGNORECASE,
        )
    )

    # Try matching with each author from the search
    for author_tokens in all_author_tokens:
        # Create matcher function for this author
        get_match_score = create_title_author_matcher(orig_title, title_tokens, author_tokens)

        # Process each result
        for result in results:
            # Extract title
            title_elem = result.xpath('.//div[@class="col"]//h3//a')
            if not title_elem:
                continue
            result_title = title_elem[0].text_content().strip()

            # Extract authors
            author_elems = result.xpath('.//div[@class="col"]//h4//div//span//a')
            if not author_elems:
                continue
            result_authors = []
            for a in author_elems:
                author_text = a.text_content().strip()
                # Split by comma in case multiple authors are in one field
                # e.g., "Yumoyori Wilson, Avery Phoenix" -> ["Yumoyori Wilson", "Avery Phoenix"]
                if ", " in author_text:
                    result_authors.extend([name.strip() for name in author_text.split(", ")])
                else:
                    result_authors.append(author_text)

            # Check if this result matches and get its score
            is_match, match_score = get_match_score(result_title, result_authors)

            if is_match:
                # Extract URL and ID
                url_elem = result.xpath('.//div[@class="flexbox"]//div[@class="col"]//h3//a')
                if not url_elem:
                    continue

                book_url = url_elem[0].get("href")

                # Extract romanceio_id from URL: /books/{id}/title-author
                url_match = re.search(r"/books/([a-f0-9]+)", book_url)
                if url_match:
                    romanceio_id = url_match.group(1)
                    result_title_lower = lower(result_title)

                    # Add additional scoring factors
                    score = match_score

                    if not has_series_info:
                        # Search didn't specify series info, so prefer omnibus/standalone over individual volumes
                        # Check if result has single volume indicators
                        # Match: "#5", "Vol. 5", "Volume 5", "Book 5", "Part Two"
                        # Don't match: "#1-5", "Vol. 1-5" (these are omnibus/collections)
                        has_single_volume = bool(
                            re.search(
                                r"(#|vol\.?|volume|book)\s*\d+(?!\s*[-–—]\s*\d+)"
                                r"|part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)",
                                str(result_title_lower),
                                re.IGNORECASE,
                            )
                        )

                        if not has_single_volume:
                            # Prefer results without single volume numbers (likely omnibus or standalone)
                            score += 100
                        else:
                            # Deprioritize individual volumes
                            score -= 50
                    elif search_for_first:
                        # Search is for first book (e.g., "The Burning Witch 1" or "Part One")
                        # Prefer the base book without a volume number over sequels
                        # Match sequels: "#2", "#3", "Vol. 2", "Part Two", etc. (not "#1", "Vol. 1", "Part One")
                        has_sequel_number = bool(
                            re.search(
                                r"(#|vol\.?|volume|book)\s*([2-9]|\d{2,})(?!\s*[-–—]\s*\d+)"
                                r"|part\s+(two|three|four|five|six|seven|eight|nine|ten|[2-9]|\d{2,})",
                                str(result_title_lower),
                                re.IGNORECASE,
                            )
                        )

                        if has_sequel_number:
                            # This is a sequel (book 2, 3, etc.), deprioritize it
                            score -= 200
                        else:
                            # Either the base book or book 1, prefer it
                            score += 50
                    else:
                        # Search has series info (but not first) - check for part mismatch
                        # Extract part number/word from search title
                        search_part_match = re.search(
                            r"part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)",
                            str(orig_title_lower),
                            re.IGNORECASE,
                        )
                        if search_part_match:
                            search_part = search_part_match.group(1).lower()
                            # Extract part from result title
                            result_part_match = re.search(
                                r"part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)",
                                str(result_title_lower),
                                re.IGNORECASE,
                            )
                            if result_part_match:
                                result_part = result_part_match.group(1).lower()
                                # Convert word numbers to digits for comparison
                                word_to_num = {
                                    "one": "1",
                                    "two": "2",
                                    "three": "3",
                                    "four": "4",
                                    "five": "5",
                                    "six": "6",
                                    "seven": "7",
                                    "eight": "8",
                                    "nine": "9",
                                    "ten": "10",
                                }
                                search_part_num = word_to_num.get(search_part, search_part)
                                result_part_num = word_to_num.get(result_part, result_part)

                                if search_part_num != result_part_num:
                                    # Different parts - reject this match
                                    score -= 500

                    # Prefer shorter titles (closer match)
                    title_length_diff = abs(len(result_title_lower) - len(orig_title_lower))
                    score -= title_length_diff

                    # Update best match if this is better
                    if score > best_score:
                        best_score = score
                        best_match = (romanceio_id, result_title, result_authors)

    # If we found a match, use the best one
    if best_match:
        return best_match

    return None


def _has_volume_range(title: str) -> bool:
    """
    Check if a title contains a volume range (e.g., #1-5, Vol. 1-5, Books 1-5).

    Args:
        title: Book title to check

    Returns:
        True if title contains a volume range, False otherwise
    """
    # Match patterns like "#1-5", "Vol. 1-5", "Books 1-5", etc.
    range_pattern = r"(?:#|vol\.?\s*|books?\s*|volumes?\s*)(\d+)\s*[-–—]\s*(\d+)"
    return bool(re.search(range_pattern, title, re.IGNORECASE))


def _has_individual_volume(title: str) -> bool:
    """
    Check if a title contains an individual volume number (e.g., Vol. 2, #2, Book 2).

    Args:
        title: Book title to check

    Returns:
        True if title contains an individual volume number, False otherwise
    """
    # Match patterns like "Vol. 2", "#2", "Book 2" but NOT ranges
    # Negative lookahead to avoid matching ranges
    individual_pattern = r"(?:#|vol\.?\s*|book\s+|volume\s+)(\d+)(?!\s*[-–—]\s*\d+)"
    return bool(re.search(individual_pattern, title, re.IGNORECASE))


def find_best_json_match(
    books: List[Dict[str, Any]],
    search_title: str,
    search_authors: Optional[List[str]],
    log_func: Callable = print,
) -> Optional[str]:
    """
    Find the best matching book from JSON search results using title/author scoring.
    Prefers boxed sets/complete editions over individual volumes when titles match equally.

    Args:
        books: List of book dicts from JSON search_books_json API
        search_title: Title we're searching for
        search_authors: Authors we're searching for (optional)
        log_func: Logging function

    Returns:
        romanceio_id of best match, or None if no good match found
    """
    if not books:
        return None

    log_func(f"Matching against {len(books)} search results...")

    # Prepare search criteria
    title_tokens = _get_title_tokens(search_title)
    author_tokens = []
    if search_authors:
        for author in search_authors:
            author_tokens.extend(_get_title_tokens(author))

    matcher = create_title_author_matcher(search_title, title_tokens, author_tokens)

    # Check if search title has series info (same logic as HTML search)
    search_title_lower = lower(search_title)
    has_series_info = bool(
        re.search(
            r"#\d+|book\s+\d+|vol\.?\s*\d+|part\s+(one|two|three|four|five|six|seven|eight|nine|ten|\d+)|\b\d+$",
            str(search_title_lower),
            re.IGNORECASE,
        )
    )

    best_match_id = None
    best_score = 0
    match_details = []

    for i, book in enumerate(books):
        romanceio_id = book.get("_id")
        if not romanceio_id:
            continue

        info = book.get("info", {})
        book_title = info.get("title", "")

        book_authors = []
        authors_list = book.get("authors", [])
        if authors_list:
            for author_obj in authors_list:
                if isinstance(author_obj, dict):
                    author_name = author_obj.get("name", "")
                    if author_name:
                        book_authors.append(author_name)

        is_match, score = matcher(book_title, book_authors)

        # Apply omnibus preference logic only when search doesn't have series info (matches HTML search)
        adjusted_score = score
        if is_match and not has_series_info:
            # Search didn't specify series info, so prefer omnibus/boxed sets over individual volumes
            if _has_volume_range(book_title):
                # Bonus for boxed sets/complete editions (e.g., "#1-5")
                adjusted_score += 100
            elif _has_individual_volume(book_title):
                # Penalty for individual volumes (e.g., "Vol. 2")
                adjusted_score -= 50

        # Store details for logging only if no match is found
        match_details.append(
            f"  [{i+1}] '{book_title}' by {book_authors} - "
            f"Match: {is_match}, Score: {score}, Adjusted: {adjusted_score}"
        )

        if is_match and adjusted_score > best_score:
            best_score = adjusted_score
            best_match_id = romanceio_id

    if best_match_id:
        log_func(f"✓ Best match (Romance.io ID): {best_match_id} (score: {best_score})")
        return best_match_id

    # Log details only when no match found
    for detail in match_details:
        log_func(detail)
    log_func("✗ No good match found")
    return None
