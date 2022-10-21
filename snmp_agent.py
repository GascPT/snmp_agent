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
import config_service_pb2
import telemetry_service_pb2
import telemetry_service_pb2_grpc
import sdk_common_pb2

from logger import *
from element import *
from target import *

# Modules
from pygnmi.client import gNMIclient,telemetryParser
############################################################
#                       Variables
############################################################

############################################################
## Agent will start with this name
############################################################
agent_name ='snmp_agent'

############################################################
## FILENAME of input
############################################################
FILENAME = 'input_elements'

############################################################
## Open a GRPC channel to connect to sdk_mgr on the dut
## sdk_mgr will be listening on 50053
############################################################
channel = grpc.insecure_channel('127.0.0.1:50053')
metadata = [('agent_name', agent_name)]
stub = sdk_service_pb2_grpc.SdkMgrServiceStub(channel)

############################################################
## This is the Global Variables to the snmp agent to work 
############################################################
# GNMI Server
host = ('unix:///opt/srlinux/var/run/sr_gnmi_server', 57400)

# Queue with the entries of subscribe function
queue = queue.Queue()

# Logger Class
log = MyLogger("Logger")

# Main Variables of the agent
global_paths = []
targets = []
elements = []



#Credentials Class that willl save the gNMI Credentials in runtime
class Credentials():
    def __init__(self,user,password):
        self._user = user
        self._password = password


    def getUser(self):
        return self._user

    def getPassword(self):
        return self._password

gnmi_credentials = None

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
    
    ##Subscribe to Config Notifications - configs added by the snmp-agent
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

############################################################
## Function to add List of Targets from memory
## to telemetry 
############################################################
def addTargetsToTelemetry() -> None:
    global targets
    for t in targets:
        js_path = f'.{agent_name}.targets.target{{.address=="{t.get_address()}"}}'
        json_content = { 'network-instance': f'{t.get_nw()}',
                            }       
        r = Add_Telemetry(js_path,json.dumps(json_content))

############################################################
## Function to remove List of Targets from memory
## to telemetry 
############################################################
def removeTargetsOfTelemetry(address) -> None:
    js_path = f'.{agent_name}.targets.target{{.address=="{address}"}}'  
    r = Delete_Telemetry(js_path)

############################################################
## Function to add List of Elements from memory
## to telemetry 
############################################################
def addElementsToTelemetry() -> None:
    global elements
    base_path = '.' + agent_name + ".monitoring_elements.element"
    for e in elements:
        js_key = e.getKey()
        js_path = base_path + f'{{.resource=="{js_key}"}}'
        json_content = e.getJSONElement()  
        r = Add_Telemetry(js_path,json.dumps(json_content))

############################################################
## Function to remove List of Elements from memory
## to telemetry 
############################################################
def removeElementsOfTelemetry(resource) -> None:
    js_path = f'.{agent_name}.monitoring_elements.element{{.resource=="{resource}"}}'  
    r = Delete_Telemetry(js_path)

############################################################
##                  Auxiliar Functions
############################################################
# Add Slash in final of a string
def addBrackets(phrase: str) -> str:
    if not phrase.endswith('/'):
        phrase = phrase + '/'
    return phrase

# Difference between 2 JSON Objects
def diffTwoJSONObjects(array_a, array_b):
    # array_a -> From Memory
    # array_b -> From File
    data = []
    for o in array_a:
        if not o in array_b:
            data.append(o)
    return data

