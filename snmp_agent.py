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
import re

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


from logger import *
from element import *

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
#global_paths = ['interface[name=ethernet-1/1]/oper-state',
#                'interface[name=ethernet-1/2]/oper-state']
global_paths = []
targets = []
elements = []
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
    if not stream_id:
        log.info("Stream ID not sent.")
        return False
    
    ##Subscribe to Config Notifications - configs added by the fib-agent
    Subscribe(stream_id)

############################################################
## Function to populate state of agent config 
## using telemetry -- add/update info from state 
############################################################
def Add_Telemetry(js_path, js_data):
    telemetry_stub = telemetry_service_pb2_grpc.SdkMgrTelemetryServiceStub(channel)
    telemetry_update_request = telemetry_service_pb2.TelemetryUpdateRequest()
    telemetry_info = telemetry_update_request.state.add()
    telemetry_info.key.js_path = js_path
    telemetry_info.data.json_content = js_data
    #log.info(f"Telemetry_Update_Request :: {telemetry_update_request}")
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
    #log.info(f"Telemetry_Delete_Request :: {telemetry_delete_request}")
    telemetry_response = telemetry_stub.TelemetryDelete(request=telemetry_delete_request, metadata=metadata)
    return telemetry_response

def addTargetsToTelemetry() -> None:
    global targets
    js_path = '.' + agent_name
    json_content = { "target": { "address": [ ] } }

    for t in targets:
        json_content['target']['address'].append({"value": f'{t}'})  
    
    r = Add_Telemetry(js_path,json.dumps(json_content))

def addElementsToTelemetry() -> None:
    global elements
    base_path = '.' + agent_name + ".monitoring_elements.element"
    for te in elements:
        js_key = te.getKey()
        js_path = base_path + f'{{.resource=="{js_key}"}}'
        json_content = te.getJSONElement()  
        r = Add_Telemetry(js_path,json.dumps(json_content))


def addBrackets(phrase: str) -> str:
    if not phrase.endswith('/'):
        phrase = phrase + '/'
    return phrase

def addStatusToMemory(obj, filename = None):
    global targets, elements
    # From Notification
    if filename == None:
        #Check if are target config
        if obj.config.key.js_path == ".snmp_agent":
            #Check if exits any config 
            if not obj.config.data.json == "{\n}\n":    
                notification_targets = json.loads(obj.config.data.json) 
                for target in notification_targets['target']['address']:
                    if target not in targets:
                        t = target['value']
                        targets.append(t)
                addTargetsToTelemetry() 

                # Add to the File
                with open("input_elements","r+") as f:
                    file_data = json.load(f)
                    aux_targets = []

                    for target in file_data['targets']:
                        aux_targets.append(target['address'])

                    #Diff between global state targets and targets written on the file 
                    diff_targets = [x for x in targets if x not in aux_targets]

                    for t in diff_targets:
                        file_data['targets'].append({"address" : t})
                    
                    f.seek(0)
                    f.write(json.dumps(file_data, indent=4))
                    f.truncate()
                
        # Check if are configuration of a element
        elif obj.config.key.js_path == ".snmp_agent.monitoring_elements.element":
            #Check if exits any config 
            if not obj.config.data.json == "{\n}\n":
                element_json = json.loads(obj.config.data.json)['element']
                # Desiralization of the elements into variables
                resource = obj.config.key.keys[0]
                parameter = element_json['parameter']['value']
                monitoring_condition = element_json['monitoring_condition']['value'] 
                if "resource_filter" in element_json:
                    resource_filter = element_json['resource_filter']['value']
                else:
                    resource_filter = ""
                   
                if "trigger_condition" in element_json:
                    trigger_condition = element_json['trigger_condition']['value']
                else:
                    trigger_condition = ""
  
                e = Element(resource,parameter,monitoring_condition,resource_filter,trigger_condition, False)

                # Add element to monitoring to the list of elements
                elements.append(e)
                # Add to Telemetry
                addElementsToTelemetry()
                # Add to the File
                # TODO
                


    # From File
    else:
        try:
            with open(filename) as f:
                file_data = json.load(f)
                # Add targets to the global variable       
                for target in file_data['targets']:
                    if target not in targets:
                        t = target['address']
                        targets.append(t)
                        
                # Add Targets to State
                if not len(targets) == 0:
                    addTargetsToTelemetry()

                # Add Elements to the global variable
                for element in file_data['monitoring_elements']:
                    resource = addBrackets(element['resource'])
                    parameter = element['parameter']
                    monitoring_condition = element['monitoring_condition']
                    if "resource_filter" in element:
                        resource_filter = element['resource_filter']
                    else:
                        resource_filter = ""
                    
                    if "trigger_condition" in element:
                        trigger_condition = element['trigger_condition']
                    else:
                        trigger_condition = ""
                    
                    trigger_message = element['trigger_message']

                    e = Element(resource,parameter,monitoring_condition,resource_filter,trigger_condition, False)

                    log.info(e.print())

                    # Add element to monitoring to the list of elements
                    elements.append(e)
                    # Add to Telemetry
                    addElementsToTelemetry()

                    
        except Exception as e:
            logging.info(f"Exception caught while reading file :: {e}")
            #Set programed status as false
            return False


