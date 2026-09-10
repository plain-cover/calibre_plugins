"""Verify a downloaded file against a repository-pinned SHA-512 digest."""

import argparse
import hashlib
import os
import re

SHA512_PATTERN = re.compile(r"[0-9a-fA-F]{128}")


def sha512_file(path, chunk_size=1024 * 1024):
    """Return the lowercase SHA-512 digest for *path* without loading it all in memory."""
    digest = hashlib.sha512()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha512(path, expected):
    """Raise ValueError when *expected* is malformed or does not match *path*."""
    if not SHA512_PATTERN.fullmatch(expected):
        raise ValueError("Expected SHA-512 must contain exactly 128 hexadecimal characters")
    actual = sha512_file(path)
    if actual != expected.lower():
        raise ValueError(f"SHA-512 mismatch for {path}: expected {expected.lower()}, got {actual}")
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("expected_sha512")
    args = parser.parse_args()
    digest = verify_sha512(args.path, args.expected_sha512)
    print(f"PASS: SHA-512 verified: {digest}  {os.path.abspath(args.path)}")


if __name__ == "__main__":
    main()
