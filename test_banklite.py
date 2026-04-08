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

class TestStatementBuilder(unittest.TestCase):
    def setUp(self):
        self.repo    = MagicMock()
        self.builder = StatementBuilder(self.repo)
    
    def test_no_transactions(self):
        self.repo.find_by_user.return_value = []
        result = self.builder.build(user_id=1)

        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total_charged"], 0.0)
        self.assertIsInstance(result["transactions"], list)

    def test_success_transaction(self):
        self.repo.find_by_user.return_value = [
            Transaction("Test 1", 7, 10.00, status="success"),
            Transaction("Test 2", 7,  50.00, status="declined"), 
            Transaction("Test 3", 7, 25.00, status="success"),
            Transaction("Test 4", 7,  75.00, status="pending"), 
        ]

        result = self.builder.build(user_id=10)
        self.assertEqual(result["total_charged"], 35.00)
        self.assertEqual(result["count"], 4)   

    def test_mixed_transactions(self):
        self.repo.find_by_user.return_value = [
            Transaction("Test 1", 3, 5.00, status="success"),
            Transaction("Test 2", 3,  5.00, status="success"), 
            Transaction("Test 3", 3, 5.00, status="success"),
            Transaction("Test 4", 3,  5.00, status="success"), 
        ]

        result = self.builder.build(user_id=3)
        self.assertEqual(result["total_charged"], 20.00)
        self.assertEqual(result["count"], 4) 
    
    def test_rounding(self):
        self.repo.find_by_user.return_value = [
            Transaction("Test 1", 3, 5.0067, status="success"),
            Transaction("Test 2", 3,  5.0094, status="success"), 
        ]

        result = self.builder.build(user_id=3)
        self.assertEqual(result["total_charged"], 10.02)
        self.assertEqual(result["count"], 2) 

    def test_transaction_return(self):
        return1 = [
            Transaction("Test 1", 3, 5.0067, status="success"),
            Transaction("Test 2", 3,  5.0094, status="success"), 
        ]
        self.repo.find_by_user.return_value = return1

        result = self.builder.build(user_id=3)

        self.assertEqual(result["transactions"],return1)
    
class TestCheckoutServiceWithSpy(unittest.TestCase):
    def setUp(self):
        self.calculator      = FeeCalculator()
        self.spy_calc  = MagicMock(wraps=self.calculator)
        self.gateway   = MagicMock()
        self.gateway.charge.return_value = True
        self.service       = CheckoutService(self.spy_calc, self.gateway)

    def _usd_tx(self, amount=100.00):
        return Transaction("TX-USD", 1, amount, currency="USD")

    def _eur_tx(self, amount=200.00):
        return Transaction("TX-EUR", 1, amount, currency="EUR")

    
    def test_correct_usd(self):
        result = self.calculator.processing_fee(100);
        self.assertEqual(result,3.20)

    def test_correct_international(self):
        result = self.calculator.processing_fee(200,"EUR")
        self.assertEqual(result,9.10)

    def test_correct_processing_args(self):
        tx = self._usd_tx(250.00)
        self.service.checkout(tx)

        self.spy_calc.processing_fee.assert_called_once_with(250.00, "USD")

    def test_correct_net_args(self):
        tx = self._usd_tx(250.00)
        self.service.checkout(tx)

        self.spy_calc.net_amount.assert_called_once_with(250.00, "USD")
    
    def test_called_exactly_once(self):
        self.service.checkout(self._usd_tx(500.00))

        self.assertEqual(self.spy_calc.processing_fee.call_count, 1)
        self.assertEqual(self.spy_calc.net_amount.call_count, 1)

    def test_receipt_flow(self):
        receipt = self.service.checkout(self._usd_tx(100.00))

        self.assertEqual(receipt["fee"], 3.2)
        self.assertEqual(receipt["net"], 96.8)

    def test_only_net_amount(self):
        calculator = FeeCalculator()
        service = CheckoutService(calculator, self.gateway)
        tx = self._usd_tx(500.00)

        with patch.object(calculator, "net_amount", wraps=calculator.net_amount) as spy_net:
            receipt = service.checkout(tx)
        
        spy_net.assert_called_once_with(500.00, "USD")
        self.assertEqual(receipt["net"], 485.20)

    def test_contrast(self):
        mock_calc = MagicMock()
        mock_calc.processing_fee.return_value = 5.00
        mock_calc.net_amount.return_value     = 95.00 

        service = CheckoutService(mock_calc, self.gateway)
        receipt = service.checkout(self._usd_tx(100.00))

        self.assertEqual(receipt["fee"],    5.00)
        self.assertEqual(receipt["net"],   95.00)
        self.assertEqual(receipt["status"], "success")
        mock_calc.processing_fee.assert_called_once()










