#"monitoring_elements":[
#        {
#            "resource":"interface[name=*]/",
#            "parameter":"oper-state", 
#            "monitoring_condition":"admin-state=enable",    
#            "resource_filter":"ethernet*", 
#            "trigger_condition":"up -> down",
#            "trigger_message":"oper-down-reason"
#        }
#    ]
import re


class Element: 
    def __init__(self, 
                resource, 
                parameter, 
                monitoring_condition,
                resource_filter, 
                trigger_condition,
                watched,status):

        self._resource = resource
        self._parameter = parameter
        self._monitoring_condition = monitoring_condition
        self._resource_filter = resource_filter
        self._trigger_condition = trigger_condition
        self._watched = watched
        self._paths = {}
        self._monitoring_status = ""
        self._previous_status = status

    def isWatched(self):
        return self._watched

    def setWatched(self,watched):
        self._watched = watched
        return self._watched

    def getPath(self):
        return self._resource + self._parameter

    def getMonitoringPath(self):
        m = self._monitoring_condition
        if "=" in m:
            m = m.split("=")[0]
        if self._resource[-1] == '/':
            return self._resource + m 
        else:
            return self._resource +"/"+ m 

    def getMonitoringParameter(self):
        m = self._monitoring_condition
        if "=" in m:
            m = m.split("=")[0]

        return m 
 
    def getParameter(self):
        return self._parameter
    
    def getResource(self):
        return self._resource

    def getMonitoring(self):
        return self._monitoring_condition
    
    def getKey(self):
        return self._resource

    def getFilter(self):
        return self._resource_filter

    def getJSONElement(self):
        e = {
            'element': {
                'parameter' : 
                    {'value': f'{self._parameter}'},
                'monitoring_condition' : 
                    {'value': f'{self._monitoring_condition}'},
                'resource_filter' : 
                    {'value': f'{self._resource_filter}'},
                'trigger_condition' : 
                    {'value': f'{self._trigger_condition}'}
            }
        }
        #log.info(json.dumps(e,indent = 4))
        return e

    def addPath(self,entry_path,value):
        resource = "/".join(entry_path.split("/")[:-1])
        self._paths[entry_path] = Element(resource,self._parameter,self._monitoring_condition,self._resource_filter,self._trigger_condition, False,value)
        

    def getSubPathsKeys(self):
        return self._paths.keys()

        
    def getPaths(self):
        return self._paths

    def addMonitoringPath(self,path):
        self._monitoring_path = path

    #def getMonitoringPath(self):
    #    return self._monitoring_path

    def getMonitoringStatus(self):
        return self._monitoring_status

    def setMonitoringStatus(self,status):
        self._monitoring_status = status

    def getTrigger(self):
        return self._trigger_condition

    def getStatus(self):
        return self._previous_status

    def setStatus(self,status):
        self._previous_status = status
    
    def verifyIfExistPath(self, entry_path):
        if entry_path in self._paths:
            return "path"
        if entry_path in self._monitoring_condition:
            return "monitorig_path"
        return "False" 

    def print(self):
        return f"Element -> \n Resource : {self._resource}\n Parameter : {self._parameter}\n Monitoring : {self._monitoring_condition}\n Resource Filter : {self._resource_filter}\n Trigger Condition : {self._trigger_condition}\n Status : {self._previous_status}\n Monitoring Path : {self.getMonitoringPath()}\n Monitoring Status : {self._monitoring_status}\n"
            
    
    def verifyIfEntryBelongs(self,log, entry_path, value):
        element_path = self._resource
 
        list_entry_path = self.cleanUpEntry(entry_path)
        list_element_path = self.cleanUpEntry(element_path)
        #log.info(list_entry_path)
        #log.info(list_element_path)
        i = 0
        for a in list_entry_path:
            #Verify existence of a key
            if i >= len(list_element_path):
                    if a == self._parameter or a == self.getMonitoringParameter():
                        return True
                    else:
                        log.info("Last position dont match")
                        return False
            
            b = list_element_path[i]
            i = i + 1
            if '[' in a and ']' in a:
                
                # Compare before keys
                left_entry = a.split('[')[0]
                left_elem = b.split('[')[0]
                if not left_entry == left_elem:
                    #log.info("Elements before keys dont match")
                    return False

                entry_key = a.split('[')[1].lstrip().split(']')[0].split('=')[1]
                
                #Verify Existence of Key in Elem
                if not '[' in b and not ']' in b:
                    #log.info("Dont exist key in element path")
                    return False

                elem_key = b.split('[')[1].lstrip().split(']')[0].split('=')[1]

                if entry_key == elem_key:
                    continue
                elif elem_key == '*':
                    continue
                else:
                    #log.info("Keys don't match")
                    return False

            else:

                if i >= len(list_entry_path):
                    if a == self._parameter or a == self.getMonitoringParameter():
                        return True
                if not a == b:
                    #log.info("Elements not equal in the path")
                    return False
                       
        log.info("Sommething bad happens")   
        return False
    

    def cleanUpEntry(self,entry):
        elem = re.split('/(?=[^0-9])',entry)

        elem = list(filter(None,elem))
        for i in range(len(elem)):
            if elem[i][-1] == '/':
                elem[i] = elem[i][:-1]

        return elem

    def verifyIfIsMonitoringPath(self,entry_path):
        entry_parameter = entry_path.split("/")[-1]

        if entry_parameter == self.getMonitoringParameter():
            return True

    def setSubPath(self,log,key_path,value):
        self._paths[key_path].setMonitoringStatus(value)
        

    def updateStatus(self,log, entry_path, value):

        trigger = self._paths[entry_path].getTrigger()

        if self._paths[entry_path].getStatus() == "": # If previous status are empty
            self._paths[entry_path].setStatus(value)
            return False
        
        if "->" in trigger: # Change from value 1 to value 2
            val1,val2 = trigger.split("->")
            if self._paths[entry_path].getStatus() == val1 and val2 == value:
                self._paths[entry_path].setStatus(value)
                return True,"Message"
            self._paths[entry_path].setStatus(value)

        elif "!=" in trigger: # TODO Different from one value
            val1 = trigger.replace("!=","")
            if self._paths[entry_path].getStatus() == val1 and val1 != value:
                self._paths[entry_path].setStatus(value)
                return True,"Message"
            self._paths[entry_path].setStatus(value)
            

        return False,""

    def checkFilter(self,log,entry_path):
        # TODO Verify correctness
        entry_key = entry_path.split('[')[1].lstrip().split(']')[0].split('=')[1]
        if len(self._resource_filter) == 0:
            return True

        for filt in self._resource_filter:
            if entry_key in filt:
                return True
            elif "*" in filt:
                if filt.split("*")[0] in entry_key:
                    return True
        
        return False
    