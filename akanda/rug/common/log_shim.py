

import logging
from logging import INFO as _INFO

INFO = _INFO

LOGGERS = {}
logging_cli_opts = []
log_opts = []

def setup(name):
    return

def getLogger(name):
    print 'setting up logging for %s' % name
    if name in LOGGERS:
        print '= found logger ' + name
        return LOGGERS[name]
    print '- creating logger ' + name
    logger = logging.getLogger(name)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)

    log_format = ':'.join('%(' + n + ')s'
                          for n in ['asctime',
                                    'levelname',
                                    'name',
                                    'process',
                                    'processName',
                                    'threadName',
                                    'message'])
    formatter = logging.Formatter(log_format)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    logger.setLevel(logging.DEBUG)
    LOGGERS[name] = logger
    return logger


class WritableLogger(object):
    """A thin wrapper that responds to `write` and logs."""

    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level

    def write(self, msg):
        self.logger.log(self.level, msg)
