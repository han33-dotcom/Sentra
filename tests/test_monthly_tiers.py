"""Publication failure, hot expiry and compatibility on synthetic monthly fixtures."""
from contextlib import nullcontext
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import pyarrow.parquet as pq

from sentra import monthly_tiers as m, tiers
from sentra.errors import SentraError
from sentra.shared import Limits,CapacityStop
from test_tiers import ROWS,NOW,Bucket


class MonthlyTests(unittest.TestCase):
    def reader(self):
        reader=Mock(read_bytes=0)
        reader.db.transaction.return_value=nullcontext()
        reader.usage.return_value={'database_bytes':1000,'object_bytes':1000,'audit_bytes':1000,'egress_bytes':1000}
        reader.read_partition.side_effect=lambda query,values:list(ROWS[query.split('(')[1].split(')')[0]])
        return reader

    def inventory(self):
        # SQL partition assignment is covered against PostgreSQL in test_compaction_db.
        return {f'{name}/2026-10':[len(rows),'a','b'] for name,rows in ROWS.items()}, {name:(name,()) for name in ROWS}

    def test_legacy_equivalence_reuse_hot_expiry_and_corrupt_cache_rejection(self):
        reader=self.reader(); bucket=Bucket(); limits=Limits()
        with patch.object(m,'inventory',return_value=self.inventory()):
            objects,report=m.build(reader,limits,bucket,now=NOW)
            tiers.publish(objects,report,bucket,reader,limits)
            with tempfile.TemporaryDirectory() as folder:
                tiers.fetch(bucket,folder)
                flat=m.materialize(objects,folder)
                hot,warm=tiers.hr_tables(ROWS['hr_raw'],ROWS['hr_minute'],NOW)
                expected={'measurements.parquet':tiers.measurements_table(ROWS['measurements']),
                          'sessions.parquet':tiers.sessions_table(ROWS['sessions']),
                          **{f'hr_raw/{p}.parquet':table for p,table in hot.items()},
                          **{f'hr_minute/{p}.parquet':table for p,table in warm.items()}}
                self.assertEqual(set(flat),set(expected))
                for key,table in expected.items(): self.assertEqual(pq.read_table(io.BytesIO(flat[key])).to_pylist(),table.to_pylist())
            reader.read_partition.reset_mock()
            expired,expiration=m.build(reader,limits,bucket,now=NOW+timedelta(days=32))
            reader.read_partition.assert_not_called()
            self.assertFalse(any('/hr_raw/' in key for key in expired))
            self.assertTrue(any('/hr_minute/' in key for key in expired))
            self.assertFalse(expiration['unchanged'])
            location=next(iter(report['locations'].values()))
            bucket.objects[location]=b'corrupt'
            with self.assertRaisesRegex(SentraError,'integrity'): m.build(reader,limits,bucket,now=NOW)

    def test_failed_manifest_keeps_previous_complete_publication_and_retry_succeeds(self):
        reader=self.reader(); bucket=Bucket(); limits=Limits()
        with patch.object(m,'inventory',return_value=self.inventory()):
            objects,report=m.build(reader,limits,bucket,now=NOW)
        tiers.publish(objects,report,bucket,reader,limits)
        before=bucket.objects['size_report.json']
        # Unchanged objects need no writes: only manifest POST is attempted.
        bucket.fail_at=0
        with self.assertRaisesRegex(SentraError,'manifest'): tiers.publish(objects,report,bucket,reader,limits)
        self.assertEqual(bucket.objects['size_report.json'],before)
        bucket.fail_at=None
        self.assertEqual(tiers.publish(objects,report,bucket,reader,limits)['uploaded'],1)
        with tempfile.TemporaryDirectory() as folder: tiers.fetch(bucket,folder)

    def test_total_capacity_check_happens_before_upload(self):
        reader=self.reader(); bucket=Bucket(); guard=Mock()
        guard.check.side_effect=CapacityStop('full')
        with patch.object(m,'inventory',return_value=self.inventory()):
            objects,report=m.build(reader,Limits(),bucket,now=NOW)
        with self.assertRaises(CapacityStop): tiers.publish(objects,report,bucket,reader,guard,extra_bytes=100)
        self.assertEqual(bucket.objects,{})

    def test_publication_lock_rejects_overlap(self):
        reader=Mock()
        reader.db.execute.return_value.fetchone.return_value=(False,)
        with self.assertRaisesRegex(SentraError,'publisher'): m.lock(reader)

    def test_board_upload_retry_uses_tier_hashes_when_collection_time_is_unchanged(self):
        from sentra import wellness_refresh as w
        from sentra.processing.board import BOARD_VERSION
        from sentra.processing.pipeline import ASSESSMENT_VERSION
        from test_wellness_board import Bucket as BoardBucket
        reader=self.reader(); bucket=BoardBucket(); limits=Limits()
        source=NOW.isoformat()
        old={'board_version':BOARD_VERSION,'assessment_version':ASSESSMENT_VERSION,
             'source_run':source,'tier_sha256':{'old':'old'},'people':[]}
        bucket.objects[w.BOARD_KEY]=json.dumps(old).encode()
        with patch.object(m,'inventory',return_value=self.inventory()):
            objects,report=m.build(reader,limits,bucket,now=NOW)
        bucket.fail=w.BOARD_KEY
        with patch.object(w,'latest_run',return_value=source), patch.object(m,'build',return_value=(objects,report)):
            with self.assertRaisesRegex(SentraError,'Board upload failed'):
                w.refresh(reader,limits,bucket,now=NOW,incremental=True,log=lambda *_:None)
            self.assertEqual(json.loads(bucket.objects[w.BOARD_KEY]),old)
            # The tier manifest already advanced. A retry still must publish the board.
            report['unchanged']=True; bucket.fail=None
            result=w.refresh(reader,limits,bucket,now=NOW,incremental=True,log=lambda *_:None)
            self.assertEqual(result['status'],'published')
            with patch.object(w,'run',side_effect=AssertionError('unchanged board must not reprocess')):
                result=w.refresh(reader,limits,bucket,now=NOW,incremental=True,log=lambda *_:None)
            self.assertEqual(result['status'],'skipped')
