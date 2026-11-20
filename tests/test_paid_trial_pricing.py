import unittest
from pathlib import Path
from all_auto.core import check_product

class PaidTrialPricingTests(unittest.TestCase):
    def make(self, amount=499, approved_by="owner-confirmed", trial="7_days",
             trial_approved_by="owner-confirmed", owner=True):
        item={
            "id":"sampleapp","type":"app","submission_kind":"new",
            "price":{"amount_minor":amount,"currency":"JPY","approved_by":approved_by,
                     "approval_required":True,"free_trial":trial,"trial_approved_by":trial_approved_by},
            "owner_approved_for_draft":owner,
        }
        return check_product(item,Path("."))

    def test_paid_price_requires_approval_source(self):
        result=self.make(approved_by="")
        self.assertIn("PAID_PRICE_NOT_APPROVED",result["findings"])

    def test_owner_approved_paid_price_clears_price_approval_hold(self):
        result=self.make()
        self.assertNotIn("PAID_PRICE_NOT_APPROVED",result["findings"])

    def test_7_day_trial_requires_separate_approval_source(self):
        result=self.make(trial_approved_by="")
        self.assertIn("FREE_TRIAL_NOT_APPROVED",result["findings"])

    def test_approved_7_day_trial_clears_trial_approval_hold(self):
        result=self.make()
        self.assertNotIn("FREE_TRIAL_NOT_APPROVED",result["findings"])

    def test_trial_is_invalid_for_free_product(self):
        result=self.make(amount=0)
        self.assertIn("TRIAL_REQUIRES_PAID_PRODUCT",result["findings"])

if __name__=="__main__": unittest.main()