# Add STATUS from File or Notification to Memory
def addStatusToMemory(obj, filename = None):
    global targets, elements, gnmi_credentials
    # From Notification
    if filename == None:
        #Check if are target config
        if obj.config.key.js_path == ".snmp_agent.targets.target":
            #Check if exits any config 
            if not obj.config.data.json == "{\n}\n":    
                notification_targets = json.loads(obj.config.data.json) 
                log.info(notification_targets)
                # One notification for entry
                address = obj.config.key.keys[0]
                nw_instance = notification_targets['target']['network_instance']['value']
                community_string = notification_targets['target']['community_string']['value']

                # Verify if exists in targets
                flag = False
                for t in targets:
                    if t.get_address() == address and t.get_nw() == nw_instance:
                        flag = True

                             
                #Add to Telemetry and targets element
                if not flag:
                    targets.append(Target(nw_instance,address,community_string))
                    addTargetsToTelemetry() 

                
                # Add to the File
                with open(FILENAME,"r+") as f:
                    file_data = json.load(f)
                    targets_original = []
                    
                    for t in targets:
                        targets_original.append(t.get_JSON())

                    file_data['targets'] = targets_original
                   
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
                # Mandatory parameters
                parameter = element_json['parameter']['value']
                trigger_condition = element_json['trigger_condition']['value']
                trap_oid = element_json['trap_oid']['value']

                # Optional parameters
                if "resource_filter" in element_json:
                    resource_filter = [x['value'] for x in element_json['resource_filter']]
                else:
                    resource_filter = []
                
                if "monitoring_condition" in element_json:
                    monitoring_condition = element_json['monitoring_condition']['value']
                else:
                    monitoring_condition = ""

                if "trigger_message" in element_json:
                    trigger_message = element_json['trigger_message']['value']
                else:
                    trigger_message = ""

                if "resolution_condition" in element_json:
                    resolution_condition = element_json['resolution_condition']['value']
                else:
                    resolution_condition = ""

                if "resolution_message" in element_json:
                    resolution_message = element_json['resolution_message']['value']
                else:
                    resolution_message = ""    
                

                element = Element(resource,
                            parameter,
                            monitoring_condition,
                            resource_filter,
                            trigger_condition,
                            trigger_message,
                            resolution_condition,
                            resolution_message,
                            trap_oid, 
                            False,
                            "")
               
                # Verify if exists in elements
                flag = False
                for e in elements:
                    if e.getResource() == resource: # Verify if key list 
                        flag = True

                             
                # Add element to monitoring to the list of elements
                if not flag:
                    elements.append(element)
                    # Add to Telemetry
                    addElementsToTelemetry()

                # Add to the File
                with open(FILENAME,"r+") as f:
                    file_data = json.load(f)
                    elements_original = []

                    # FROM Memory
                    for e in elements:
                        elements_original.append(e.getJSON())

                    file_data['monitoring_elements'] = elements_original
  
                    f.seek(0)
                    f.write(json.dumps(file_data, indent=4))
                    f.truncate()

                # Add to Subscribe
                paths = getPathsToSubscribe(element)

                if paths[1] == "":
                    paths.pop()

                th = threading.Thread(target=subscribe_thread, args=(paths,))
                th.start()

    # From File
    else:
        try:    
            with open(filename) as f:
                file_data_as_json = json.load(f)

                # Read GNMI Credentials
                aux = file_data_as_json['gnmi_credentials']
                gnmi_credentials = Credentials(aux['user'],aux['password'])
                

                # Add Elements to the global variable
                for element in file_data_as_json['monitoring_elements']:
                    resource = addBrackets(element['resource'])

                    # Mandatory parameters
                    parameter = element['parameter']
                    trigger_condition = element['trigger_condition']
                    trap_oid = element['trap_oid']

                    # Optional parameters
                    if "resource_filter" in element:
                        resource_filter = element['resource_filter']
                    else:
                        resource_filter = []
                    
                    if "monitoring_condition" in element:
                        monitoring_condition = element['monitoring_condition']
                    else:
                        monitoring_condition = ""

                    if "trigger_message" in element:
                        trigger_message = element['trigger_message']
                    else:
                        trigger_message = ""

                    if "resolution_condition" in element:
                        resolution_condition = element['resolution_condition']
                    else:
                        resolution_condition = ""

                    if "resolution_message" in element:
                        resolution_message = element['resolution_message'] 
                    else:
                        resolution_message = ""    
                    
                    e = Element(resource,
                                parameter,
                                monitoring_condition,
                                resource_filter,
                                trigger_condition,
                                trigger_message,
                                resolution_condition,
                                resolution_message,
                                trap_oid, 
                                False,
                                "")

                    # Add element to monitoring to the list of elements
                    elements.append(e)

                # Add to Telemetry
                addElementsToTelemetry()

                # Add targets to the global variable       
                for target in file_data_as_json['targets']:
                    flag = False
                    for t in targets:
                        if target['address'] == t.get_address() and target['nw-instance'] == t.get_nw():
                            flag = True

                    if not flag:
                        nw_instance = target['nw-instance']
                        address = target['address']
                        community_string = target['community-string']
                        targets.append(Target(nw_instance,address,community_string))
                        
                # Add Targets to State
                if not len(targets) == 0:
                    addTargetsToTelemetry()
                
                # Add to Config
                addStatusToConfigDataStore()


        except Exception as e:
            logging.info(f"Exception caught while reading file :: {e}")
            #Set programed status as false
            return False

