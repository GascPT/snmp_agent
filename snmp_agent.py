#!/usr/bin/env python
# coding=utf-8

from unittest import result
import grpc
import datetime
import time
import sys
import logging
import socket
import os
import ipaddress
import json
import signal
import subprocess
import threading
import queue


import sdk_service_pb2
import sdk_service_pb2_grpc
import lldp_service_pb2
import interface_service_pb2
import networkinstance_service_pb2
import route_service_pb2
import route_service_pb2_grpc
import nexthop_group_service_pb2
import nexthop_group_service_pb2_grpc
import mpls_service_pb2
import mpls_service_pb2_grpc
import config_service_pb2
import telemetry_service_pb2
import telemetry_service_pb2_grpc
import sdk_common_pb2
#from logging.handlers import RotatingFileHandler

from logger import *

# Modules
from pygnmi.client import gNMIclient,telemetryParser

# Variables

############################################################
## Agent will start with this name
############################################################
agent_name='snmp_agent'
############################################################
## Open a GRPC channel to connect to sdk_mgr on the dut
## sdk_mgr will be listening on 50053
############################################################
channel = grpc.insecure_channel('127.0.0.1:50053')
metadata = [('agent_name', agent_name)]
stub = sdk_service_pb2_grpc.SdkMgrServiceStub(channel)

##################################################################################################
## This is the GLobal Variables to the snmp agent to work 
##################################################################################################
host = ('unix:///opt/srlinux/var/run/sr_gnmi_server', 57400)

queue = queue.Queue()


log = MyLogger("Logger")

global_paths = ['interface[name=ethernet-1/1]/admin-state',
         'interface[name=ethernet-1/2]/admin-state']


def subscribe_thread(paths):
    subscribe = {
        'subscription': [
        ],
        'use_aliases': False,
        'mode': 'stream',
        'encoding': 'json_ietf'
    }

    for path in paths:
        subscribe['subscription'].append(
                {
                    'path': path,
                    'mode': 'on_change',
                    'sample_interval': 1000000000
                }
        )
            
      
    with gNMIclient(target= host, username='admin', password='admin', insecure=True, debug = True) as gc:
        telemetry_stream = gc.subscribe(subscribe=subscribe)

        #pygnmi implements this for as infinite loop
        for telemetry_entry in telemetry_stream:
            telemetry_entry_str = telemetryParser(telemetry_entry) 
            if not "sync_response" in telemetry_entry_str :
                queue.put(telemetry_entry_str)
            

##################################################################################################
## This is the main kproc where all processing for snmp_agent starts.
## Agent registeration, notification registration, Subscrition to notifications.
## Waits on the sunscribed Notifications and once any config is received, handles that config
## If there are critical errors, Unregisters the snmp_agent gracefully.
##################################################################################################
def Run():
    response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
    log.info(f"Registration response : {response.status}")

    ####################################################################################
    # START OF SUBSCRIBE THRED
    x = threading.Thread(target=subscribe_thread, args=(global_paths,))

    x.start()
    ################################################################################
    while True:
        while not queue.empty():
            entry = queue.get()
            
            log.info(f"{entry}  :::::  QUEUE SIZE --> {queue.qsize()}\n ")
        
 
    sys.exit()
    return True

############################################################
## Gracefully handle SIGTERM signal
## When called, will unregister Agent and gracefully exit
############################################################
def Exit_Gracefully(signum, frame):
    log.info("Caught signal :: {}\n will unregister snmp_agent".format(signum))
    try:
        response=stub.AgentUnRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
        log.error('try: Unregister response:: {}'.format(response))
        sys.exit()
    except grpc._channel._Rendezvous as err:
        log.info('GOING TO EXIT NOW: {}'.format(err))
        sys.exit()

##################################################################################################
## Main from where the Agent starts
## Log file is written to: /var/log/srlinux/stdout/<dutName>_snmpagent.log
## Signals handled for graceful exit: SIGTERM
##################################################################################################
if __name__ == '__main__':

    signal.signal(signal.SIGTERM, Exit_Gracefully)
    log.info("START TIME :: {}".format(datetime.datetime.now()))

    if Run():
        log.info('Agent unregistered and agent routes withdrawed from dut')
    else:
        log.info(f'Some exception caught, Check !')

