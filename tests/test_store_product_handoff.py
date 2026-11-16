import unittest
import json
from pathlib import Path
from all_auto.store_product_handoff import normalize_store_product_handoff,to_windows_automator_input,apply_identity_reverify_receipt,StoreHandoffError

def sample():
    return {
      "schema_version":"store-product-handoff/2",
      "product":{"id":"folder-engine","type":"app","name":"Folder Automation Engine","edition":"standard","submission_kind":"update","submission_route":"msix_pwa_app","repository":"https://github.com/shihuiarenjinba-png/folder-automation-engine","source_ref":"codex/x","source_sha":"a"*40},
      "package":{"package_type":"msix","file_name":"Folder.msix","package_sha256":"b"*64},
      "identity":{"store_id":"9PTEST","name":"OkinawaDesktopTools.FolderAutomationEngine","publisher":"CN=TEST","version":"1.0.0.0","architecture":"x64","live_partner_center_reverified":False,"accepted_version_history_verified":False,"version_history_state":"VERIFIED_ACCEPTED_HISTORY","version_conflict":False},
      "commercial":{"model":"paid_one_time","currency":"JPY","exact_partner_center_price_value":None,"price_confirmed":False,"approved_by":None,"free_trial":"7_days","trial_confirmed":True,"trial_approved_by":"owner-confirmed","publishing_hold":"manual_publish"},
      "distribution":{"audience":"PRIVATE_AUDIENCE_TEST","known_user_group":None,"public_release_approved":False},
      "assets":{"owner_visual_approval":False},
      "security":{"package_sha256":"b"*64,"owner_confirmation_complete":False},
      "approvals":{"owner_approved_for_draft":False,"certification_submit_approved":False,"publish_approved":False}
    }