############################################################
## Function to introduce memory in Config Datastore
## Targets and Elements with formated paths
############################################################
def addStatusToConfigDataStore():
    global elements, targets
    # Add Targets
    for t in targets:
        data = t.gNMISetOperation(log)
        gnmiSET(data)

    # Add Elements
    for e in elements:
        data = e.gNMISetOperation(log)
        gnmiSET(data)

############################################################
## GNMI SET OPERATION
## input: formatted path to update 
## return: None
############################################################
def gnmiSET(update_path) -> None:
    global gnmi_credentials 
    with gNMIclient(target= host, username=gnmi_credentials.getUser(), password=gnmi_credentials.getPassword(), insecure=True, debug = True) as gc:
        try:
            data = gc.set(update=update_path,encoding="json_ietf")
            #log.info(f"gNMI SET Operation ::: {data}")
        except Exception as e:
            log.info(e)

############################################################
## Delete Config Operation
## input: obj
## return: 
############################################################
def delStatusofMemory(obj):
    global elements, targets
    #REMOVE TARGET ELEMENT
    if obj.config.key.js_path == ".snmp_agent.targets.target":
        #Remove From Memory
        key = obj.config.key.keys[0]
        for i in range(len(targets)):
            if targets[i].get_address() == key:
                targets.pop(i)
                break
        
        # Update Targets to State
        removeTargetsOfTelemetry(key)
        # Update Config
        addStatusToConfigDataStore()
        log.info("ENTROU AQUI")
        #Remove From File
        with open(FILENAME,"r+") as f:
            file_data = json.load(f) 
            for i in range(len(file_data['targets'])):
                if file_data['targets'][i]['address'] == key:
                    file_data['targets'].pop(i)
                    break

            f.seek(0)
            f.write(json.dumps(file_data, indent=4))
            f.truncate()

    #REMOVE MONITORING ELEMENT
    elif obj.config.key.js_path == ".snmp_agent.monitoring_elements.element":
        #Remove From Memory
        key = obj.config.key.keys[0]
        for i in range(len(elements)):
            if elements[i].getResource() == key:
                elements.pop(i)
                break
        

        # Update Elements to State
        removeElementsOfTelemetry(key)
        # Update Config
        addStatusToConfigDataStore()
        
        #Remove From File
        with open(FILENAME,"r+") as f:
            file_data = json.load(f) 
            for i in range(len(file_data['monitoring_elements'])):
                if file_data['monitoring_elements'][i]['resource'] == key:
                    file_data['monitoring_elements'].pop(i)
                    break

            f.seek(0)
            f.write(json.dumps(file_data, indent=4))
            f.truncate()





