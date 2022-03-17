import sys
import socket
import os

import logging

from logging.handlers import RotatingFileHandler

class MyLogger:
    def __init__(self, name):

        hostname = socket.gethostname()
        stdout_dir = '/var/log/srlinux/stdout' # PyTEnv.SRL_STDOUT_DIR
        
        if not os.path.exists(stdout_dir):
            os.makedirs(stdout_dir, exist_ok=True)

        log_filename = '{}/{}_snmpagent.log'.format(stdout_dir, hostname)

        self.logger = logging.getLogger(name)

        logging.basicConfig(filename=log_filename, filemode='a',\
                            format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',\
                            datefmt='%H:%M:%S', level=logging.INFO)
        
        handler = RotatingFileHandler(log_filename, maxBytes=3000000, backupCount=5)

        self.logger.addHandler(handler)
        self.logger.propagate = False

    
    def info(self, message):
        self.logger.info(message) 

