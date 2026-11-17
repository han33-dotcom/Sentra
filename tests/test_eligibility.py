from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from sentra.eligibility import metadata
from sentra.errors import SentraError
from sentra.processing.board import BOARD_VERSION
from sentra.processing.pipeline import ASSESSMENT_VERSION
from sentra import wellness_refresh as w


class EligibilityTests(unittest.TestCase):
    def board(self):
        return {'built_at':'2026-11-17T12:00:00+00:00','source_run':'2026-11-17T11:00:00+00:00',
                'board_version':BOARD_VERSION,'assessment_version':ASSESSMENT_VERSION,
                'people':[{'id':'p01','days':[{'d':'2026-11-16','lvl':'green'}]},
                          {'id':'p02','days':[{'d':'2026-11-16','lvl':'red','a':'partial'}]},
                          {'id':'p03','days':[]}]}

    def test_only_current_contract_completeness_becomes_metadata(self):
        board=self.board()
        self.assertEqual([r['assessable'] for r in metadata(board)],[True,False,None])
        self.assertTrue(all(set(r)=={'participant_id','day','assessable'} for r in metadata(board)))
        for change in ({'assessment_version':'old'},{'board_version':'old'},
                       {'people':board['people']*40},{'people':[board['people'][0]]*2}):
            with self.assertRaises(SentraError): metadata({**board,**change})

    def test_unchanged_board_repairs_feed_without_rebuilding_tiers(self):
        import json
        from datetime import datetime
        from sentra.shared import Limits
        board=self.board(); storage=Mock()
        storage.request.return_value=(200,json.dumps(board).encode())
        writer=Mock(return_value='published')
        with patch.object(w,'latest_run',return_value=board['source_run']), \
                patch.object(w,'build',side_effect=AssertionError('must not rebuild')):
            result=w.refresh(Mock(),Limits(),storage,eligibility_writer=writer,log=lambda *_:None)
        self.assertEqual((result['status'],result['eligibility']),('skipped','published'))
        writer.assert_called_once_with(board)

    def test_failed_feed_is_explicit_and_never_claims_board_rollback(self):
        with self.assertRaisesRegex(SentraError,'Board is published'):
            w._eligibility(Mock(side_effect=RuntimeError('private details')),self.board())