def changeStatusOfMemory(obj):
    #log.info(obj)
    #Check if are target config
    if obj.config.key.js_path == ".snmp_agent.targets.target":
        #Check if exits any config 
        if not obj.config.data.json == "{\n}\n":
            #Return the JSON from the object    
            notification_target = json.loads(obj.config.data.json) 

            # One notification for entry
            address = obj.config.key.keys[0]
            nw_instance = notification_target['target']['network_instance']['value']

            for t in targets:
                if t.get_address() == address :
                    t.set_nw(nw_instance)
                           
            #Add to Telemetry and targets element
            addTargetsToTelemetry() 
            
            # Add to the File
            with open(FILENAME,"r+") as f:
                file_data = json.load(f)
                
                for target in file_data['targets']:
                    if target['address'] == address:
                        target['nw-instance'] = nw_instance
                
                # Eliminate duplicates 
                aux_targets = []
                for target in file_data['targets']:
                    if target not in aux_targets :
                        aux_targets.append(target)

                file_data['targets'] = aux_targets 

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
            # Mandatory parameters
            parameter = element_json['parameter']['value']
            trigger_condition = element_json['trigger_condition']['value']
            trap_oid = element_json['trap_oid']['value']

            # Optional parameters
            if "resource_filter" in element_json:
                resource_filter = [x['value'] for x in element_json['resource_filter']]
            else:
                resource_filter = []
            
            if "monitoring_condition" in element_json:
                monitoring_condition = element_json['monitoring_condition']['value']
            else:
                monitoring_condition = ""

            if "trigger_message" in element_json:
                trigger_message = element_json['trigger_message']['value']
            else:
                trigger_message = ""

            if "resolution_condition" in element_json:
                resolution_condition = element_json['resolution_condition']['value']
            else:
                resolution_condition = ""

            if "resolution_message" in element_json:
                resolution_message = element_json['resolution_message']['value']
            else:
                resolution_message = ""    
            

            for e in elements:
                if e.getResource() == resource: # Verify if key list 
                    e.setChangeOperation(parameter, 
                                        monitoring_condition,
                                        resource_filter, 
                                        trigger_condition,
                                        trigger_message,
                                        resolution_condition,
                                        resolution_message,
                                        trap_oid)
                            
            addElementsToTelemetry()

            # Add to the File
            with open(FILENAME,"r+") as f:
                file_data = json.load(f)
                elements_original = []

                for e in elements:
                    elements_original.append(e.getJSON())

                file_data['monitoring_elements'] = elements_original
 
                f.seek(0)
                f.write(json.dumps(file_data, indent=4))
                f.truncate()              


##################################################################
## Proc to process the config Notifications received by snmp_agent
## At present processing config from js_path = .snmp_agent
##################################################################
def Handle_Notification(obj) -> bool:
    if obj.HasField('config') and obj.config.key.js_path != ".commit.end":
        log.info(f"OPeration:{obj.config.op}")
        if obj.config.op == 0: # Add Config Operation
            if "snmp_agent" in obj.config.key.js_path:
                addStatusToMemory(obj)
        elif obj.config.op == 1: # Change Configuration 
            
            changeStatusOfMemory(obj)
        elif obj.config.op == 2: # Delete Configuration 
            log.info("Delete HANDLER")
            delStatusofMemory(obj)
        else:
            log.info("SOMETHING GONE WRONG")        
    #always return
    return False

def NotificationStreamThread(stream_id):
    sub_stub = sdk_service_pb2_grpc.SdkNotificationServiceStub(channel)
    stream_request = sdk_service_pb2.NotificationStreamRequest(stream_id=stream_id)
    stream_response = sub_stub.NotificationStream(stream_request, metadata=metadata)
    time.sleep(2)
    for r in stream_response:
        #log.info(r.notification)
        for obj in r.notification:
            Handle_Notification(obj)



############################################################
## Function to send keep alives to the NDK
############################################################
def send_keep_alive():
    global thread_exit
    while not thread_exit:
        keep_alive_response = stub.KeepAlive(request=sdk_service_pb2.KeepAliveRequest(),metadata=metadata)
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
    
    global gnmi_credentials, queue

    with gNMIclient(target=host, username=gnmi_credentials.getUser(), password=gnmi_credentials.getPassword(), insecure=True, debug = True) as gc:
        telemetry_stream = gc.subscribe(subscribe=subscribe)
        #pygnmi implements this 'for' as infinite loop
        for telemetry_entry in telemetry_stream: # Block Here
            telemetry_entry_str = telemetryParser(telemetry_entry) 
            if not "sync_response" in telemetry_entry_str :
                queue.put(telemetry_entry_str)

def getGNMIPath(path):
    global gnmi_credentials
    with gNMIclient(target= host, username=gnmi_credentials.getUser(), password=gnmi_credentials.getPassword(), insecure=True, debug = True) as gc:
        return gc.get(path,encoding="json_ietf")

############################################################
## Function to send SNMP Trap with the apropriate format
############################################################
def sendSNMPTrap(msg_entry,target,trap_oid_1,trap_oid_2):  
    p = f"ip netns exec {target.get_nw()} snmptrap -v 2c -c {target.get_community_string()} {target.get_address()} 0 {trap_oid_1} {trap_oid_2} s \"{msg_entry}\""
    out = subprocess.run(p, shell=True)
    return None


def sendToAllTargets(msg_entry,t1,t2):
    global targets
    for target in targets:
        sendSNMPTrap(msg_entry,target,t1,t2)

