import unittest
from pathlib import Path
from all_auto.core import check_product

class FreePriceSafetyTests(unittest.TestCase):
    def make(self,amount=0,free_approved=False,approved_by="",currency="JPY"):
        item={"id":"sampleapp","type":"app","submission_kind":"new",
              "price":{"amount_minor":amount,"currency":currency,
                       "free_approved":free_approved,"approved_by":approved_by},
              "owner_approved_for_draft":free_approved}
        return check_product(item,Path("."))
    def test_free_never_approved_by_default(self):
        result=self.make()
        self.assertIn("FREE_PRICE_NOT_APPROVED",result["findings"])
        self.assertEqual(result["status"],"HOLD")
    def test_approved_free_price_is_not_price_hold(self):
        result=self.make(free_approved=True,approved_by="operator-confirmed")
        self.assertNotIn("FREE_PRICE_NOT_APPROVED",result["findings"])
        self.assertEqual(result["status"],"HOLD")
    def test_invalid_currency_stays_hold(self):
        result=self.make(free_approved=True,approved_by="operator-confirmed",currency="ZZZ")
        self.assertIn("CURRENCY_UNCONFIRMED",result["findings"])
    def test_negative_price_is_hold(self):
        result=self.make(amount=-1,free_approved=True,approved_by="operator-confirmed")
        self.assertIn("PRICE_UNCONFIRMED",result["findings"])
    def test_positive_price_does_not_require_free_flag(self):
        result=self.make(amount=499)
        self.assertNotIn("FREE_PRICE_NOT_APPROVED",result["findings"])

if __name__=="__main__":
    unittest.main()