class StoreProductHandoffTests(unittest.TestCase):
    def test_incomplete_paid_folder_is_valid_shape_but_hold(self):
        n=normalize_store_product_handoff(sample())
        self.assertFalse(n["ready_for_automator_draft"])
        self.assertIn("commercial.price_value",n["missing_for_draft"])
        self.assertNotIn("commercial.trial_confirmed",n["missing_for_draft"])

    def test_complete_paid_folder_translates_to_manual_7_day_trial(self):
        p=sample()
        p["identity"]["live_partner_center_reverified"]=True
        p["identity"]["accepted_version_history_verified"]=True
        p["identity"]["version_history_state"]="VERIFIED_ACCEPTED_HISTORY"
        p["identity"]["version_conflict"]=False
        p["commercial"].update({"exact_partner_center_price_value":"LIVE_LOW_PRICE_TIER","price_confirmed":True,"approved_by":"owner-confirmed"})
        p["distribution"]["known_user_group"]="owner-testers"
        p["assets"]["owner_visual_approval"]=True
        p["security"]["owner_confirmation_complete"]=True
        p["approvals"]["owner_approved_for_draft"]=True
        n=normalize_store_product_handoff(p)
        self.assertTrue(n["ready_for_automator_draft"])
        a=to_windows_automator_input(n,package_path="C:/x.msix",images_dir="C:/images")
        self.assertEqual(a["price_mode"],"paid")
        self.assertEqual(a["fields"]["free_trial"]["value"],"7_days")
        self.assertEqual(a["fields"]["free_trial"]["mode"],"manual")

    def test_exact_folder_fixture_is_hold_only_on_live_commercial_gates(self):
        path=Path(__file__).parent/"fixtures"/"folder_engine_paid_trial_handoff_v2.json"
        n=normalize_store_product_handoff(json.loads(path.read_text(encoding="utf-8")))
        self.assertFalse(n["ready_for_automator_draft"])
        self.assertEqual(n["commercial"]["free_trial"],"7_days")
        self.assertEqual(n["package"]["package_sha256"],
                         "911f8eb13abfdbb51bea8f279006d138d6be9cba4a25413416c1d70458676450")
        expected={
            "commercial.price_confirmed",
            "commercial.approved_by",
            "commercial.price_value",
            "assets.owner_visual_approval",
            "security.owner_confirmation_complete",
            "approvals.owner_approved_for_draft",
            "distribution.known_user_group",
        }
        self.assertEqual(set(n["missing_for_draft"]),expected)

    def test_identity_receipt_advances_only_live_identity_gate(self):
        p=sample()
        p["identity"]["package_family_name"]="OkinawaDesktopTools.FolderAutomationEngine_j8yefg9jgfh58"
        p["identity"]["package_sid"]="S-1-15-2-1-2-3-4-5-6-7"
        receipt={
            "schema_version":"existing-store-identity-reverify-receipt/1",
            "status":"EXISTING_IDENTITY_EXACT_MATCH",
            "partner_center_reverified":True,
            "source_sha":"a"*40,
            "package_sha256":"b"*64,
            "store_id":"9PTEST",
            "identity_name":"OkinawaDesktopTools.FolderAutomationEngine",
            "publisher":"CN=TEST",
            "package_family_name":"OkinawaDesktopTools.FolderAutomationEngine_j8yefg9jgfh58",
            "package_sid":"S-1-15-2-1-2-3-4-5-6-7",
            "created_or_reserved_product":False,
            "submission_started":False,
            "package_uploaded":False,
            "pricing_changed":False,
            "submitted":False,
            "published":False,
        }
        n=apply_identity_reverify_receipt(p,receipt)
        self.assertTrue(n["identity"]["live_partner_center_reverified"])
        self.assertFalse(n["identity"]["accepted_version_history_verified"])
        self.assertIn("identity.version_history_ready",n["missing_for_draft"])
        self.assertNotIn("identity.live_partner_center_reverified",n["missing_for_draft"])

    def test_identity_receipt_rejects_different_store_id_or_write(self):
        p=sample()
        base={
            "schema_version":"existing-store-identity-reverify-receipt/1",
            "status":"EXISTING_IDENTITY_EXACT_MATCH","partner_center_reverified":True,
            "source_sha":"a"*40,"package_sha256":"b"*64,
            "store_id":"OTHER","identity_name":"OkinawaDesktopTools.FolderAutomationEngine",
            "publisher":"CN=TEST","package_family_name":"","package_sid":"",
            "created_or_reserved_product":False,"submission_started":False,
            "package_uploaded":False,"pricing_changed":False,"submitted":False,"published":False,
        }
        with self.assertRaises(StoreHandoffError):
            apply_identity_reverify_receipt(p,base)
        base["store_id"]="9PTEST"; base["package_uploaded"]=True
        with self.assertRaises(StoreHandoffError):
            apply_identity_reverify_receipt(p,base)

    def test_initial_submission_can_be_version_ready_without_accepted_history(self):
        p=sample()
        p["product"]["submission_kind"]="new"
        p["identity"]["accepted_version_history_verified"]=False
        p["identity"]["version_history_state"]="NO_ACCEPTED_PACKAGE_OBSERVED"
        p["identity"]["version_conflict"]=False
        n=normalize_store_product_handoff(p)
        self.assertTrue(n["identity"]["version_history_ready"])
        self.assertNotIn("identity.version_history_ready",n["missing_for_draft"])

    def test_update_still_requires_verified_accepted_history(self):
        p=sample()
        p["product"]["submission_kind"]="update"
        p["identity"]["accepted_version_history_verified"]=False
        p["identity"]["version_history_state"]="NO_ACCEPTED_PACKAGE_OBSERVED"
        p["identity"]["version_conflict"]=False
        n=normalize_store_product_handoff(p)
        self.assertFalse(n["identity"]["version_history_ready"])
        self.assertIn("identity.version_history_ready",n["missing_for_draft"])

    def test_free_product_cannot_have_trial(self):
        p=sample();p["commercial"]["model"]="free"
        with self.assertRaises(StoreHandoffError): normalize_store_product_handoff(p)

if __name__=="__main__": unittest.main()
