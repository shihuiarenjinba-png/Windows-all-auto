"""Strict Store-product handoff used after MSIX/QA and before Windows-Automator.

This module is pure validation/translation. It never opens Partner Center,
uploads a package, changes pricing, submits certification, or publishes.
"""
from __future__ import annotations
from pathlib import Path
import copy
from typing import Any
import re

HEX40=re.compile(r"^[0-9a-fA-F]{40}$")
HEX64=re.compile(r"^[0-9a-fA-F]{64}$")
ROUTES={"msix_pwa_app":("app",{"msix","msixupload","msixbundle","appx","appxupload","appxbundle"}),
        "msix_pwa_game":("game",{"msix","msixupload","msixbundle","appx","appxupload","appxbundle"})}
TRIALS={"none","1_day","7_days","15_days","30_days","unlimited"}
AUDIENCES={"PRIVATE_AUDIENCE_TEST","PUBLIC_RELEASE"}
VERSION_HISTORY_STATES={"VERIFIED_ACCEPTED_HISTORY","NO_ACCEPTED_PACKAGE_OBSERVED","UNKNOWN"}
UNSIGNED_GUI_STATES={"NOT_ATTEMPTED","PASS","APPLICATION_CONTROL_BLOCKED","OTHER_HOLD"}

class StoreHandoffError(ValueError): pass

def _obj(v,label):
    if not isinstance(v,dict): raise StoreHandoffError(f"{label} must be object")
    return v

def _text(v,label):
    if not isinstance(v,str) or not v.strip(): raise StoreHandoffError(f"{label} must be non-empty string")
    return v.strip()

