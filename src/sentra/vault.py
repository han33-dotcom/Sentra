"""Local encrypted state; OS credential storage holds the encryption key."""
import json
import os
from pathlib import Path
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from filelock import FileLock
import keyring

from .errors import SentraError


def local_cipher(*, create=False):
    # Fail closed rather than use a plaintext file backend.
    backend = keyring.get_keyring()
    if not type(backend).__module__.startswith(("keyring.backends.Windows", "keyring.backends.macOS",
                                               "keyring.backends.SecretService")):
        raise SentraError("No supported OS credential store. Configure Windows Credential Locker, macOS Keychain or Secret Service.")
    try:
        key = keyring.get_password("sentra-audit", "local-encryption-key")
        if key is None and create:
            key = Fernet.generate_key().decode("ascii")
            keyring.set_password("sentra-audit", "local-encryption-key", key)
        if key is None:
            raise SentraError("Run sentra init-vault first.")
        return Fernet(key.encode("ascii"))
    except SentraError:
        raise
    except Exception:
        raise SentraError("Cannot access the OS credential store; no data was decrypted.") from None


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".sentra-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class TokenVault:
    def __init__(self, root: Path, provider: str, participant: str, cipher):
        self.path = root / "tokens" / f"{provider}-{participant}.enc"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = cipher
        self.lock = FileLock(str(self.path) + ".lock", timeout=10)

    def read(self):
        try:
            return json.loads(self.cipher.decrypt(self.path.read_bytes()))
        except (OSError, ValueError, InvalidToken):
            raise SentraError("No readable connection state. Authorize/reconnect this participant.") from None

    def write(self, value):
        try:
            atomic_write(self.path, self.cipher.encrypt(json.dumps(value).encode("utf-8")))
        except OSError:
            raise SentraError("Cannot persist encrypted connection state; stop and reconnect if tokens rotated.") from None