def getPathsToSubscribe(element):
    path = element.getPath()
    monitoring_path = ""

    if not element.getMonitoringCondition() == "":
        monitoring_path = element.getMonitoringPath()
    
    return [path,monitoring_path]

def addGlobalPaths():
    global global_paths,elements
    for element in elements:
        #Populate global paths with subscribe paths
        path = element.getPath()
        global_paths.append(path)
        #
        if not element.getMonitoringCondition() == "":
            monitoring_path = element.getMonitoringPath()
            global_paths.append(monitoring_path)


def cleanUPPath(e):
    pattern = "/[a-zA-Z]+_([a-zA-Z]+(-[a-zA-Z]+)+):"
    clean_path  = e['path']
    
    while len(clean_path.split(":")) > 2 :
        clean_path = re.sub(pattern,"/",clean_path)

    clean_path = clean_path.split(":")[1]# Clean the path model
    #log.info(f"Path Clean: {clean_path}")

    if ":" in clean_path:
        log.info("Error: Exitence of \":\" in path ")

    # ADD: PATH + PARAMETER
    if isinstance(e['val'],str): # Entry with parameter in the path
        value = e['val']
        entry_path = clean_path
    else:   # Entry without parameter in the path
        value = list(e['val'].items())[0][1]
        entry_path = clean_path+"/"+list(e['val'].keys())[0]

    return entry_path,value


def processEntry(entry):
    global elements
    # Can be more than one entry from subscribe
    for e in entry:
        log.info("Original Entry : " + str(e))
        # Clean up the path removing the model and adding the parameter
        entry_path, value = cleanUPPath(e)  
        #log.info("Clean Stage: " + str(entry_path))
        for element in elements:
            path = element.getResource()
            # Verify if entry belongs to this element
            if element.verifyIfEntryBelongs(log,entry_path,value):
                #log.info("Entry Belongs")
                # Verify if entry exists in subpaths
                if entry_path in element.getSubPathsKeys():
                    # Proceed to updates and checks triggers conditions
                    result, event, base_trap_oid, specified_trap_oid = element.updateStatus(log,entry_path,value)
                    #log.info("Result: " + str(result))
                    if result:
                        #log.info("Original Entry : " + str(e))
                        log.info(f"SEND SNMP TRAP with the Event: {event}")
                        sendToAllTargets(event + ": " + entry_path,base_trap_oid,specified_trap_oid)
                        element.set_traps_generated(element.get_traps_generated() + 1)
                        # Add to Telemetry
                        addElementsToTelemetry()
                    break
                    
                else:
                    # Verify if is a monitoring path or normal path 
                    if element.verifyIfIsMonitoringPath(entry_path):
                        # ADD STATUS to subpath monitoring
                        #log.info("Enter Monitoring Path")
                        resource = "/".join(entry_path.split("/")[:-1])
                        key_path = resource +"/"+ element.getParameter()
                        #log.info(resource + "|" + key_path)
                        element.setSubPath(log,key_path,value)
                        break

                    elif not element.verifyIfIsMonitoringPath(entry_path):
                        # First time of the entry
                        # Check Resource Filter
                        #log.info("Add Entry for the First Time")
                        if element.checkFilter(log,entry_path):
                            #log.info("Passed on Filter Condition")
                            element.addPath(entry_path,value)
                        break

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


    if os.path.exists(FILENAME):
        addStatusToMemory(None,FILENAME)
        time.sleep(0.5)

    
    notificationStreamThread = threading.Thread(target=NotificationStreamThread, args=(stream_id,))
    notificationStreamThread.start()
    ####################################################################################
    # Add Global Paths from Elements
    ####################################################################################
    addGlobalPaths()

    ####################################################################################
    # START OF GNMI SUBSCRIBE THREAD
    ####################################################################################
    th = threading.Thread(target=subscribe_thread, args=(global_paths,))
    th.start()

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
    log.info("\n\n\n\n\n\n")
    log.info("\tSTART TIME :: {}".format(datetime.datetime.now()))
    log.info("\n\n\n\n\n\n")
    if Run():
        log.info('Agent unregistered and agent routes withdrawed from dut')
    else:
        log.info(f'Some exception caught, Check !')