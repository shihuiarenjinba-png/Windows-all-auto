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

    ready_checks={
        "identity.live_partner_center_reverified": identity.get("live_partner_center_reverified") is True,
        "identity.accepted_version_history_verified": identity.get("accepted_version_history_verified") is True,
        "commercial.price_confirmed": commercial.get("price_confirmed") is True,
        "commercial.approved_by": isinstance(commercial.get("approved_by"),str) and bool(commercial.get("approved_by").strip()),
        "commercial.price_value": model=="free" or isinstance(price_value,str) and bool(price_value.strip()),
        "commercial.trial_confirmed": trial=="none" or commercial.get("trial_confirmed") is True,
        "commercial.trial_approved_by": trial=="none" or isinstance(commercial.get("trial_approved_by"),str) and bool(commercial.get("trial_approved_by").strip()),
        "assets.owner_visual_approval": assets.get("owner_visual_approval") is True,
        "security.owner_confirmation_complete": security.get("owner_confirmation_complete") is True,
        "approvals.owner_approved_for_draft": approvals.get("owner_approved_for_draft") is True,
    }
    if audience=="PRIVATE_AUDIENCE_TEST":
        ready_checks["distribution.known_user_group"]=isinstance(distribution.get("known_user_group"),str) and bool(distribution.get("known_user_group").strip())
    missing=sorted(k for k,v in ready_checks.items() if not v)

    return {
        "schema_version":"store-product-handoff/2",
        "product":{**product,"source_sha":source_sha,"submission_route":route},
        "package":{**package,"package_type":package_type,"package_sha256":package_sha},
        "identity":{**identity_norm,"store_id":store_id,
                    "package_family_name":package_family_name,
                    "package_sid":package_sid,
                    "live_partner_center_reverified":identity.get("live_partner_center_reverified") is True,
                    "accepted_version_history_verified":identity.get("accepted_version_history_verified") is True},
        "commercial":{**commercial,"model":model,"currency":currency,"free_trial":trial},
        "distribution":distribution,
        "assets":assets,
        "security":security,
        "approvals":approvals,
        "missing_for_draft":missing,
        "ready_for_automator_draft":not missing,
    }

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
