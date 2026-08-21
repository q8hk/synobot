import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


class _FakeTotp:
    def __init__(self, secret):
        self.secret = secret

    def now(self):
        if self.secret == 'invalid':
            raise ValueError('invalid secret')
        return '123456'


class OtpHandlerCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.original_pyotp = sys.modules.get('pyotp')
        sys.modules['pyotp'] = types.SimpleNamespace(TOTP=_FakeTotp)
        sys.modules.pop('OtpHandler', None)
        self.module = importlib.import_module('OtpHandler')

    def tearDown(self):
        sys.modules.pop('OtpHandler', None)
        if self.original_pyotp is None:
            sys.modules.pop('pyotp', None)
        else:
            sys.modules['pyotp'] = self.original_pyotp

    def test_empty_secret_disables_otp(self):
        handler = self.module.OtpHandler()
        handler.InitOtp('')

        self.assertEqual(handler.GetOtp(), '')

    def test_configured_secret_generates_current_code(self):
        handler = self.module.OtpHandler()
        handler.InitOtp('valid')

        self.assertEqual(handler.GetOtp(), '123456')

    def test_invalid_secret_fails_closed(self):
        handler = self.module.OtpHandler()
        handler.InitOtp('invalid')

        self.assertEqual(handler.GetOtp(), '')


class _LanguageConfig:
    def __init__(self, language):
        self.language = language

    def GetSynobotLang(self):
        return self.language


class LocalizationCharacterizationTests(unittest.TestCase):
    def _service(self, language='en_us'):
        import synobotLang

        service = object.__new__(synobotLang.synobotLang)
        service.cfg = _LanguageConfig(language)
        service.lang_json = None
        return service

    def test_loads_requested_language_file_from_working_directory(self):
        service = self._service('custom')
        payload = {
            'bothandler': {'hello': 'Hello'},
            'synods': {},
            'syno_error': {},
            'syno_auth_error': {},
            'syno_task_error': {},
        }
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, 'custom.json'), 'w') as stream:
                json.dump(payload, stream)
            with patch('os.getcwd', return_value=directory):
                service.LoadLangFile()

        self.assertEqual(service.GetJson(), payload)
        self.assertEqual(service.GetBotHandlerLang('hello'), 'Hello')

    def test_missing_language_falls_back_to_korean_file(self):
        service = self._service('missing')
        payload = {
            'bothandler': {},
            'synods': {'finished': 'complete'},
            'syno_error': {},
            'syno_auth_error': {},
            'syno_task_error': {},
        }
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, 'ko_kr.json'), 'w') as stream:
                json.dump(payload, stream)
            with patch('os.getcwd', return_value=directory):
                service.LoadLangFile()

        self.assertEqual(service.GetSynoDsLang('finished'), 'complete')

    def test_unknown_keys_and_error_fallbacks_are_descriptive(self):
        service = self._service()
        service.lang_json = {
            'bothandler': {},
            'synods': {},
            'syno_error': {'100': 'common error'},
            'syno_auth_error': {'400': 'bad login'},
            'syno_task_error': {'401': 'bad task'},
        }

        self.assertIn('missing', service.GetBotHandlerLang('missing'))
        self.assertIn('missing', service.GetSynoDsLang('missing'))
        self.assertEqual(service.GetSynoAuthErrorLang('400'), 'bad login')
        self.assertEqual(service.GetSynoAuthErrorLang('100'), 'common error')
        self.assertEqual(service.GetSynoTaskErrorLang('401'), 'bad task')
        self.assertEqual(service.GetSynoTaskErrorLang('100'), 'common error')
        self.assertIn('999', service.GetSynoAuthErrorLang('999'))
        self.assertIn('999', service.GetSynoTaskErrorLang('999'))


if __name__ == '__main__':
    unittest.main()
