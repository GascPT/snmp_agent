#"monitoring_elements":[
#        {
#            "resource":"interface[name=*]/",
#            "parameter":"oper-state", 
#            "monitoring_condition":{
#                "admin-state":"enable"
#            },
#            "resource_filter":"ethernet*", 
#            "trigger_condition":"up -> down"
#        }
#    ]

class Element: 
    def __init__(self, 
                resource, 
                parameter, 
                monitoring_condition,
                resource_filter, 
                trigger_condition,
                watched):

        self._resource = resource
        self._parameter = parameter
        self._monitoring_condition = monitoring_condition
        self._resource_filter = resource_filter
        self._trigger_condition = trigger_condition
        self._watched = watched
        self._paths = []
        self._previous_status = ""

    def isWatched(self):
        return self._watched

    def setWatched(self,watched):
        self._watched = watched
        return self._watched

    def getPath(self):
        return self._resource + self._parameter

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

    def addPaths(self,path):
        self._paths.append(path)

    def getPaths(self):
        return self._paths

    def getTrigger(self):
        return self._trigger_condition

    def getStatus(self):
        return self._previous_status

    def setStatus(self,status):
        self._previous_status = status
    
    def verifyIfExistPath(self, entry_path):
        if entry_path in self._paths:
            return True
        return False 

    def print(self):
        return f"Element -> \n Resource : {self._resource}\n Parameter : {self._parameter}\n Monitoring : {self._monitoring_condition}\n Resource Filter : {self._resource_filter}\n Trigger Condition : {self._trigger_condition}\n"

    
    