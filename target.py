class Target:
    def __init__(self, nw_instance,address):
        self._nw_instance = nw_instance
        self._address = address

    def get_nw(self):
        return self._nw_instance
    
    def get_address(self):
        return self._address