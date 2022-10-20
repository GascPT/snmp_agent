class Target:
    def __init__(self, nw_instance,address,community_string):
        self._nw_instance = nw_instance
        self._address = address
        self._community_string = community_string

    def get_nw(self):
        return self._nw_instance
    
    def get_address(self):
        return self._address

    def get_community_string(self):
        return self._community_string

    def gNMISetOperation(self,log):
        base_path = f"/snmp-agent/targets/target[address={self._address}]"   
        data = [
            (
                f"{base_path}/network-instance",
                f'{self._nw_instance}'
            ),
            (
                f"{base_path}/community-string",
                f'{self._community_string}'
            )
        ]
        return data

    def get_JSON(self):
        return {
                    "nw-instance": self._nw_instance,
                    "address": self._address,
                    "community-string": self._community_string
                }

    def set_nw(self,nw):
        self._nw_instance = nw

    def set_address(self,address):
        self._address = address

    def set_community_string(self,community_string):
        self._community_string = community_string