"""Encrypt or decrypt a PostgreSQL custom-format dump for short-term recovery."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"CCM-BACKUP-1\n"
ASSOCIATED_DATA = b"competitor-closure-map/postgres-dump/v1"


def key_from_environment() -> bytes:
    encoded = os.environ.get("BACKUP_ENCRYPTION_KEY", "")
    try:
        key = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("BACKUP_ENCRYPTION_KEY must be base64") from error
    if len(key) != 32:
        raise ValueError("BACKUP_ENCRYPTION_KEY must contain 32 bytes")
    return key


def encrypt(source: Path, destination: Path, key: bytes) -> None:
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, source.read_bytes(), ASSOCIATED_DATA)
    destination.write_bytes(MAGIC + nonce + ciphertext)
    destination.chmod(0o600)


def decrypt(source: Path, destination: Path, key: bytes) -> None:
    payload = source.read_bytes()
    if not payload.startswith(MAGIC) or len(payload) <= len(MAGIC) + 12 + 16:
        raise ValueError("Invalid backup format")
    nonce = payload[len(MAGIC):len(MAGIC) + 12]
    plaintext = AESGCM(key).decrypt(nonce, payload[len(MAGIC) + 12:], ASSOCIATED_DATA)
    destination.write_bytes(plaintext)
    destination.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("encrypt", "decrypt"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    key = key_from_environment()
    if args.mode == "encrypt":
        encrypt(args.source, args.destination, key)
    else:
        decrypt(args.source, args.destination, key)


if __name__ == "__main__":
    main()