def normalize_store_product_handoff(payload:Any)->dict[str,Any]:
    root=_obj(payload,"handoff")
    if root.get("schema_version")!="store-product-handoff/2":
        raise StoreHandoffError("unsupported schema_version")
    product=_obj(root.get("product"),"product")
    package=_obj(root.get("package"),"package")
    identity=_obj(root.get("identity"),"identity")
    commercial=_obj(root.get("commercial"),"commercial")
    distribution=_obj(root.get("distribution"),"distribution")
    assets=_obj(root.get("assets"),"assets")
    security=_obj(root.get("security"),"security")
    approvals=_obj(root.get("approvals"),"approvals")
    qa_present="qa" in root
    qa=_obj(root.get("qa"),"qa") if qa_present else {}
    release_holds=root.get("release_holds") or []
    if not isinstance(release_holds,list) or not all(isinstance(x,str) and x.strip() for x in release_holds):
        raise StoreHandoffError("release_holds must be a list of non-empty strings")

    product_type=_text(product.get("type"),"product.type")
    route=_text(product.get("submission_route"),"product.submission_route")
    if route not in ROUTES or ROUTES[route][0]!=product_type:
        raise StoreHandoffError("submission_route/product type mismatch")
    source_sha=_text(product.get("source_sha"),"product.source_sha").lower()
    if not HEX40.fullmatch(source_sha): raise StoreHandoffError("invalid source_sha")
    package_type=_text(package.get("package_type"),"package.package_type").lower().lstrip(".")
    if package_type not in ROUTES[route][1]:
        raise StoreHandoffError("submission_route/package type mismatch")
    package_sha=_text(package.get("package_sha256"),"package.package_sha256").lower()
    if not HEX64.fullmatch(package_sha): raise StoreHandoffError("invalid package_sha256")
    file_name=_text(package.get("file_name"),"package.file_name")
    if Path(file_name).suffix.lower().lstrip(".")!=package_type:
        raise StoreHandoffError("package filename/type mismatch")

    identity_norm={k:_text(identity.get(k),f"identity.{k}") for k in ("name","publisher","version","architecture")}
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+",identity_norm["version"]):
        raise StoreHandoffError("identity.version must be four-part")
    store_id=_text(identity.get("store_id"),"identity.store_id")
    package_family_name=str(identity.get("package_family_name") or "").strip()
    package_sid=str(identity.get("package_sid") or "").strip()
    submission_kind=_text(product.get("submission_kind"),"product.submission_kind")
    if submission_kind not in {"new","update"}:
        raise StoreHandoffError("unsupported product.submission_kind")
    version_history_state=str(identity.get("version_history_state") or "UNKNOWN").strip()
    if version_history_state not in VERSION_HISTORY_STATES:
        raise StoreHandoffError("unsupported identity.version_history_state")
    version_conflict=identity.get("version_conflict")
    if version_conflict not in {True,False,None}:
        raise StoreHandoffError("identity.version_conflict must be true, false, or null")
    if submission_kind=="new":
        version_history_ready=(
            version_history_state=="NO_ACCEPTED_PACKAGE_OBSERVED"
            and version_conflict is False
        )
    else:
        version_history_ready=(
            version_history_state=="VERIFIED_ACCEPTED_HISTORY"
            and identity.get("accepted_version_history_verified") is True
            and version_conflict is False
        )

    model=_text(commercial.get("model"),"commercial.model")
    if model not in {"free","paid_one_time"}: raise StoreHandoffError("unsupported commercial.model")
    currency=_text(commercial.get("currency"),"commercial.currency")
    if currency not in {"JPY","USD"}: raise StoreHandoffError("unsupported commercial.currency")
    trial=_text(commercial.get("free_trial"),"commercial.free_trial")
    if trial not in TRIALS: raise StoreHandoffError("unsupported free_trial")
    if model=="free" and trial!="none": raise StoreHandoffError("free product cannot have paid-product trial")
    price_value=commercial.get("exact_partner_center_price_value")
    if price_value is not None and (not isinstance(price_value,str) or not price_value.strip()):
        raise StoreHandoffError("commercial price value must be null or non-empty string")
    if commercial.get("publishing_hold")!="manual_publish":
        raise StoreHandoffError("publishing_hold must remain manual_publish")

    audience=_text(distribution.get("audience"),"distribution.audience")
    if audience not in AUDIENCES: raise StoreHandoffError("unsupported distribution audience")
    if audience=="PRIVATE_AUDIENCE_TEST" and distribution.get("public_release_approved") is not False:
        raise StoreHandoffError("private audience must not carry public release approval")

    if security.get("package_sha256")!=package_sha:
        raise StoreHandoffError("security confirmation is not bound to package SHA")

    if qa_present:
        for key in ("github_exact_head_ci_pass","local_final_pass","store_signed_install_pass"):
            if qa.get(key) not in {True,False}:
                raise StoreHandoffError(f"qa.{key} must be boolean")
        if "pre_store_static_pass" in qa and qa.get("pre_store_static_pass") not in {True,False}:
            raise StoreHandoffError("qa.pre_store_static_pass must be boolean")
        unsigned_gui_execution_status=str(
            qa.get("unsigned_gui_execution_status")
            or ("PASS" if qa.get("local_final_pass") is True else "NOT_ATTEMPTED")
        ).strip()
        if unsigned_gui_execution_status not in UNSIGNED_GUI_STATES:
            raise StoreHandoffError("unsupported qa.unsigned_gui_execution_status")
        pre_store_static_pass=qa.get("pre_store_static_pass") is True
        local_final_pass=qa.get("local_final_pass") is True
        store_signed_install_pass=qa.get("store_signed_install_pass") is True
        private_store_signing_lane_ready=(
            local_final_pass
            or (
                pre_store_static_pass
                and unsigned_gui_execution_status=="APPLICATION_CONTROL_BLOCKED"
            )
        )
    else:
        unsigned_gui_execution_status="NOT_ATTEMPTED"
        pre_store_static_pass=False
        local_final_pass=False
        store_signed_install_pass=False
        private_store_signing_lane_ready=False

    ready_checks={
        "identity.live_partner_center_reverified": identity.get("live_partner_center_reverified") is True,
        "identity.version_history_ready": version_history_ready,
        "commercial.price_confirmed": commercial.get("price_confirmed") is True,
        "commercial.approved_by": isinstance(commercial.get("approved_by"),str) and bool(commercial.get("approved_by").strip()),
        "commercial.price_value": model=="free" or isinstance(price_value,str) and bool(price_value.strip()),
        "commercial.trial_confirmed": trial=="none" or commercial.get("trial_confirmed") is True,
        "commercial.trial_approved_by": trial=="none" or isinstance(commercial.get("trial_approved_by"),str) and bool(commercial.get("trial_approved_by").strip()),
        "assets.owner_visual_approval": assets.get("owner_visual_approval") is True,
        "security.owner_confirmation_complete": security.get("owner_confirmation_complete") is True,
        "approvals.owner_approved_for_draft": approvals.get("owner_approved_for_draft") is True,
    }
    if qa_present:
        ready_checks["qa.local_final_pass"]=(
            local_final_pass
            or store_signed_install_pass
            or (
                audience=="PRIVATE_AUDIENCE_TEST"
                and private_store_signing_lane_ready
            )
        )
        if audience=="PUBLIC_RELEASE":
            ready_checks["qa.store_signed_install_pass"]=store_signed_install_pass
    if audience=="PRIVATE_AUDIENCE_TEST":
        ready_checks["distribution.known_user_group"]=isinstance(distribution.get("known_user_group"),str) and bool(distribution.get("known_user_group").strip())
    missing=sorted(k for k,v in ready_checks.items() if not v)

    result={
        "schema_version":"store-product-handoff/2",
        "product":{**product,"source_sha":source_sha,"submission_route":route,"submission_kind":submission_kind},
        "package":{**package,"package_type":package_type,"package_sha256":package_sha},
        "identity":{**identity_norm,"store_id":store_id,
                    "package_family_name":package_family_name,
                    "package_sid":package_sid,
                    "live_partner_center_reverified":identity.get("live_partner_center_reverified") is True,
                    "accepted_version_history_verified":identity.get("accepted_version_history_verified") is True,
                    "version_history_state":version_history_state,
                    "version_conflict":version_conflict,
                    "version_history_ready":version_history_ready},
        "commercial":{**commercial,"model":model,"currency":currency,"free_trial":trial},
        "distribution":distribution,
        "assets":assets,
        "security":security,
        "approvals":approvals,
        "release_holds":list(release_holds),
        "notes":list(root.get("notes") or []),
        "missing_for_draft":missing,
        "ready_for_automator_draft":not missing,
    }
    if qa_present:
        result["qa"]={**qa,
                      "github_exact_head_ci_pass":qa.get("github_exact_head_ci_pass") is True,
                      "local_final_pass":local_final_pass,
                      "store_signed_install_pass":store_signed_install_pass,
                      "pre_store_static_pass":pre_store_static_pass,
                      "unsigned_gui_execution_status":unsigned_gui_execution_status,
                      "private_store_signing_lane_ready":private_store_signing_lane_ready}
    return result

