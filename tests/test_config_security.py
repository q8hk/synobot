import os
import unittest
from unittest.mock import patch

import BotConfig


class IdListParsingTests(unittest.TestCase):
    def test_parses_deduplicated_numeric_ids(self):
        self.assertEqual(
            BotConfig._parse_id_list(' 123,456,123, ', 'TEST_IDS'),
            (123, 456),
        )

    def test_rejects_code_instead_of_evaluating_it(self):
        with self.assertRaisesRegex(ValueError, 'comma-separated numeric IDs'):
            BotConfig._parse_id_list('__import__("os").getcwd()', 'TEST_IDS')

    def test_rejects_empty_list(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            BotConfig._parse_id_list(' , ', 'TEST_IDS')

    def test_allows_negative_chat_ids_only_when_requested(self):
        self.assertEqual(
            BotConfig._parse_id_list('-100123,456', 'CHAT_IDS', allow_negative=True),
            (-100123, 456),
        )
        with self.assertRaisesRegex(ValueError, 'numeric IDs'):
            BotConfig._parse_id_list('-100123', 'USER_IDS')


class ConfigurationSecurityTests(unittest.TestCase):
    def test_telegram_ids_have_consistent_integer_types(self):
        env = {
            'TG_NOTY_ID': '101, 202',
            'TG_DSM_PW_ID': '303',
            'TG_VALID_USER': '404,505',
        }
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig.BotConfig()

        self.assertEqual(config.GetNotifyList(), (101, 202))
        self.assertEqual(config.GetDsmPwId(), 303)
        self.assertEqual(config.GetValidUser(), (404, 505))

    def test_tls_verify_new_name_takes_precedence(self):
        env = {'DSM_TLS_VERIFY': 'false', 'DSM_CERT': '1'}
        with patch.dict(os.environ, env, clear=True):
            config = BotConfig.BotConfig()

        self.assertFalse(config.IsUseCert())

    def test_legacy_tls_setting_remains_supported(self):
        with patch.dict(os.environ, {'DSM_CERT': '0'}, clear=True):
            config = BotConfig.BotConfig()

        self.assertFalse(config.IsUseCert())

    def test_invalid_tls_setting_has_clear_error(self):
        with patch.dict(os.environ, {'DSM_TLS_VERIFY': 'maybe'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'DSM_TLS_VERIFY must be one of'):
                BotConfig.BotConfig()

    def test_bot_token_has_no_embedded_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = BotConfig.BotConfig()

        self.assertEqual(config.GetBotToken(), '')


if __name__ == '__main__':
    unittest.main()
