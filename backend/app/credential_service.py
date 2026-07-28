from __future__ import annotations

import os

from cryptography.fernet import Fernet

from .settings import settings


def _fernet() -> Fernet:
    key_path = settings.credential_key_file
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with key_path.open("xb") as handle:
                handle.write(Fernet.generate_key())
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        except FileExistsError:
            pass
    return Fernet(key_path.read_bytes().strip())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