def apply_local_final_qa_receipt(payload:Any, receipt:Any)->dict[str,Any]:
    """Bind exact-package local Windows QA to the Store handoff.

    The receipt cannot grant Partner Center, pricing, certification or publish
    approval. It only proves that the exact source/package candidate passed the
    required pre-upload local acceptance.
    """
    raw=_obj(payload,"handoff")
    current=normalize_store_product_handoff(raw)
    rec=_obj(receipt,"local QA receipt")
    if rec.get("schema_version")!="local-final-qa-receipt/1":
        raise StoreHandoffError("unsupported local QA receipt schema")
    if rec.get("status")!="PASS":
        raise StoreHandoffError("local QA receipt is not PASS")
    expected={
        "store_id":current["identity"]["store_id"],
        "source_sha":current["product"]["source_sha"],
        "package_sha256":current["package"]["package_sha256"],
    }
    for key,value in expected.items():
        actual=str(rec.get(key) or "")
        if key.endswith("sha") or key.endswith("sha256"):
            actual=actual.lower()
        if actual!=value:
            raise StoreHandoffError(f"local QA receipt mismatch: {key}")
    required_true=(
        "tests_passed","package_sha_verified","unpacked_exe_sha_verified",
        "jp_en_gui_passed","dpi_matrix_passed","product_specific_acceptance_passed",
        "normal_exit_passed",
    )
    for key in required_true:
        if rec.get(key) is not True:
            raise StoreHandoffError(f"local QA receipt missing PASS: {key}")
    for key in ("package_rebuilt","security_bypass_used"):
        if rec.get(key) is not False:
            raise StoreHandoffError(f"unsafe local QA receipt flag: {key}")

    updated=copy.deepcopy(raw)
    updated.setdefault("qa",{})
    updated["qa"]["github_exact_head_ci_pass"]=True
    updated["qa"]["local_final_pass"]=True
    updated["qa"].setdefault("store_signed_install_pass",False)
    updated["qa"]["local_final_qa_receipt_status"]="PASS"
    updated["qa"]["local_final_qa_product_specific_checks"]=list(rec.get("product_specific_checks") or [])
    return normalize_store_product_handoff(updated)

