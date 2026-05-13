import argparse
import unittest
from unittest.mock import patch

from f1fantasy.models import TransferStatus
from scripts.f1_fantasy import _check_free_transfers_or_exit, build_parser


IDEAL = {
    "drivers": ["A", "B", "C", "D", "E"],
    "constructors": ["X", "Y"],
    "boost_driver": None,
}


def _args(*, allow_paid_transfers=False):
    return argparse.Namespace(
        team_id=1,
        expected_team_name=None,
        profile_dir="/tmp/f1-profile",
        headful=False,
        allow_paid_transfers=allow_paid_transfers,
    )


class TestCliTransferGuard(unittest.TestCase):
    def test_sync_help_exposes_paid_transfer_override(self):
        parser = build_parser()
        args = parser.parse_args(["sync", "--ideal", "ideal.json", "--allow-paid-transfers"])
        self.assertTrue(args.allow_paid_transfers)

    @patch("scripts.f1_fantasy.scrape_transfer_status")
    @patch("scripts.f1_fantasy.sync_team_to_ideal")
    def test_blocks_when_required_transfers_exceed_free(self, mock_sync, mock_status):
        mock_sync.return_value = {"diff": {"transfers_required": 3}}
        mock_status.return_value = TransferStatus(ts_utc="now", team_id=1, free_transfers=2)

        with self.assertRaises(SystemExit):
            _check_free_transfers_or_exit(args=_args(), ideal=IDEAL)

        mock_sync.assert_called_once()
        self.assertFalse(mock_sync.call_args.kwargs["apply"])
        self.assertTrue(mock_sync.call_args.kwargs["force"])

    @patch("scripts.f1_fantasy.scrape_transfer_status")
    @patch("scripts.f1_fantasy.sync_team_to_ideal")
    def test_allows_explicit_paid_transfer_override(self, mock_sync, mock_status):
        mock_sync.return_value = {"diff": {"transfers_required": 3}}
        mock_status.return_value = TransferStatus(ts_utc="now", team_id=1, free_transfers=2)

        result = _check_free_transfers_or_exit(args=_args(allow_paid_transfers=True), ideal=IDEAL)

        self.assertEqual(result["transfers_required"], 3)
        self.assertEqual(result["free_transfers"], 2)
        self.assertTrue(result["paid_transfer_override"])


if __name__ == "__main__":
    unittest.main()
