import unittest
from unittest.mock import *
from banklite import *

class TestPaymentProcessor(unittest.TestCase):
    def setUp(self):
        self.gateway = MagicMock()
        self.audit   = MagicMock()
        self.proc    = PaymentProcessor(self.gateway, self.audit)

    def _make_tx(self, amount=100.00, tx_id="TX-001", user_id=1):
        return Transaction(tx_id=tx_id, user_id=user_id, amount=amount);
    
    def test_successful_charge(self):
        self.gateway.charge.return_value = True
        tx = self._make_tx()
        result = self.proc.process(tx);
        self.assertEqual(result,"success")
    
    def test_failed_charge(self):
        self.gateway.charge.return_value = False
        tx = self._make_tx()

        result = self.proc.process(tx)
        self.assertEqual(result,"declined")
