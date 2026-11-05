from datetime import date
import unittest
from unittest.mock import Mock

from sentra.errors import SentraError
from sentra.shared import Limits, CapacityStop


class ViewerReaderTests(unittest.TestCase):
    def module(self):
        try:
            from sentra import viewer_reader
            return viewer_reader
        except ImportError:
            self.fail('Viewer reader not implemented')

    def test_access_rechecked_before_every_read_or_original(self):
        m = self.module()
        denied = Mock(side_effect=SentraError('denied'))
        db = Mock()
        reader = m.ViewerReader({}, Limits(), denied, db=db)
        for call in (reader.catalog, reader.usage,
                     lambda:reader.measurements(m.Selection('p99','whoop','sleep',date(2026,10,7),date(2026,10,8))),
                     lambda:reader.original('a'*64, m.Selection('p99','whoop','sleep',date(2026,10,7),date(2026,10,8)))):
            with self.assertRaisesRegex(SentraError,'denied'): call()
        db.execute.assert_not_called()

    def test_organization_rows_fall_back_to_none_without_the_org_schema(self):
        import psycopg
        m=self.module()
        for missing in (psycopg.errors.UndefinedTable, psycopg.errors.InvalidSchemaName):
            db=Mock()
            db.cursor.return_value.__enter__=Mock(return_value=Mock(execute=Mock(side_effect=missing('absent'))))
            db.cursor.return_value.__exit__=Mock(return_value=False)
            reader=m.ViewerReader({},Limits(),lambda:'officer@a.test',db=db,budget_db=Mock())
            with self.subTest(error=missing.__name__):
                self.assertEqual(reader.organization_rows(),([],[]))
                db.rollback.assert_called_once()
        db=Mock()
        db.cursor.return_value.__enter__=Mock(return_value=Mock(execute=Mock(side_effect=psycopg.OperationalError('down'))))
        db.cursor.return_value.__exit__=Mock(return_value=False)
        reader=m.ViewerReader({},Limits(),lambda:'officer@a.test',db=db,budget_db=Mock())
        with self.assertRaisesRegex(SentraError,'unavailable'):reader.organization_rows()
        denied=Mock(side_effect=SentraError('denied'));db=Mock()
        with self.assertRaisesRegex(SentraError,'denied'):
            m.ViewerReader({},Limits(),denied,db=db).organization_rows()
        db.cursor.assert_not_called()

    def test_board_and_group_board_keep_individual_and_group_scopes_apart(self):
        from unittest import mock
        m=self.module()
        reader=m.ViewerReader.__new__(m.ViewerReader)
        reader.credentials,reader.principal,reader.reserve={},lambda:'officer@a.test',lambda amount:None
        reader.can_view=lambda p:p=='p91'
        reader.can_count=lambda p:p in ('p91','p92')
        body=b'{"people":[{"id":"p91","days":[]},{"id":"p92","days":[]},{"id":"p93","days":[]}]}'
        with mock.patch('sentra.viewer_reader.PrivateStorage') as storage:
            storage.return_value.request.return_value=(200,body)
            self.assertEqual([p['id'] for p in reader.board()['people']],['p91'])
            self.assertEqual([p['id'] for p in reader.group_board()['people']],['p91','p92'])
        rows=[{'participant_id':p} for p in ('p91','p92','p93')]
        reader._rows=lambda *a,**k:rows
        self.assertEqual([r['participant_id'] for r in reader.catalog()],['p91'])
        self.assertEqual([r['participant_id'] for r in reader.group_catalog()],['p91','p92'])

    def test_curated_records_recheck_access_and_refuse_oversized_before_transfer(self):
        m=self.module()
        self.assertTrue(hasattr(m.ViewerReader,'records'),'Bounded curated read missing')
        from psycopg.pq import TransactionStatus
        db=Mock();db.info.transaction_status=TransactionStatus.IDLE
        db.transaction.return_value.__enter__=Mock()
        db.transaction.return_value.__exit__=Mock(return_value=False)
        db.execute.return_value.fetchone.return_value=(1,20_000_001)
        denied=Mock(side_effect=SentraError('denied'))
        reader=m.ViewerReader({},Limits(),denied,db=db,budget_db=Mock())
        f=m.Selection('p99','whoop','sleep',date(2026,10,7),date(2026,10,8))
        with self.assertRaisesRegex(SentraError,'denied'):reader.records(f)
        db.execute.assert_not_called()
        reader.principal=lambda:'allowed'
        with self.assertRaisesRegex(SentraError,'Narrow'):reader.records(f)
        db.cursor.assert_not_called()

    def test_literal_search_is_parameterized_and_units_and_civil_dates_are_retained(self):
        m = self.module()
        f = m.Selection('p99','google_health','daily_steps',date(2026,10,7),date(2026,10,8),
                        metric='/steps/countSum',search="%' OR true --_")
        where, values = m.selection_where(f)
        self.assertNotIn(f.search,where)
        self.assertIn('civil',where)
        self.assertIn(f.metric, values)
        self.assertIn("%\\%' OR true --\\_%",values)

    def test_oversized_result_is_refused_before_health_rows_are_returned(self):
        m = self.module()
        for count,size in ((10001,50),(1,20_000_001)):
            with self.assertRaisesRegex(SentraError,'Narrow'): m.check_result_size(count,size)

    def test_failed_reservation_stops_without_storage_login(self):
        m = self.module()
        db = Mock()
        import psycopg
        db.execute.side_effect = psycopg.errors.RaiseException('secret must not escape')
        reader=m.ViewerReader({},Limits(),lambda:'allowed',db=db,budget_db=db)
        with self.assertRaises(CapacityStop) as error: reader.reserve(100)
        self.assertNotIn('secret',str(error.exception))

    def test_usage_must_be_available_and_ceiling_cannot_exceed_existing_limits(self):
        m=self.module()
        db=Mock()
        db.execute.return_value.fetchone.return_value=({'database_bytes':10,'object_bytes':10,
                                                        'egress_bytes':None},)
        reader=m.ViewerReader({},Limits(),lambda:'allowed',db=db,budget_db=Mock())
        with self.assertRaises(CapacityStop): reader.usage()

    def test_payload_reservation_survives_failed_read_transaction(self):
        m=self.module()
        import psycopg
        from psycopg.pq import TransactionStatus
        main=Mock(); main.info.transaction_status=TransactionStatus.IDLE
        main.execute.return_value.fetchone.return_value=(5,10000)
        main.transaction.return_value.__enter__=Mock()
        main.transaction.return_value.__exit__=Mock(return_value=False)
        cursor=Mock();cursor.__enter__=Mock(return_value=cursor);cursor.__exit__=Mock(return_value=False)
        cursor.fetchall.side_effect=psycopg.OperationalError('simulated interrupted payload transfer')
        main.cursor.return_value=cursor
        budget=Mock();budget.autocommit=True
        reader=m.ViewerReader({},Limits(),lambda:'allowed',db=main,budget_db=budget)
        with self.assertRaises(SentraError):
            reader.measurements(m.Selection('p99','whoop','sleep',date(2026,10,7),date(2026,10,8)))
        reserved=[call.args[1][0] for call in budget.execute.call_args_list]
        self.assertIn(10000*2+65536,reserved)
        self.assertTrue(all('reserve_viewer_egress' not in str(call) for call in main.execute.call_args_list))


if __name__=='__main__': unittest.main()
