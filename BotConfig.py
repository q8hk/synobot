#-*- coding: utf-8 -*-

import sys
import os
import socket
import single


def _parse_id_list(value, setting_name, allow_negative=False):
    """Parse a comma-separated Telegram ID list without executing input."""
    if value is None:
        raise ValueError('%s must be configured' % setting_name)

    ids = []
    for item in str(value).split(','):
        item = item.strip()
        if not item:
            continue
        numeric_item = item[1:] if allow_negative and item.startswith('-') else item
        if not numeric_item.isdecimal():
            raise ValueError('%s must contain only comma-separated numeric IDs' % setting_name)
        parsed_id = int(item)
        if parsed_id == 0 or (parsed_id < 0 and not allow_negative):
            qualifier = 'non-zero' if allow_negative else 'positive'
            raise ValueError('%s must contain %s numeric IDs' % (setting_name, qualifier))
        if parsed_id not in ids:
            ids.append(parsed_id)

    if not ids:
        raise ValueError('%s must contain at least one numeric ID' % setting_name)
    return tuple(ids)


def _parse_bool(value, setting_name):
    normalized = str(value).strip().lower()
    if normalized in ('1', 'true', 'yes', 'on'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError('%s must be one of: 1, 0, true, false, yes, no, on, off' % setting_name)

class BotConfig(single.SingletonInstane):
    
    # 알림을 받을 Telegram 사용자의 Chat ID리스트 (, 기호로 구분)
    notify_chat_id_list = None
    dsm_pw_chat_id = ""
    # DSM 로그인 ID
    dsm_id = ""
    # DSM 로그인 PW
    dsm_pw = ""
    # Telegram Bot Token
    bot_token = ""
    # BOT 명령에 유효한 Telegram 사용자 Chat ID
    valid_user_list = None
    # Log Size (단위:MB)
    log_size = 0
    # Log Rotation 개수
    log_count = 0
    # Synlogy DSM 접속 URL 또는 IP
    dsm_url = ''
    # Synology Download Station 의 포트
    ds_download_port = 80
    # Https SSL 인증서 불일치 무시 여부
    dsm_cert = True
    # 로그인 재시도 횟수
    dsm_retry_login = 10
    # 작업 완료시 자동 삭제 여부
    dsm_task_auto_delete = False
    # 로컬라이징
    synobot_lang = 'ko_kr'
    # Torrent Watch Direcotry
    tor_watch_path = ''

    execute_path = ""
    host_name = ''

    # OTP Secret Key
    otp_secret = ''

    # Docker Log print option
    log_print = False


    def __init__(self, *args, **kwargs):

        self.notify_chat_id_list = _parse_id_list(
            os.environ.get('TG_NOTY_ID', '12345678'), 'TG_NOTY_ID', allow_negative=True)

        self.dsm_pw_chat_id = _parse_id_list(
            os.environ.get('TG_DSM_PW_ID', '12345678'), 'TG_DSM_PW_ID')[0]

        self.dsm_id = os.environ.get('DSM_ID', '')
        self.bot_token = os.environ.get('TG_BOT_TOKEN', '')
        self.valid_user_list = _parse_id_list(
            os.environ.get('TG_VALID_USER', '12345678,87654321'), 'TG_VALID_USER')
        
        self.log_size = int( os.environ.get('LOG_MAX_SIZE', '50') )
        self.log_count = int( os.environ.get('LOG_COUNT', '5') )

        self.dsm_url = os.environ.get('DSM_URL', 'https://DSM_IP_OR_URL')
        self.ds_download_port = os.environ.get('DS_PORT', '8000')

        # Prefer the explicit DSM_TLS_VERIFY name. DSM_CERT remains compatible:
        # 1 verifies certificates and 0 disables verification.
        if 'DSM_TLS_VERIFY' in os.environ:
            self.dsm_cert = _parse_bool(os.environ['DSM_TLS_VERIFY'], 'DSM_TLS_VERIFY')
        else:
            self.dsm_cert = _parse_bool(os.environ.get('DSM_CERT', '1'), 'DSM_CERT')

        self.dsm_retry_login = os.environ.get('DSM_RETRY_LOGIN', 10)

        temp_val = os.environ.get('DSM_AUTO_DEL', '0')
        if temp_val == '1':
            self.dsm_task_auto_delete = True

        self.synobot_lang = os.environ.get('TG_LANG', 'ko_kr')

        self.tor_watch_path = os.environ.get('DSM_WATCH', '')

        temp_path = os.path.split(sys.argv[0])
        self.execute_path = temp_path[0]

        self.host_name = socket.gethostname()

        # DSM_PW 환경변수가 있는 경우에는 Telegram 을 통해 암호를 입력 받는 과정을 생략 한다.
        self.dsm_pw = os.environ.get('DSM_PW', '')

        # DSM_OTP_SECRET 환경변수가 있으면 OTP Code 를 자동으로 생성하여 로그인한다.
        self.otp_secret = os.environ.get('DSM_OTP_SECRET', '')

        temp_val = os.environ.get('DOCKER_LOG', '1')
        if temp_val == '1':
            self.log_print = True

    def GetNotifyList(self):
        return self.notify_chat_id_list

    def GetDsmPwId(self):
        return self.dsm_pw_chat_id

    def GetDsmId(self):
        return self.dsm_id

    def GetBotToken(self):
        return self.bot_token

    def GetValidUser(self):
        return self.valid_user_list

    def GetLogSize(self):
        return self.log_size

    def GetLogCount(self):
        return self.log_count

    def GetDSDownloadUrl(self):
        return self.dsm_url + ":" + self.ds_download_port

    def GetExecutePath(self):
        return self.execute_path

    def GetHostName(self):
        return self.host_name

    def GetDsmPW(self):
        return self.dsm_pw

    def SetDsmId(self, dsm_id):
        self.dsm_id = dsm_id

    def SetDsmPW(self, pw):
        self.dsm_pw = pw

    def IsUseCert(self):
        return self.dsm_cert

    def GetDsmRetryLoginCnt(self):
        return int(self.dsm_retry_login)

    def IsTaskAutoDel(self):
        return self.dsm_task_auto_delete

    def GetSynobotLang(self):
        return self.synobot_lang

    def GetTorWatch(self):
        return self.tor_watch_path

    def GetLogPrint(self):
        return self.log_print

    def GetOtpSecret(self):
        return self.otp_secret