def apply_pre_store_static_qa_receipt(payload:Any, receipt:Any)->dict[str,Any]:
    """Bind a safe pre-Store static QA HOLD caused by Windows Application Control.

    This receipt does not claim GUI acceptance. It only permits the limited
    Private-audience Microsoft Store signing lane when exact package provenance
    passed and no security bypass was used.
    """
    raw=_obj(payload,"handoff")
    current=normalize_store_product_handoff(raw)
    rec=_obj(receipt,"pre-Store static QA receipt")
    if rec.get("schema_version")!="pre-store-static-qa-receipt/1":
        raise StoreHandoffError("unsupported pre-Store static QA receipt schema")
    if rec.get("status")!="APPLICATION_CONTROL_BLOCKED":
        raise StoreHandoffError("pre-Store static QA receipt must record Application Control block")
    expected={
        "store_id":current["identity"]["store_id"],
        "source_sha":current["product"]["source_sha"],
        "package_sha256":current["package"]["package_sha256"],
    }
    for key,value in expected.items():
        actual=str(rec.get(key) or "")
        if key.endswith("sha") or key.endswith("sha256"):
            actual=actual.lower()
        if actual!=value:
            raise StoreHandoffError(f"pre-Store static QA receipt mismatch: {key}")
    for key in (
        "tests_passed","package_sha_verified","unpacked_exe_sha_verified",
        "manifest_identity_verified","application_control_blocked",
    ):
        if rec.get(key) is not True:
            raise StoreHandoffError(f"pre-Store static QA receipt missing evidence: {key}")
    for key in (
        "package_rebuilt","security_bypass_used","security_policy_modified",
        "certificate_store_modified","alternate_bypass_used",
    ):
        if rec.get(key) is not False:
            raise StoreHandoffError(f"unsafe pre-Store static QA receipt flag: {key}")

    updated=copy.deepcopy(raw)
    updated.setdefault("qa",{})
    updated["qa"]["github_exact_head_ci_pass"]=True
    updated["qa"]["local_final_pass"]=False
    updated["qa"]["store_signed_install_pass"]=False
    updated["qa"]["pre_store_static_pass"]=True
    updated["qa"]["unsigned_gui_execution_status"]="APPLICATION_CONTROL_BLOCKED"
    updated["qa"]["pre_store_static_qa_receipt_status"]="APPLICATION_CONTROL_BLOCKED"
    return normalize_store_product_handoff(updated)


