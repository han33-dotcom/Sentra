"""Aggregate capacity snapshots and observed growth; no participant readings are involved."""
import json
from pathlib import Path
import tempfile
import unittest

from sentra import capacity


class Backend:
    def __init__(self, usage): self._usage, self.reserved = usage, 0
    def reserve(self, amount): self.reserved += amount
    def usage(self): return self._usage

    class db:
        @staticmethod
        def execute(query, values=()):
            rows = {'pg_total_relation_size': [('audit.measurements', 1000)],
                    'audit.measurements': [('p01', 'whoop', 'recovery', 3)],
                    'audit.collection_runs': [('p01', 'whoop', 'succeeded', 2)]}
            found = next(v for k, v in rows.items() if k in query)
            return type('R', (), {'fetchall': lambda _s: found})()


class CapacityTests(unittest.TestCase):
    def test_snapshot_holds_only_aggregates_and_growth_is_per_day(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'measurements' / 'capacity.jsonl'
            first = capacity.snapshot(Backend({'database_bytes': 100, 'object_bytes': 10, 'egress_bytes': None}))
            self.assertEqual(first['runs'], [{'participant_id': 'p01', 'provider': 'whoop', 'status': 'succeeded', 'count': 2}])
            capacity.append(log, first)
            self.assertEqual(capacity.growth(log)['snapshots'], 1)
            second = {**first, 'taken_at': '2099-01-01T00:00:00+00:00', 'usage': {'database_bytes': 100 + 2 * 86_400, 'object_bytes': 10}}
            first['taken_at'] = '2098-12-30T00:00:00+00:00'
            log.write_text(json.dumps(first) + '\n' + json.dumps(second) + '\n', encoding='utf-8')
            result = capacity.growth(log)
            self.assertEqual((result['days'], result['database_bytes_per_day']), (2.0, 86_400))
            self.assertIsNone(result['egress_bytes_per_day'])  # the two snapshots are in different months

    def test_egress_growth_never_spans_a_monthly_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'capacity.jsonl'
            snap = lambda at, egress: {'taken_at': at, 'usage': {'database_bytes': 0, 'object_bytes': 0, 'egress_bytes': egress}}
            entries = [snap('2026-11-30T00:00:00+00:00', 3_000_000_000), snap('2026-12-01T00:00:00+00:00', 50_000_000),
                       snap('2026-12-03T00:00:00+00:00', 150_000_000)]
            log.write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')
            result = capacity.growth(log)
            self.assertEqual((result['egress_bytes_per_day'], result['egress_from']), (50_000_000, '2026-12-01T00:00:00+00:00'))
            log.write_text(''.join(json.dumps(e) + '\n' for e in entries[:2]), encoding='utf-8')
            self.assertIsNone(capacity.growth(log)['egress_bytes_per_day'])


if __name__ == '__main__':
    unittest.main()
