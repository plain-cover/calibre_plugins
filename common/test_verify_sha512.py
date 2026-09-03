"""Tests for repository-pinned download integrity verification."""

import hashlib

import pytest

from common.verify_sha512 import sha512_file, verify_sha512


def test_verify_sha512_accepts_matching_digest(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"calibre test artifact")
    expected = hashlib.sha512(artifact.read_bytes()).hexdigest()
    assert verify_sha512(str(artifact), expected.upper()) == expected
    assert sha512_file(str(artifact), chunk_size=3) == expected


def test_verify_sha512_rejects_mismatch(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"unexpected content")
    with pytest.raises(ValueError, match="SHA-512 mismatch"):
        verify_sha512(str(artifact), "0" * 128)


@pytest.mark.parametrize("invalid", ("", "abc", "g" * 128, "0" * 127, "0" * 129))
def test_verify_sha512_rejects_malformed_digest(tmp_path, invalid):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"content")
    with pytest.raises(ValueError, match="exactly 128 hexadecimal"):
        verify_sha512(str(artifact), invalid)
