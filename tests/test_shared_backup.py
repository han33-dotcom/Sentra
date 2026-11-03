import importlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from cryptography.fernet import Fernet


class BackupTests(unittest.TestCase):
    def module(self):
        try: return importlib.import_module('sentra.shared_backup')
        except ModuleNotFoundError: self.fail('Encrypted shared backup not implemented')

    def test_backup_roundtrip_rejects_corruption_and_unsafe_paths(self):
        m = self.module()
        cipher = Fernet(Fernet.generate_key())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            writer = m.BackupWriter(root,cipher,max_bytes=1_000_000)
            writer.write('records-0001',b'{"example":7}\n',rows=1)
            path = writer.finish({'kind':'synthetic'})
            reader = m.BackupReader(path,cipher)
            self.assertEqual(reader.read('records-0001'),b'{"example":7}\n')
            with self.assertRaises(m.SentraError): writer.write('../escape',b'x')
            target = path.parent / 'records-0001.enc'
            target.write_bytes(target.read_bytes()[:-4] + b'bad!')
            with self.assertRaises(m.SentraError): reader.read('records-0001')

    def test_backup_limit_is_checked_before_writing(self):
        m = self.module()
        with tempfile.TemporaryDirectory() as directory:
            writer = m.BackupWriter(Path(directory),Fernet(Fernet.generate_key()),max_bytes=100)
            with self.assertRaises(m.CapacityStop): writer.write('records',b'x' * 200)
            self.assertFalse((writer.folder / 'records.enc').exists())

    def test_row_fingerprint_is_order_independent_but_detects_changed_values(self):
        m = self.module()
        a,b = {'id':'a','value':7},{'id':'b','value':8}
        self.assertEqual(m.row_fingerprint([a,b]),m.row_fingerprint([b,a]))
        self.assertNotEqual(m.row_fingerprint([a,b]),m.row_fingerprint([a,{**b,'value':9}]))

    def test_offline_verify_checks_counts_fingerprints_and_originals(self):
        import gzip, hashlib, json
        m = self.module(); cipher = Fernet(Fernet.generate_key())
        rows = {t: [{'table': t, 'n': i} for i in range(2)] for t in m.TABLES}
        original = gzip.compress(b'{"page":1}')
        location = 'sentra-originals/p01/x.json.gz'
        with tempfile.TemporaryDirectory() as directory:
            def backup(changed=None):
                writer = m.BackupWriter(Path(directory), cipher)
                for t, items in rows.items():
                    stored = items if t != changed else items[:1] + [{'table': t, 'n': 99}]
                    writer.write(f'{t}-00000', ''.join(json.dumps(r, sort_keys=True, separators=(',', ':')) + '\n' for r in stored).encode(), rows=2)
                writer.write('raw-' + hashlib.sha256(location.encode()).hexdigest(), original)
                return m.BackupReader(writer.finish({'tables': {t: 2 for t in m.TABLES},
                    'table_fingerprints': {t: m.row_fingerprint(r) for t, r in rows.items()},
                    'objects': {location: [hashlib.sha256(b'{"page":1}').hexdigest(), len(original)]}}), cipher)
            result = m.verify_backup(backup())
            self.assertEqual((result['status'], result['tables']['measurements'], result['originals']), ('verified', 2, 1))
            with self.assertRaises(m.SentraError):
                m.verify_backup(backup(changed='records'))  # same count, altered value

    def test_incomplete_inventory_refused_before_cloud_changes(self):
        m=self.module(); cipher=Fernet(Fernet.generate_key())
        with tempfile.TemporaryDirectory() as directory:
            writer=m.BackupWriter(Path(directory),cipher)
            reader=m.BackupReader(writer.finish({'tables':{'records':0},'table_fingerprints':{},'objects':{}}),cipher)
            called=[]
            backend=SimpleNamespace(lock=lambda:called.append('lock'))
            with self.assertRaises(m.SentraError): m.restore_backup(reader,backend,None)
            self.assertEqual(called,[])