def apply_store_signed_install_qa_receipt(payload:Any, receipt:Any)->dict[str,Any]:
    """Bind final physical QA performed on the Microsoft Store-signed build."""
    raw=_obj(payload,"handoff")
    current=normalize_store_product_handoff(raw)
    rec=_obj(receipt,"Store-signed install QA receipt")
    if rec.get("schema_version")!="store-signed-install-qa-receipt/1":
        raise StoreHandoffError("unsupported Store-signed install QA receipt schema")
    if rec.get("status")!="PASS":
        raise StoreHandoffError("Store-signed install QA receipt is not PASS")
    expected={
        "store_id":current["identity"]["store_id"],
        "source_sha":current["product"]["source_sha"],
        "original_package_sha256":current["package"]["package_sha256"],
        "identity_name":current["identity"]["name"],
        "version":current["identity"]["version"],
        "architecture":current["identity"]["architecture"],
    }
    for key,value in expected.items():
        actual=str(rec.get(key) or "")
        if key.endswith("sha") or key.endswith("sha256"):
            actual=actual.lower()
        if actual!=value:
            raise StoreHandoffError(f"Store-signed install QA receipt mismatch: {key}")
    for key in (
        "microsoft_store_delivery_verified","signature_trust_verified",
        "jp_en_gui_passed","dpi_matrix_passed","product_specific_acceptance_passed",
        "normal_exit_passed",
    ):
        if rec.get(key) is not True:
            raise StoreHandoffError(f"Store-signed install QA receipt missing PASS: {key}")
    for key in ("package_rebuilt","security_bypass_used"):
        if rec.get(key) is not False:
            raise StoreHandoffError(f"unsafe Store-signed install QA receipt flag: {key}")

    updated=copy.deepcopy(raw)
    updated.setdefault("qa",{})
    updated["qa"].setdefault("github_exact_head_ci_pass",True)
    updated["qa"].setdefault("local_final_pass",False)
    updated["qa"]["store_signed_install_pass"]=True
    updated["qa"]["store_signed_install_qa_receipt_status"]="PASS"
    updated["qa"]["store_signed_product_specific_checks"]=list(rec.get("product_specific_checks") or [])
    return normalize_store_product_handoff(updated)


def apply_identity_reverify_receipt(payload:Any, receipt:Any)->dict[str,Any]:
    """Bind a local read-only Partner Center identity receipt to the Store handoff.

    Only the live identity re-verification flag is advanced. Version history,
    pricing, security, assets, draft approval, certification and publication
    remain independent gates.
    """
    raw=_obj(payload,"handoff")
    current=normalize_store_product_handoff(raw)
    rec=_obj(receipt,"identity receipt")
    if rec.get("schema_version")!="existing-store-identity-reverify-receipt/1":
        raise StoreHandoffError("unsupported identity receipt schema")
    if rec.get("status")!="EXISTING_IDENTITY_EXACT_MATCH" or rec.get("partner_center_reverified") is not True:
        raise StoreHandoffError("identity receipt is not an exact-match PASS")
    if str(rec.get("source_sha") or "").lower()!=current["product"]["source_sha"]:
        raise StoreHandoffError("identity receipt source_sha mismatch")
    if str(rec.get("package_sha256") or "").lower()!=current["package"]["package_sha256"]:
        raise StoreHandoffError("identity receipt package_sha256 mismatch")

    expected={
        "store_id":current["identity"]["store_id"],
        "identity_name":current["identity"]["name"],
        "publisher":current["identity"]["publisher"],
    }
    if current["identity"].get("package_family_name"):
        expected["package_family_name"]=current["identity"]["package_family_name"]
    if current["identity"].get("package_sid"):
        expected["package_sid"]=current["identity"]["package_sid"]
    for key,value in expected.items():
        if rec.get(key)!=value:
            raise StoreHandoffError(f"identity receipt mismatch: {key}")
    for flag in (
        "created_or_reserved_product","submission_started","package_uploaded",
        "pricing_changed","submitted","published",
    ):
        if rec.get(flag) is not False:
            raise StoreHandoffError(f"identity receipt must prove read-only behavior: {flag}")

    updated=copy.deepcopy(raw)
    updated.setdefault("identity",{})["live_partner_center_reverified"]=True
    updated["identity"]["live_reverify_receipt_status"]="EXISTING_IDENTITY_EXACT_MATCH"
    return normalize_store_product_handoff(updated)


