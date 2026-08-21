
#-*- coding: utf-8 -*-

# 설치 할 패키지 목록
# python-telegram-bot
# requests


import os
import sys
import time
import traceback
import signal

import BotConfig
import bothandler
import synods
import taskmgr

from LogManager import log

SIGNALS_TO_NAMES_DICT = dict((getattr(signal, n), n) for n in dir(signal) if n.startswith('SIG') and '_' not in n )

def signal_handler(sig, frame):
    log.info('recv signal : %s[%d]', SIGNALS_TO_NAMES_DICT[sig], sig)

def signal_term_handler(sig, frame):
    log.info('recv signal : %s[%d]', SIGNALS_TO_NAMES_DICT[sig], sig)
    log.info('stopping Synobot gracefully')
    taskmgr.TaskMgr().instance().SaveTask()
    bothandler.BotHandler().instance().Shutdown()

def exception_hook(exc_type, exc_value, exc_traceback):
    log.error(
        "Uncaught exception",
        exc_info=(exc_type, exc_value, exc_traceback)
    )
    

def main():

    # Signal 예외 처리
    # signal Register
    signal.signal(signal.SIGTERM, signal_term_handler)
    signal.signal(signal.SIGABRT, signal_handler)
    signal.signal(signal.SIGSEGV, signal_handler)
    signal.signal(signal.SIGHUP, signal_handler)

    # BotConfig Init
    BotConfig.BotConfig().instance()

    #synods.SynoDownloadStation().instance().Login()
    
    bot = bothandler.BotHandler().instance()

    try:
        bot.InitBot()
    finally:
        bot.StopTaskMonitor()
        taskmgr.TaskMgr().instance().SaveTask()

    log.info("Bot Exit")


if __name__ == '__main__':
    main()

