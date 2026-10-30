"""Discovery must remain usable without native code, network, or mining."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch
from pearl_m_miner import cli


class DiscoveryTests(unittest.TestCase):
    def test_json_is_portable_and_never_enters_native_preflight(self):
        with patch.object(cli, 'preflight', side_effect=AssertionError('native preflight forbidden')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['info', '--json']), 0)
        value = json.loads(output.getvalue())
        self.assertFalse(value['operation']['starts_mining'])
        self.assertFalse(value['operation']['network_access'])
        self.assertFalse(value['operation']['requires_wallet_secret'])
        self.assertTrue(value['developer_contribution']['optional'])
        self.assertEqual(value['developer_contribution']['disable_option'], '--dev-fee 0')
        self.assertNotEqual(value['pools']['kryptex']['identity'], value['developer_contribution']['public_address'])

    def test_human_output_explains_separate_identity_and_no_launch(self):
        with patch.object(cli, 'preflight', side_effect=AssertionError('native preflight forbidden')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['info']), 0)
        self.assertIn('Developer public PRL address: prl1', output.getvalue())
        self.assertIn('separate --address', output.getvalue())
        self.assertIn('does not start mining', output.getvalue())