def apply_initial_submission_receipt(payload:Any, receipt:Any)->dict[str,Any]:
    """Bind an owner-authorized initial Draft creation receipt to the handoff."""
    raw=_obj(payload,"handoff")
    current=normalize_store_product_handoff(raw)
    rec=_obj(receipt,"initial submission receipt")
    if rec.get("schema_version")!="existing-store-initial-submission-start-receipt/1":
        raise StoreHandoffError("unsupported initial submission receipt schema")
    if rec.get("status")!="INITIAL_SUBMISSION_DRAFT_CREATED":
        raise StoreHandoffError("initial submission receipt is not a PASS")
    if current["product"]["submission_kind"]!="new":
        raise StoreHandoffError("initial submission receipt requires submission_kind=new")
    if rec.get("store_id")!=current["identity"]["store_id"]:
        raise StoreHandoffError("initial submission receipt store_id mismatch")
    if str(rec.get("source_sha") or "").lower()!=current["product"]["source_sha"]:
        raise StoreHandoffError("initial submission receipt source_sha mismatch")
    if str(rec.get("package_sha256") or "").lower()!=current["package"]["package_sha256"]:
        raise StoreHandoffError("initial submission receipt package_sha256 mismatch")
    draft_id=str(rec.get("draft_id") or "").strip()
    if not draft_id.isdigit():
        raise StoreHandoffError("initial submission receipt draft_id is invalid")
    required={
        "created_or_reserved_product":False,
        "submission_started":True,
        "start_submission_clicked":True,
        "start_update_clicked":False,
        "package_uploaded":False,
        "pricing_changed":False,
        "submitted":False,
        "published":False,
    }
    for key,value in required.items():
        if rec.get(key) is not value:
            raise StoreHandoffError(f"initial submission receipt has unsafe or missing flag: {key}")
    updated=copy.deepcopy(raw)
    updated.setdefault("product",{})["draft_id"]=draft_id
    updated["product"]["initial_submission_started"]=True
    updated["product"]["initial_submission_receipt_status"]="INITIAL_SUBMISSION_DRAFT_CREATED"
    updated.setdefault("approvals",{})["initial_submission_start_completed"]=True
    return normalize_store_product_handoff(updated)


def to_windows_automator_input(normalized:dict[str,Any], *, package_path:str, images_dir:str)->dict[str,Any]:
    if normalized.get("schema_version")!="store-product-handoff/2":
        raise StoreHandoffError("normalize handoff before translation")
    p=normalized["product"]; pkg=normalized["package"]; ident=normalized["identity"]; c=normalized["commercial"]
    model="free" if c["model"]=="free" else "paid"
    return {
        "product_type":p["type"], "product_name":p["name"], "app_summary":p.get("summary",""),
        "repository":p["repository"], "package_path":package_path, "images_dir":images_dir,
        "store_product_id":ident["store_id"], "price_mode":model,
        "price_value":c.get("exact_partner_center_price_value") or "",
        "commercial_approval_required":True,
        "price_confirmed":c.get("price_confirmed") is True,
        "trial_confirmed":c.get("trial_confirmed") is True,
        "commercial_approved_by":str(c.get("approved_by") or c.get("trial_approved_by") or ""),
        "market_preset":p.get("market_preset",""),
        "submission_kind":p["submission_kind"], "submission_route":p["submission_route"],
        "draft_id":str(p.get("draft_id") or ""),
        "submission_route_source":"upstream", "package_type":pkg["package_type"],
        "package_sha256":pkg["package_sha256"], "source_sha":p["source_sha"],
        "identity_name":ident["name"], "identity_publisher":ident["publisher"],
        "package_version":ident["version"],
        "fields":{
            "free_trial":{"key":"free_trial","mode":"manual","value":c["free_trial"],
                          "source":"owner-approved commercial handoff","confidence":1.0,
                          "rationale":"explicit product commercial profile","confirmed":c.get("trial_confirmed") is True},
            "pricing_model":{"key":"pricing_model","mode":"manual","value":model,
                             "source":"owner-approved commercial handoff","confidence":1.0,
                             "rationale":"explicit product commercial profile","confirmed":c.get("price_confirmed") is True},
        },
        "certification_gate":"HOLD",
    }
