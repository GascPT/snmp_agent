class Target:
    def __init__(self, nw_instance,address):
        self._nw_instance = nw_instance
        self._address = address

    def get_nw(self):
        return self._nw_instance
    
    def get_address(self):
        return self._address

    def gNMISetOperation(self,log):
        base_path = f"/snmp-agent/targets/target[address={self._address}]"   
        data = [
            (
                f"{base_path}/network-instance",
                f'{self._nw_instance}'
            )
        ]
        return data

    def get_JSON(self):
        return {
                    "nw-instance": self._nw_instance,
                    "address": self._address
                }