"""Review 2026-11-21 S4: passphrase-derived keys need salt and work.

``EVALITH_SECRET_KEY`` set to a human passphrase used to derive the
Fernet key with a single unsalted SHA-256. Anyone holding a database
backup could GPU-brute-force the passphrase offline (no salt, no
iterations, precomputable across installs). The derivation now uses
PBKDF2-HMAC-SHA256 with 600k iterations and a per-install random salt
stored beside the key material.

Ciphertexts written by the old derivation stay readable: decryption
falls back to the legacy key so existing installs keep working, while
every new write uses the salted key.
"""

import base64
import hashlib
from pathlib import Path

import pytest

from evalith.security import CredentialCipher

PASSPHRASE = "correct horse battery staple"


def cipher_for(tmp_path, passphrase=PASSPHRASE):
    return CredentialCipher(passphrase, Path(tmp_path))


def legacy_encrypt(passphrase, value):
    legacy_key = base64.urlsafe_b64encode(
        hashlib.sha256(passphrase.encode("utf-8")).digest()
    )
    from cryptography.fernet import Fernet

    return Fernet(legacy_key).encrypt(value.encode("utf-8")).decode("ascii")


class TestSaltedDerivation:
    def test_two_installs_derive_different_keys(self, tmp_path):
        first = cipher_for(tmp_path / "a")
        second = cipher_for(tmp_path / "b")
        token = first.encrypt("api-key-material")
        assert first.decrypt(token) == "api-key-material"
        # Same passphrase, different install salt: the other install
        # cannot read this token.
        try:
            second.decrypt(token)
            raise AssertionError("cross-install decrypt should fail")
        except RuntimeError:
            pass

    def test_salt_file_is_created_once_with_tight_permissions(self, tmp_path):
        data = tmp_path / "install"
        cipher_for(data)
        salt_file = data / "kdf.salt"
        assert salt_file.exists()
        assert oct(salt_file.stat().st_mode & 0o777) == "0o600"
        first = salt_file.read_bytes()
        cipher_for(data)
        assert salt_file.read_bytes() == first

    def test_fernet_key_passphrases_bypass_derivation(self, tmp_path):
        from cryptography.fernet import Fernet

        key = Fernet.generate_key().decode("ascii")
        cipher = CredentialCipher(key, Path(tmp_path))
        token = cipher.encrypt("v")
        assert cipher.decrypt(token) == "v"
        assert not (tmp_path / "kdf.salt").exists()


class TestLegacyCiphertextsStayReadable:
    def test_legacy_single_hash_ciphertext_decrypts(self, tmp_path):
        cipher = cipher_for(tmp_path)
        legacy_token = legacy_encrypt(PASSPHRASE, "old-secret")
        assert cipher.decrypt(legacy_token) == "old-secret"

    def test_new_writes_use_the_salted_key(self, tmp_path):
        from cryptography.fernet import Fernet

        cipher = cipher_for(tmp_path)
        token = cipher.encrypt("new-secret")
        assert cipher.decrypt(token) == "new-secret"
        # A token written by the salted key must NOT be a legacy-key
        # ciphertext (otherwise the salt added nothing).
        legacy = Fernet(
            base64.urlsafe_b64encode(
                hashlib.sha256(PASSPHRASE.encode("utf-8")).digest()
            )
        )
        with pytest.raises(Exception):
            legacy.decrypt(token.encode("ascii"))
