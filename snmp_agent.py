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
from logging.handlers import RotatingFileHandler

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
## This functions get the app_id from idb for a given app_name
##################################################################################################
def get_app_id(app_name):
    logging.info(f'Metadata {metadata} ')
    appId_req = sdk_service_pb2.AppIdRequest(name=app_name)
    app_id_response=stub.GetAppId(request=appId_req, metadata=metadata)
    logging.info(f'app_id_response {app_id_response.status} {app_id_response.id} ')
    return app_id_response.id



def subscribe_thread():
    host = ('unix:///opt/srlinux/var/run/sr_gnmi_server',57400)
    path = ["/interface[name=mgmt0]/admin-state"]
    #path = ["/"]
    cert = "/opt/srlinux/bin/server-cert.pem"

    #update = [('interface[name=ethernet-1/1]', { 'admin-state': 'enable' } )]

    subscribe = {
            'subscription': [
                {
                    'path': 'interface[name=ethernet-1/1]/admin-state',
                    'mode': 'on_change',
                    'sample_interval': 1000000000
                }
            ],
            'use_aliases': False,
            'mode': 'stream',
            'encoding': 'json_ietf'
        }
    #('/bfd/subinterface[name=system0.0]', { 'admin-state': 'enable' } )
    
    #with gNMIclient(target=host, username='admin', password='admin', insecure=True, path_cert=cert, debug=True) as gc:
    #with gNMIclient(target=host, username='admin', password='admin', insecure=True, debug=True) as gc:    
    with gNMIclient(target= host, username='admin', password='admin', insecure=True) as gc:
        #result = gc.capabilities()
        result = gc.get(path=path,encoding='json_ietf')
        #result = gc.set(update=update,encoding='json_ietf')
        #result_formatted = json.dumps(result)
        #print(f"GOT this {result}")
        #logging.info(result["notification"][0]['update'])
        telemetry_stream = gc.subscribe(subscribe=subscribe)

        for telemetry_entry in telemetry_stream:
            #print(telemetryParser(telemetry_entry))
            logging.info(f"\n\n{telemetryParser(telemetry_entry)}\n")
            logging.info("HERRRRRRRRRRRRRRRRRRRRRRRRRRRRRREEEEEEEEEEEEEEEEEEEEEE")

##################################################################################################
## This is the main kproc where all processing for snmp_agent starts.
## Agent registeration, notification registration, Subscrition to notifications.
## Waits on the sunscribed Notifications and once any config is received, handles that config
## If there are critical errors, Unregisters the snmp_agent gracefully.
##################################################################################################
def Run():
    response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
    logging.info(f"Registration response : {response.status}")

    ####################################################################################
    x = threading.Thread(target=subscribe_thread)

    x.start()

    while True:
        time.sleep(10)
        logging.info("ENtrou")
  
 
    sys.exit()
    return True

############################################################
## Gracefully handle SIGTERM signal
## When called, will unregister Agent and gracefully exit
############################################################
def Exit_Gracefully(signum, frame):
    logging.info("Caught signal :: {}\n will unregister snmp_agent".format(signum))
    try:
        response=stub.AgentUnRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
        logging.error('try: Unregister response:: {}'.format(response))
        sys.exit()
    except grpc._channel._Rendezvous as err:
        logging.info('GOING TO EXIT NOW: {}'.format(err))
        sys.exit()

##################################################################################################
## Main from where the Agent starts
## Log file is written to: /var/log/srlinux/stdout/<dutName>_snmpagent.log
## Signals handled for graceful exit: SIGTERM
##################################################################################################
if __name__ == '__main__':
    hostname = socket.gethostname()
    stdout_dir = '/var/log/srlinux/stdout' # PyTEnv.SRL_STDOUT_DIR
    signal.signal(signal.SIGTERM, Exit_Gracefully)
    if not os.path.exists(stdout_dir):
        os.makedirs(stdout_dir, exist_ok=True)
    log_filename = '{}/{}_snmpagent.log'.format(stdout_dir, hostname)
    logging.basicConfig(filename=log_filename, filemode='a',\
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',\
                        datefmt='%H:%M:%S', level=logging.INFO)
    handler = RotatingFileHandler(log_filename, maxBytes=3000000,
                                  backupCount=5)
    logging.getLogger().addHandler(handler)
    logging.info("START TIME :: {}".format(datetime.datetime.now()))
    if Run():
        logging.info('Agent unregistered and agent routes withdrawed from dut')
    else:
        logging.info(f'Some exception caught, Check !')

