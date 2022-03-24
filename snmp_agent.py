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
## This is the Global Variables to the snmp agent to work 
##################################################################################################
host = ('unix:///opt/srlinux/var/run/sr_gnmi_server', 57400)

queue = queue.Queue()


log = MyLogger("Logger")


#global_paths = ['interface[name=*]/admin-state']

global_paths = ['interface[name=ethernet-1/1]/admin-state',
                'interface[name=ethernet-1/2]/admin-state']

##################################################################################################
## This functions get the app_id from IDB for a given app_name
##################################################################################################
def get_app_id(app_name):
    log.info(f'Metadata {metadata}')
    appID_req = sdk_service_pb2.AppIdRequest(name=app_name)
    app_id_response = stub.GetAppId(request=appID_req, metadata=metadata)
    log.info(f'app_id_response {app_id_response.status} {app_id_response.id}')
    return app_id_response.id


############################################################
## Subscribe to required event
## This proc handles subscription of Config
############################################################
def Subscribe(stream_id):  
    op = sdk_service_pb2.NotificationRegisterRequest.AddSubscription

    entry = config_service_pb2.ConfigSubscriptionRequest()
    request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, config=entry)

    subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
    
    if subscription_response.status == sdk_common_pb2.SdkMgrStatus.Value("kSdkMgrFailed"):
        log.info("Subscription Config register Failed")

    
    log.info('Status of subscription response for config :: {}'.format(subscription_response.status))

############################################################
## Subscribe to all the events that Agent needs
############################################################
def Subscribe_Notifications(stream_id):
    '''
    Agent will receive notifications to what is subscribed here.
    '''
    if not stream_id:
        log.info("Stream ID not sent.")
        return False
    log.info("ENtering Subscribe function")
    ##Subscribe to Config Notifications - configs added by the fib-agent
    Subscribe(stream_id)

############################################################
## Function to populate state of agent config 
## using telemetry -- add/update info from state 
############################################################
def Add_Telemetry(js_path, js_data ):
    telemetry_stub = telemetry_service_pb2_grpc.SdkMgrTelemetryServiceStub(channel)
    telemetry_update_request = telemetry_service_pb2.TelemetryUpdateRequest()
    telemetry_info = telemetry_update_request.state.add()
    telemetry_info.key.js_path = js_path
    telemetry_info.data.json_content = js_data
    log.info(f"Telemetry_Update_Request :: {telemetry_update_request}")
    telemetry_response = telemetry_stub.TelemetryAddOrUpdate(request=telemetry_update_request, metadata=metadata)
    return telemetry_response

############################################################
## Function to cleanup state of agent config 
## using telemetry -- cleanup info from state
############################################################
def Delete_Telemetry(js_path):
    telemetry_stub = telemetry_service_pb2_grpc.SdkMgrTelemetryServiceStub(channel)
    telemetry_delete_request = telemetry_service_pb2.TelemetryDeleteRequest()
    telemetry_delete = telemetry_delete_request.key.add()
    telemetry_delete.js_path = js_path
    log.info(f"Telemetry_Delete_Request :: {telemetry_delete_request}")
    telemetry_response = telemetry_stub.TelemetryDelete(request=telemetry_delete_request, metadata=metadata)
    return telemetry_response


##################################################################
## Proc to process the config Notifications received by fib_agent 
## At present processing config from js_path = .fib-agent
##################################################################
def Handle_Notification(obj):
    log.info(obj)
    if obj.HasField('config') and obj.config.key.js_path != ".commit.end":
        log.info(f"GOT CONFIG :: {obj.config.key.js_path}")
        log.info(f"OLD FILE :: input elements")
        log.info(f"Handle_Config with file_name as input_elements")
        if "fib_agent" in obj.config.key.js_path:
            log.info(f"Got config for agent, now will handle it :: \n{obj.config}\
                            Operation :: {obj.config.op}\nData :: {obj.config.data.json}")
    
    #always return
    return True

def NotificationStreamThread(stream_id):
    sub_stub = sdk_service_pb2_grpc.SdkNotificationServiceStub(channel)
    stream_request = sdk_service_pb2.NotificationStreamRequest(stream_id=stream_id)
    stream_response = sub_stub.NotificationStream(stream_request, metadata=metadata)
    
    for r in stream_response:
        for obj in r.notification:
            Handle_Notification(obj)


def send_keep_alive():
    global thread_exit
    while not thread_exit:
        keep_alive_response = stub.KeepAlive(request=sdk_service_pb2.KeepAliveRequest(),metadata=metadata)
        #log.info("SEND KEEP ALIVE")
        if keep_alive_response.status == sdk_common_pb2.SdkMgrStatus.Value("kSdkMgrFailed"):
            log.error("Keep Alive Failed")
        time.sleep(3)


############################################################
## Function to subscribe to the paths
## using telemetry -- add/update info from state 
############################################################
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

        #pygnmi implements this 'for' as infinite loop
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
    response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(agent_liveliness=5), metadata=metadata)
    log.info(f"Registration response : {response.status}")

    app_id = get_app_id(agent_name)

    if not app_id:
        log.error(f'idb does not have the appID for {agent_name} : {app_id}')
    else:
        log.info(f'Got appId {app_id} for {agent_name}')
    
    # Send Keep Alives
    th = threading.Thread(target=send_keep_alive)
    th.start()

    #Subscribe Notifications
    request=sdk_service_pb2.NotificationRegisterRequest(op=sdk_service_pb2.NotificationRegisterRequest.Create)
    create_subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
    if create_subscription_response.status == sdk_common_pb2.SdkMgrStatus.Value("kSdkMgrFailed"):
        log.info("Notification register Failed")

    stream_id = create_subscription_response.stream_id
    
    log.info(f"Create subscription response received. Stream_id : {stream_id}")

    Subscribe_Notifications(stream_id)

    notificationStreamThread = threading.Thread(target=NotificationStreamThread, args=(stream_id,))
    notificationStreamThread.start()
   
    ####################################################################################
    # START OF SUBSCRIBE GNMI THREAD

    x = threading.Thread(target=subscribe_thread, args=(global_paths,))
    print(global_paths)
    x.start()
    
    ################################################################################
    while True:
        while not queue.empty():
            entry = queue.get()
            
            log.info(f"{entry['update']['update']}  :::::  QUEUE SIZE --> {queue.qsize()}\n ")
        
 
    sys.exit()
    return True

############################################################
## Gracefully handle SIGTERM signal
## When called, will unregister Agent and gracefully exit
############################################################
def Exit_Gracefully(signum, frame):
    global thread_exit
    thread_exit = True
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
    global thread_exit
    thread_exit = False
    signal.signal(signal.SIGTERM, Exit_Gracefully)
    log.info("START TIME :: {}".format(datetime.datetime.now()))

    if Run():
        log.info('Agent unregistered and agent routes withdrawed from dut')
    else:
        log.info(f'Some exception caught, Check !')

