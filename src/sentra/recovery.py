"""Passphrase-protected recovery of the OS-held key; no plaintext key output."""
import base64
import getpass
import json
import os

from cryptography.fernet import Fernet,InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
import keyring

from .errors import SentraError
from .vault import atomic_write


def derived(password,salt):
    if len(password)<16: raise SentraError('Use a separate recovery passphrase of at least 16 characters.')
    return Fernet(base64.urlsafe_b64encode(Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password.encode())))


def wrap_key(key,password):
    Fernet(key)
    salt=os.urandom(16)
    return json.dumps({'format':1,'salt':base64.b64encode(salt).decode(),
                       'wrapped_key':derived(password,salt).encrypt(key).decode()}).encode()


def unwrap_key(value,password):
    try:
        if len(value)>4096: raise ValueError
        envelope=json.loads(value)
        salt=base64.b64decode(envelope['salt'],validate=True)
        if envelope['format']!=1 or len(salt)!=16: raise ValueError
        key=derived(password,salt).decrypt(envelope['wrapped_key'].encode())
        Fernet(key)
        return key
    except (ValueError,KeyError,TypeError,InvalidToken):
        raise SentraError('Recovery envelope/passphrase invalid; existing OS key unchanged.') from None


def key_recovery(path,*,save):
    backend=keyring.get_keyring()
    if not type(backend).__module__.startswith(('keyring.backends.Windows','keyring.backends.macOS','keyring.backends.SecretService')):
        raise SentraError('A supported OS credential store is required for key recovery.')
    current=keyring.get_password('sentra-audit','local-encryption-key')
    password=getpass.getpass('Recovery passphrase (never displayed): ')
    if save:
        if not current: raise SentraError('No existing OS key to protect.')
        if password!=getpass.getpass('Repeat recovery passphrase: '): raise SentraError('Passphrases differ.')
        if path.exists(): raise SentraError('Recovery envelope exists; preserve it or choose a new private filename.')
        atomic_write(path,wrap_key(current.encode(),password))
    else:
        key=unwrap_key(path.read_bytes(),password).decode()
        if current and current!=key: raise SentraError('Another OS key already exists; restore using a separate OS account instead of overwriting it.')
        if not current: keyring.set_password('sentra-audit','local-encryption-key',key)
