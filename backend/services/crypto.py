"""Fernet-based credential encryption/decryption service.

Uses the ENCRYPTION_KEY environment variable as the Fernet symmetric key.
The key must be a valid Fernet key (32 url-safe base64-encoded bytes).

Generate a key with:
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Security notes:
  - The key is read lazily inside each function call (not cached at module level)
    so that test fixtures can set os.environ["ENCRYPTION_KEY"] before calling.
  - NEVER log the key or any plaintext credential value.
  - Fernet uses AES-128-CBC + HMAC-SHA256 with a random IV per encryption, so
    encrypting the same value twice produces different ciphertexts (no repetition leak).

Threat mitigations:
  T-02-03: credentials stored as Fernet blobs; key only in .env (never in git).
  T-02-04: key never logged; no plaintext in log args.
"""

import os

from cryptography.fernet import Fernet


def encrypt_credential(plaintext: str) -> str:
    """Encrypt a plaintext string using Fernet symmetric encryption.

    Args:
        plaintext: The credential value to encrypt (e.g. a Jira API token).

    Returns:
        A base64-encoded Fernet token string safe to store in the database.

    Raises:
        KeyError: If ENCRYPTION_KEY env var is not set.
        ValueError: If ENCRYPTION_KEY is not a valid Fernet key.
    """
    key = os.environ["ENCRYPTION_KEY"].encode()
    return Fernet(key).encrypt(plaintext.encode()).decode()


def decrypt_credential(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted ciphertext string back to plaintext.

    Args:
        ciphertext: A base64-encoded Fernet token as stored in the database.

    Returns:
        The original plaintext string.

    Raises:
        cryptography.fernet.InvalidToken: If the ciphertext is invalid or the
            key does not match the key used to encrypt.
        KeyError: If ENCRYPTION_KEY env var is not set.
    """
    key = os.environ["ENCRYPTION_KEY"].encode()
    return Fernet(key).decrypt(ciphertext.encode()).decode()
