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
        original = gzip.compress(b'{"page":1}')
        location = 'sentra-originals/p01/x.json.gz'
        digest = hashlib.sha256(b'{"page":1}').hexdigest()
        rows = {t: [{'table': t, 'n': i} for i in range(2)] for t in m.TABLES}
        rows['raw_response_manifest'] = [{'n': i, 'object_location': location, 'content_sha256': digest,
                                          'compressed_bytes': len(original)} for i in range(2)]
        raw_name = 'raw-' + hashlib.sha256(location.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            def backup(changed=None, objects=None, extra=None, chunks=1):
                writer = m.BackupWriter(Path(directory), cipher)
                for t, items in rows.items():
                    stored = items if t != changed else items[:1] + [{'table': t, 'n': 99}]
                    for part in range(chunks):  # the same rows split over several chunks
                        writer.write(f'{t}-{part:05d}', ''.join(json.dumps(r, sort_keys=True, separators=(',', ':')) + '\n'
                                                               for r in stored[part::chunks]).encode())
                writer.write(raw_name, original)
                if extra:
                    writer.write(extra, b'x')
                manifest = writer.finish({'tables': {t: 2 for t in m.TABLES},
                    'table_fingerprints': {t: m.row_fingerprint(r) for t, r in rows.items()},
                    'objects': {location: [digest, len(original)]} if objects is None else objects})
                return m.BackupReader(manifest, cipher), manifest.parent
            reader, _ = backup(chunks=2)
            result = m.verify_backup(reader)
            self.assertEqual((result['status'], result['tables']['measurements'], result['originals'], result['members']),
                             ('verified', 2, 1, 15))
            failures = {'altered value, same count': backup(changed='records')[0],
                        'original row without an inventoried object': backup(objects={})[0],
                        'undeclared kind of member': backup(extra='notes-00000')[0]}
            reader, folder = backup()
            (folder / (raw_name + '.enc')).unlink()
            failures['declared original missing on disk'] = reader
            for case, broken in failures.items():
                with self.subTest(case), self.assertRaises(m.SentraError):
                    m.verify_backup(broken)

    def test_offline_verify_memory_is_bounded_by_one_chunk_not_the_table(self):
        import json, tracemalloc
        m = self.module(); cipher = Fernet(Fernet.generate_key())
        row = lambda i: {'n': i, 'pad': 'x' * 500}
        line = lambda i: json.dumps(row(i), sort_keys=True, separators=(',', ':')) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            writer = m.BackupWriter(Path(directory), cipher)
            for t in m.TABLES:
                chunks = 32 if t == 'measurements' else 1
                n = 512 if t == 'measurements' else 0
                for part in range(chunks):
                    writer.write(f'{t}-{part:05d}', ''.join(line(i) for i in range(part * n, (part + 1) * n)).encode())
            reader = m.BackupReader(writer.finish({'tables': {t: 16_384 if t == 'measurements' else 0 for t in m.TABLES},
                'table_fingerprints': {t: m.row_fingerprint(row(i) for i in range(16_384)) if t == 'measurements'
                                       else m.row_fingerprint([]) for t in m.TABLES}, 'objects': {}}), cipher)
            tracemalloc.start()
            result = m.verify_backup(reader)
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
        self.assertEqual(result['tables']['measurements'], 16_384)
        self.assertLess(peak, 4_000_000)  # the whole table is ~8.5 MB of JSON text alone

    def test_empty_audit_restore_requires_naming_the_configured_target(self):
        from argparse import Namespace
        from unittest import mock
        from sentra import shared_cli
        private = Path('.private').resolve()
        args = lambda ref: Namespace(command='shared-restore', config=Path('config/local.toml'), empty_audit=True,
                                     target_project=ref, backup=private / 'backups' / 'b' / 'manifest.enc')
        with mock.patch.object(shared_cli, 'local_cipher'), \
                mock.patch.object(shared_cli, 'load_connection', return_value=SimpleNamespace(private_dir=private)), \
                mock.patch.object(shared_cli, 'read_shared', return_value=({'url': 'https://abcd1234.supabase.co'}, None, private)), \
                mock.patch.object(shared_cli, 'SharedBackend'), \
                mock.patch.object(shared_cli, 'connect_db', side_effect=AssertionError('reached the database')) as connect:
            for ref in (None, 'live0000'):
                with self.subTest(ref=ref), self.assertRaises(shared_cli.SentraError):
                    shared_cli.run_command(args(ref))
            connect.assert_not_called()

    def test_full_backup_uses_the_admin_role_and_partial_backups_do_not(self):
        from argparse import Namespace
        from unittest import mock
        from sentra import shared_cli
        private = Path('.private').resolve()
        args = lambda **kw: Namespace(command='shared-backup', config=Path('config/local.toml'),
                                      **{'participant': None, 'provider': None, 'dataset': None, 'audit_only': False, **kw})
        admin = mock.Mock()
        with mock.patch.object(shared_cli, 'local_cipher'), mock.patch.object(shared_cli, 'require_agreement'), \
                mock.patch.object(shared_cli, 'load_connection', return_value=SimpleNamespace(private_dir=private)), \
                mock.patch.object(shared_cli, 'read_shared', return_value=({}, None, private)), \
                mock.patch.object(shared_cli, 'SharedBackend'), mock.patch.object(shared_cli, 'read_admin'), \
                mock.patch.object(shared_cli, 'connect_db', return_value=admin), mock.patch('builtins.print'), \
                mock.patch.object(shared_cli, 'make_backup', return_value=private / 'b' / 'manifest.enc') as backup:
            shared_cli.run_command(args())
            self.assertIs(backup.call_args.kwargs['admin_db'], admin)
            admin.close.assert_called_once()
            for partial in ({'participant': 'p01'}, {'audit_only': True}):
                shared_cli.run_command(args(**partial))
                self.assertIsNone(backup.call_args.kwargs['admin_db'])

    def test_incomplete_inventory_refused_before_cloud_changes(self):
        m=self.module(); cipher=Fernet(Fernet.generate_key())
        with tempfile.TemporaryDirectory() as directory:
            writer=m.BackupWriter(Path(directory),cipher)
            reader=m.BackupReader(writer.finish({'tables':{'records':0},'table_fingerprints':{},'objects':{}}),cipher)
            called=[]
            backend=SimpleNamespace(lock=lambda:called.append('lock'))
            with self.assertRaises(m.SentraError): m.restore_backup(reader,backend,None)
            self.assertEqual(called,[])