##################################################################
## Proc to process the config Notifications received by fib_agent 
## At present processing config from js_path = .fib-agent
##################################################################
def Handle_Notification(obj):
    if obj.HasField('config') and obj.config.key.js_path != ".commit.end":
        log.info(f"GOT CONFIG :: {obj.config.key.js_path}")
        if "snmp_agent" in obj.config.key.js_path:
            log.info(f"Got config for agent, now will handle it :: \n{obj.config}\
                            Operation :: {obj.config.op}\nData :: {obj.config.data.json}")

            addStatusToMemory(obj)
    
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

def getGNMIPath(path):
    with gNMIclient(target = host, username='admin', password='admin', insecure=True, debug = True) as gc:
        return gc.get(path,encoding="json_ietf")

# TODO
def sendSNMPTrap(entry,target):
    
    return None


def sendToAllTargets(entry):
    global targets
    for target in targets:
        sendSNMPTrap(entry, target)
    

def addGlobalPaths():
    global global_paths,elements
    for element in elements:
        path = element.getPath()
        global_paths.append(path)

def verifyTriggerCondition(element,value):
    trigger = element.getTrigger()

    if element.getStatus() == "": # If previous status are empty
        element.setStatus(value)
        return False
    
    if "->" in trigger: # CHange from value 1 to value 2
        val1,val2 = trigger.split("->")
        if element.getStatus() == val1 and val2 == value:
            element.setStatus(value)
            return True
        element.setStatus(value)

    elif "!=" in trigger: # TODO Different from one value
        log.info("TODO: Different from one value to another")

    return False


def verifyMonitoringCondition(element, entry_path):
    m = element.getMonitoring()
    if m == "":
        return True
    parameter,value = m.split(":")

    if element.getParameter() in entry_path: 
        entry_path = '/'.join(entry_path.split('/')[:-1])

    path = entry_path +"/"+ parameter
    # Get Request to assert with the value
    result = getGNMIPath(path)

    if result['notification'][0]['update'][0]['val'] == value:
        return True

    return False


def processEntry(entry):
    global elements
    for element in elements:
        path = element.getResource()
        # Can be more than one entry from subscribe
        for e in entry:
            entry_path = e['path'].split(":")[1] # Clean the path model
            
            if isinstance(e['val'],str):
                value = e['val']
                aux_path = entry_path
                entry_path = '/'.join(entry_path.split('/')[:-1])+"/"
            else:
                value = list(e['val'].items())[0][1]
                aux_path = entry_path+"/"+list(e['val'].keys())[0]
            #log.info(entry_path + ":" + value)
            if element.verifyIfExistPath(entry_path):
                log.info("Enter")
                if verifyTriggerCondition(element,value):
                    #Generate SNMP TRAP
                    log.info(element.getPaths())
                    log.info("Send TRAP - 1")
            # This below is first entry process    
            else:
                # Path with * 
                if '*' in path:
                    resource_filter = element.getFilter()
                    id1 = entry_path.index("=")
                    id2 = entry_path.index("]")
                    sub_path = entry_path[id1 + len("") + 1: id2]
                    for filt in resource_filter:
                        # Filter with *
                        if '*' in filt:
                            sub_filter = filt[:-1]
                            if sub_filter in sub_path:
                                # Process Get Request
                                if verifyMonitoringCondition(element,entry_path):
                                    # Add to pathsofElement in that element
                                    if not entry_path in element.getPaths():
                                        element.addPaths(entry_path+"/"+element.getParameter())
                                    # Check trigger condition
                                    if verifyTriggerCondition(element,value):
                                        #Generate SNMP TRAP
                                        log.info("Send TRAP - 2")
                                
                        else:
                        # TODO Specific Filter
                            if filt == sub_path:
                                log.info("Second filter")
                # Specific Path    
                # Because is a specific path dont check filter options       
                else:
                    log.info(element.getResource()+"||||"+entry_path)
                    if entry_path == element.getResource():
                        if verifyMonitoringCondition(element,entry_path):
                            # Add to pathsofElement in that element
                            if not entry_path in element.getPaths():
                                element.addPaths(entry_path)
                                
                                # Check trigger condition
                                if verifyTriggerCondition(element,value):
                                    #Generate SNMP TRAP
                                    log.info("Send TRAP - 3")



##################################################################################################
## This is the main kproc where all processing for snmp_agent starts.
## Agent registeration, notification registration, Subscrition to notifications.
## Waits on the sunscribed Notifications and once any config is received, handles that config
## If there are critical errors, Unregisters the snmp_agent gracefully.
##################################################################################################
def Run():
    response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(agent_liveliness=5), metadata=metadata)
    log.info(f"Registration response : {response.status}")

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

    if os.path.exists('input_elements'):
        addStatusToMemory(None,"input_elements")

    ####################################################################################
    # Add Global Paths from Elements
    addGlobalPaths()

    ####################################################################################
    # START OF GNMI SUBSCRIBE THREAD

    x = threading.Thread(target=subscribe_thread, args=(global_paths,))
    x.start()
    
    ################################################################################
    # Infinite Loop to send SNMP traps
    ################################################################################
    while True:
        while not queue.empty():
            entry = queue.get()
            entry = entry['update']['update']
            #log.info(f"{entry}  :::::  QUEUE SIZE --> {queue.qsize()}\n ")
            processEntry(entry)


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
