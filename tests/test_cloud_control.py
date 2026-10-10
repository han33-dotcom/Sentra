"""Operator pause remains available when collection allowance is exhausted."""
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout
import io

from sentra.shared import CapacityStop


class ControlTests(unittest.TestCase):
    def test_pause_does_not_require_import_capacity_or_egress_allowance(self):
        from sentra import cloud_cli
        args=SimpleNamespace(command='cloud-window',config='synthetic',pause=True,
                             start=None,approved=False,ongoing=False)
        backend=Mock();backend.reserve.side_effect=CapacityStop('exhausted')
        backend.guard.side_effect=CapacityStop('exhausted')
        with patch.object(cloud_cli,'local_cipher'),patch.object(cloud_cli,'read_shared',return_value=({},None,None)),\
             patch.object(cloud_cli,'read_setup',return_value={}),patch.object(cloud_cli,'SharedBackend',return_value=backend),\
             redirect_stdout(io.StringIO()):
            self.assertEqual(cloud_cli.run_command(args),0)
        written=backend.db.execute.call_args.args[1][0].obj
        self.assertEqual(written,{'enabled':False})

    def test_enable_still_stops_before_control_update_at_exhausted_capacity(self):
        from sentra import cloud_cli
        args=SimpleNamespace(command='cloud-window',config='synthetic',pause=False,
                             start=date(2026,10,10),approved=True,ongoing=True)
        backend=Mock();backend.guard.side_effect=CapacityStop('exhausted')
        with patch.object(cloud_cli,'local_cipher'),patch.object(cloud_cli,'read_shared',return_value=({},None,None)),\
             patch.object(cloud_cli,'read_setup',return_value={}),patch.object(cloud_cli,'SharedBackend',return_value=backend),\
             self.assertRaises(CapacityStop):cloud_cli.run_command(args)
        backend.db.execute.assert_not_called()
