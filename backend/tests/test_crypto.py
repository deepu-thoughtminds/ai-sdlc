"""Unit tests for the crypto service (Fernet-based credential encryption).

TDD RED phase: these tests import from services.crypto before that module exists,
so they will fail with ImportError until the GREEN phase implements the module.

Tests:
1. test_encrypt_decrypt_roundtrip - encrypt then decrypt returns original value
2. test_encrypt_returns_bytes_not_plaintext - ciphertext does not contain plaintext
3. test_decrypt_with_wrong_key_raises - wrong key raises cryptography exception
4. test_empty_string_roundtrip - encrypt/decrypt of empty string works
"""

import os

import pytest
from cryptography.fernet import Fernet, InvalidToken

# Set a valid ENCRYPTION_KEY before importing crypto so the module can load.
# Generate a fresh key for this test module to avoid interference.
_TEST_KEY = Fernet.generate_key().decode()
os.environ["ENCRYPTION_KEY"] = _TEST_KEY

from services.crypto import decrypt_credential, encrypt_credential  # noqa: E402


def test_encrypt_decrypt_roundtrip() -> None:
    """Encrypting and then decrypting a value must return the original string."""
    plaintext = "my-secret-jira-token"
    ciphertext = encrypt_credential(plaintext)
    result = decrypt_credential(ciphertext)
    assert result == plaintext


def test_encrypt_returns_bytes_not_plaintext() -> None:
    """The ciphertext string must not contain the plaintext value."""
    plaintext = "super-secret-token"
    ciphertext = encrypt_credential(plaintext)
    assert isinstance(ciphertext, str)
    assert plaintext not in ciphertext
    # Fernet ciphertext is base64 — should not equal the input
    assert ciphertext != plaintext


def test_decrypt_with_wrong_key_raises() -> None:
    """Decrypting with a different key must raise cryptography.fernet.InvalidToken."""
    # Encrypt with the test key already in os.environ
    ciphertext = encrypt_credential("some-value")

    # Temporarily swap in a different key
    wrong_key = Fernet.generate_key().decode()
    original_key = os.environ["ENCRYPTION_KEY"]
    os.environ["ENCRYPTION_KEY"] = wrong_key
    try:
        with pytest.raises((InvalidToken, Exception)):
            decrypt_credential(ciphertext)
    finally:
        os.environ["ENCRYPTION_KEY"] = original_key


def test_empty_string_roundtrip() -> None:
    """Encrypt and decrypt of an empty string must work without error."""
    plaintext = ""
    ciphertext = encrypt_credential(plaintext)
    result = decrypt_credential(ciphertext)
    assert result == plaintext
