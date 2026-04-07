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

    def test_zero(self):
        result = self._make_tx(0)
        self.assertRaises(ValueError)

    def test_negative(self):
        result = self._make_tx(-67)
        self.assertRaises(ValueError)
    
    def test_take_it_to_the_limit(self):
        result = self._make_tx(10001)
        self.assertRaises(ValueError)
    
    def test_success_audit(self):
        self.gateway.charge.return_value = True
        tx = self._make_tx()
        result = self.proc.process(tx);

        self.audit.record.assert_called_once_with(
            "CHARGED", tx.tx_id, {"amount": tx.amount}
        )

    def test_decline_audit(self):
        self.gateway.charge.return_value = False
        tx = self._make_tx()
        result = self.proc.process(tx)
        
        self.audit.record.assert_called_once_with(
            "DECLINED", tx.tx_id, {"amount": tx.amount}
        )
    
    def test_invalid_audit(self):
        tx = self._make_tx(1000000000)
        with self.assertRaises(ValueError):
            self.proc.process(tx)

        self.audit.record.assert_not_called()


class TestFraudAwareProcessor(unittest.TestCase):
    def setUp(self):
        self.gateway  = MagicMock()   # stubs charge() True/False
        self.detector = MagicMock()   # stubs check() → FraudCheckResult
        self.mailer   = MagicMock()   # mock: assert on send_* calls
        self.audit    = MagicMock()   # mock: assert on record() calls
        self.proc = FraudAwareProcessor(
            gateway=self.gateway,
            detector=self.detector,
            mailer=self.mailer,
            audit=self.audit,
        )
    
    def _safe_result(self, risk_score=0.1):
        return FraudCheckResult(approved=True, risk_score=risk_score)

    def _fraud_result(self, risk_score=0.9):
        return FraudCheckResult(approved=False, risk_score=risk_score)
    
    def _make_tx(self, amount=100.00, tx_id="TX-001", user_id=1):
        return Transaction(tx_id=tx_id, user_id=user_id, amount=amount)

    def test_high_risk_score(self):
        self.detector.check.return_value = self._fraud_result(risk_score=0.9)
        tx = self._make_tx()
        result = self.proc.process(tx)

        self.assertEqual(result, "blocked")

    def test_exact_risk_score(self):
        self.detector.check.return_value = self._fraud_result(risk_score=0.75)
        tx = self._make_tx()
        result = self.proc.process(tx)

        self.assertEqual(result, "blocked")
    
    def test_low_risk_successful_charge(self):
        self.detector.check.return_value = self._safe_result(risk_score=0.1)

        self.gateway.charge.return_value = True
        tx = self._make_tx()
        result = self.proc.process(tx)

        self.assertEqual(result, "success")

    def test_low_risk_declined_charge(self):
        self.detector.check.return_value = self._safe_result(risk_score=0.1)

        self.gateway.charge.return_value = False
        tx = self._make_tx()
        result = self.proc.process(tx)

        self.assertEqual(result, "declined")
    
    def test_connection_error(self):
        self.detector.check.side_effect = ConnectionError("API down")
        tx = self._make_tx()

        with self.assertRaises(ConnectionError):
            self.proc.process(tx)
            self.gateway.charge.assert_not_called()
    
    def test_fraud_alert(self):
        self.detector.check.return_value = self._fraud_result()
        tx = self._make_tx(tx_id="TX1", user_id=67)
        self.proc.process(tx)
        self.mailer.send_fraud_alert.assert_called_once_with(67, "TX1")

    def test_email_args(self):
        self.detector.check.return_value = self._safe_result()
        self.gateway.charge.return_value = True
        tx = self._make_tx(amount = 999, tx_id="TX1", user_id=67)
        self.proc.process(tx)
        self.mailer.send_receipt.assert_called_once_with(67, "TX1", 999)