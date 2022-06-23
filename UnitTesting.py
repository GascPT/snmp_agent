import unittest

from snmp_agent import *


class TestSNMPFunctions(unittest.TestCase):

    def test_string_normalizer(self):
        self.assertEqual(addBrackets("asd"),addBrackets("asd/"))
    
    def test_string_normalizer2(self):
        self.assertEqual(addBrackets("asd"),addBrackets("asd/"))


if __name__ == '__main__':
    unittest.main()