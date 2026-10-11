import importlib
import unittest
from cryptography.fernet import Fernet


class RecoveryTests(unittest.TestCase):
    def test_encrypted_key_envelope_rejects_wrong_passphrase(self):
        try: m=importlib.import_module('sentra.recovery')
        except ModuleNotFoundError: self.fail('Recovery key envelope not implemented')
        key=Fernet.generate_key()
        wrapped=m.wrap_key(key,'synthetic long passphrase')
        self.assertNotIn(key,wrapped)
        self.assertEqual(m.unwrap_key(wrapped,'synthetic long passphrase'),key)
        with self.assertRaises(m.SentraError): m.unwrap_key(wrapped,'different long passphrase')
        with self.assertRaises(m.SentraError): m.wrap_key(key,'short')
