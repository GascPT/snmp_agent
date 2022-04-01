#"monitoring_elements":[
#        {
#            "resource":"interface[name=*]/",
#            "parameter":"admin-state", 
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
                trigger_condition):

        self._resource = resource
        self._parameter = parameter
        self._monitoring_condition = monitoring_condition
        self._resource_filter = resource_filter
        self._trigger_condition = trigger_condition


    
    