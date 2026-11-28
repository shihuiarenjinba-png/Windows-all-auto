"""Command-line entry point for offline checks and explicitly scoped Store actions."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from .core import export_results, preflight
from uploader.core import UploadError
from .store_workflow import (
    StoreWorkflowError,
    _load_job,
    acquire_registered_package,
    build_store_workflow_report,
    write_unique_report,
)


def _store_run_exit_code(report: dict, execution: dict, acquisition: dict) -> int:
    """Return 0 only for a reconciled successful run, 1 for a safe hold, 2 for errors/unknowns."""
    status = str(execution.get("status", "UNKNOWN"))
    writes = execution.get("writes_performed") is True
    if status in {"FAILED", "RECONCILE_REQUIRED", "PARTIAL_RECONCILE_REQUIRED", "UNKNOWN"}:
        return 2
    if (status == "EXECUTED" and not writes and
            execution.get("all_approved_sections_completed") is not True):
        return 2
    if writes and status != "EXECUTED":
        return 2
    if status in {"HOLD", "PLAN_ONLY", "NO_APPROVED_ACTIONS"}:
        return 1
    if acquisition.get("status") == "PACKAGE_ACQUISITION_HOLD":
        return 1
    if report.get("missing_or_unverified"):
        return 1
    return 0 if status == "EXECUTED" and (
        writes or execution.get("all_approved_sections_completed") is True) else 1


def _store_overall_status(report: dict, execution: dict) -> str:
    """Do not promote a section run to whole-draft completion without all evidence."""
    execution_status = str(execution.get("status", "UNKNOWN"))
    if execution_status in {"FAILED", "RECONCILE_REQUIRED", "PARTIAL_RECONCILE_REQUIRED", "UNKNOWN"}:
        return execution_status
    if execution_status != "EXECUTED":
        return execution_status if report.get("missing_or_unverified") == [] else "INPUTS_REQUIRED"
    if report.get("missing_or_unverified"):
        return "INPUTS_REQUIRED"
    return "APPROVED_SECTIONS_RECONCILED" if execution.get("all_approved_sections_completed") is True else "PARTIAL"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="windows-all-auto")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight", help="Offline evidence check; never uploads")
    check.add_argument("--manifest", required=True, type=Path)
    check.add_argument("--out", required=True, type=Path)
    commands.add_parser("gui", help="Windows GUI for offline checks")
    store = commands.add_parser("store", help="Product-driven Store workflow (offline by default)")
    store_commands = store.add_subparsers(dest="store_command", required=True)
    store_status = store_commands.add_parser("status", help="Read-only local, ledger, and Partner Center state")
    store_status.add_argument("--product", required=True, help="Registered product key under uploader/config")
    store_status.add_argument("--cdp-url", help="Optional loopback CDP endpoint; defaults to PARTNER_CENTER_CDP_URL")
    store_status.add_argument("--out", type=Path, help="Status report directory; unique reports are never overwritten")
    store_archive = store_commands.add_parser("archive", help="Verify and retain the exact registered MSIX in a local SHA-addressed archive")
    store_archive.add_argument("--product", required=True)
    store_archive.add_argument("--package", type=Path, help="Optional exact local package; otherwise resolved from configured sources")
    store_archive.add_argument("--archive-root", type=Path, help="Durable archive root; defaults under portfolio-audit/_runtime")
    store_archive.add_argument("--backup-root", type=Path, help="Optional external destination; requires exact Product/Draft-bound approval in the product profile")
    store_run = store_commands.add_parser("run", help="Collect evidence and execute only persisted owner-approved scopes")
    store_run.add_argument("--product", required=True, help="Registered product key under uploader/config")
    store_run.add_argument("--mode", choices=("AUTO", "READ_ONLY", "DRY_RUN"), default="AUTO",
                           help="AUTO applies only persisted owner-approved scopes; otherwise it plans without writes")
    store_run.add_argument("--source-root", type=Path, help="Optional exact local source checkout for read-only inspection")
    store_run.add_argument("--package", type=Path, help="Optional exact local MSIX; used only when its upload scope is owner-approved")
    store_run.add_argument("--cache-root", type=Path, help="Package cache; defaults to STORE_PACKAGE_CACHE_ROOT or .store-artifacts")
    store_run.add_argument("--out", type=Path, help="Report output directory; unique report files are never overwritten")
    store_apply = store_commands.add_parser("apply", help="Apply one explicitly approved section through the authenticated browser")
    store_apply.add_argument("--product", required=True)
    store_apply.add_argument("--section", required=True, choices=("properties", "store_listings", "pricing_availability", "age_ratings", "submission_options", "packages"))
    store_apply.add_argument("--values", type=Path, help="JSON array of exact labeled field values; required except for delegated Packages")
    store_apply.add_argument("--approval", type=Path, help="Section-scoped approval JSON; required except for the fixed existing package-only grant")
    store_apply.add_argument("--ui-map", type=Path, help="Versioned route map; defaults to the registered msix_pwa_app map")
    store_apply.add_argument("--package", type=Path, help="Exact MSIX for the delegated existing uploader route")
    store_apply.add_argument("--execute", action="store_true", help="Perform the approved live section write")
    store_qa = store_commands.add_parser("qa", help="Verify the registered package and emit product-specific runtime QA plan")
    store_qa.add_argument("--product", required=True, help="Registered product key under uploader/config")
    store_qa.add_argument("--package", type=Path, help="Optional exact local MSIX; otherwise resolve from registered archive/cache sources")
    store_qa.add_argument("--out", type=Path, help="Output root for a unique, append-only QA plan")
    opts = parser.parse_args(argv)
    if opts.command == "gui":
        from .gui import start
        start()
        return 0
    if opts.command == "store":
        if opts.store_command == "qa":
            try:
                config_root = Path(__file__).resolve().parent.parent / "uploader" / "config"
                config, _ = _load_job(opts.product, config_root)
                package = opts.package
                acquisition = {"status": "EXPLICIT_LOCAL_PACKAGE" if package else "NOT_RESOLVED"}
                if package is None:
                    repo_root = Path(__file__).resolve().parent.parent
                    cache_root = Path(os.environ.get("STORE_PACKAGE_CACHE_ROOT", ".store-artifacts"))
                    acquisition = acquire_registered_package(
                        config, product=opts.product, cache_root=cache_root,
                        search_roots=[Path.home() / "Desktop" / "portfolio-audit" / "_runtime" / "store-fleet-sync",
                                      Path.home() / "Desktop" / "Windows-all-auto-dca-upload" / ".uploader-run" / opts.product,
                                      repo_root / "_runtime" / "store-fleet-sync"],
                        archive_root=(Path.home() / "Desktop" / "portfolio-audit" / "_runtime" /
                                      "store-fleet-sync" / "durable-package-archive"))
                    package = Path(acquisition.get("local_path") or acquisition.get("path"))
                from .runtime_qa import build_runtime_qa_report
                qa = build_runtime_qa_report(
                    product=opts.product, config_root=config_root,
                    profile_root=config_root / "runtime_qa_profiles", package=package)
                qa["run_id"] = uuid4().hex
                qa["package_acquisition"] = acquisition
                out = opts.out or Path(".store-workflow-runs") / opts.product / "runtime-qa"
                report_path = write_unique_report(qa, out)
            except (OSError, StoreWorkflowError, ValueError, UploadError) as exc:
                print(f"STORE QA HOLD: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            print(json.dumps({"status": qa["status"], "product": opts.product,
                              "package_status": qa["package"].get("status"),
                              "qa_pass": qa["qa_pass"], "report": str(report_path),
                              "store_write_performed": False}, ensure_ascii=False, sort_keys=True))
            # The command verifies package inputs and writes a QA plan only;
            # runtime scenarios are still NOT_RUN, so it must not exit as a QA pass.
            return 1
        if opts.store_command == "archive":
            try:
                config, _ = _load_job(opts.product, Path(__file__).resolve().parent.parent / "uploader" / "config")
                package = opts.package
                if package is None:
                    cache_root = Path(os.environ.get("STORE_PACKAGE_CACHE_ROOT", ".store-artifacts"))
                    repo_root = Path(__file__).resolve().parent.parent
                    acquisition = acquire_registered_package(
                        config, product=opts.product, cache_root=cache_root,
                        search_roots=[Path.home() / "Desktop" / "portfolio-audit" / "_runtime" / "store-fleet-sync",
                                      Path.home() / "Desktop" / "Windows-all-auto-dca-upload" / ".uploader-run" / opts.product,
                                      repo_root / "_runtime" / "store-fleet-sync"])
                    package = Path(acquisition.get("local_path") or acquisition.get("path"))
                from .artifact_archive import archive_verified_package
                archive_root = opts.archive_root or (Path.home() / "Desktop" / "portfolio-audit" / "_runtime" / "store-fleet-sync" / "durable-package-archive")
                result = archive_verified_package(config, package, archive_root)
                if opts.backup_root is not None:
                    from .artifact_archive import ArtifactArchiveError, copy_to_approved_external_backup
                    try:
                        result["external_backup"] = copy_to_approved_external_backup(
                            config, Path(result["path"]), Path(result["receipt"]), opts.backup_root)
                    except ArtifactArchiveError as exc:
                        result["external_backup"] = {"status": "HOLD_NO_TRANSFER",
                                                     "reason": str(exc), "destination_written": False}
                report = {"schema_version": "all-auto-store-archive/1", "product_key": opts.product,
                          "created_at_utc": datetime.now(timezone.utc).isoformat(),
                          "run_id": uuid4().hex, **result}
                report_path = write_unique_report(report, Path(".store-workflow-runs") / opts.product)
            except (OSError, StoreWorkflowError, ValueError) as exc:
                print(f"STORE ARCHIVE HOLD: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            print(json.dumps({**result, "product": opts.product, "report": str(report_path)},
                             ensure_ascii=False, sort_keys=True))
            return 1 if result.get("external_backup", {}).get("status") == "HOLD_NO_TRANSFER" else 0
        if opts.store_command == "status":
            from .store_status import collect_store_status
            try:
                report = collect_store_status(
                    product=opts.product,
                    config_root=Path(__file__).resolve().parent.parent / "uploader" / "config",
                    repo_root=Path(__file__).resolve().parent.parent,
                    cdp_endpoint=opts.cdp_url,
                )
                report_path = write_unique_report(
                    report, opts.out or Path(".store-workflow-runs") / opts.product)
            except (OSError, StoreWorkflowError, ValueError) as exc:
                print(f"STORE STATUS HOLD: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 2
            print(json.dumps({"status": report["partner_center"].get("status"),
                              "product": opts.product,
                              "local_package": report["local_package"].get("status"),
                              "package_reconciliation": report["package_reconciliation"],
                              "receipts": report["upload_history"].get("durable_receipt_count"),
                              "report": str(report_path), "writes_performed": False},
                             ensure_ascii=False, sort_keys=True))
            return 0 if report["partner_center"].get("status") == "READ_ONLY_OBSERVED" else 1
        if opts.store_command == "apply":
            live_write_succeeded = False
            try:
                config, profile_path = _load_job(opts.product, Path(__file__).resolve().parent.parent / "uploader" / "config")
                if not opts.execute:
                    raise StoreWorkflowError("store apply requires --execute; no live action was taken")
                if opts.section == "packages":
                    if opts.package is None:
                        raise StoreWorkflowError("Packages requires --package with the exact configured MSIX")
                    if config.get("upload_scope") != "ONE_EXACT_MSIX_TO_EXISTING_DRAFT_PACKAGES_ONLY" or config.get("upload_approved") is not True:
                        raise StoreWorkflowError("the product profile does not authorize an existing-Draft package-only write")
                    if config.get("certification_submission_authorized") is not False or config.get("publish_authorized") is not False:
                        raise StoreWorkflowError("Certification and Publish must remain explicitly unauthorized")
                    from uploader.run import main as uploader_main
                    original_argv = sys.argv[:]
                    try:
                        sys.argv = ["uploader.run", "--product", opts.product, "--package", str(opts.package),
                                    "--workdir", str(Path(".uploader-run") / opts.product), "--execute"]
                        return uploader_main()
                    finally:
                        sys.argv = original_argv
                if not opts.values or not opts.approval:
                    raise StoreWorkflowError("non-Package sections require both --values and --approval JSON")
                approval = json.loads(opts.approval.read_text(encoding="utf-8"))
                fields = json.loads(opts.values.read_text(encoding="utf-8"))
                if not isinstance(fields, list):
                    raise StoreWorkflowError("--values must contain a JSON array")
                route = str(config.get("submission_route", "msix_pwa_app"))
                map_path = opts.ui_map or (Path(__file__).resolve().parent.parent / "uploader" / "config" / "store_ui_maps" / f"{route}.v1.json")
                ui_map = json.loads(map_path.read_text(encoding="utf-8"))
                from uploader.store_form_engine import StoreUiHold, apply_live_section
                result = apply_live_section(config=config, section=opts.section, fields=fields,
                                            approval=approval, ui_map=ui_map,
                                            cdp_endpoint=os.environ.get("PARTNER_CENTER_CDP_URL"))
                live_write_succeeded = result.get("writes_performed") is True
                report = {"schema_version": "all-auto-store-apply/1", "product_key": opts.product,
                          "created_at_utc": datetime.now(timezone.utc).isoformat(),
                          "run_id": uuid4().hex, **result}
                report_path = write_unique_report(report, Path(".store-workflow-runs") / opts.product)
                print(json.dumps({"status": result["status"], "report": str(report_path),
                                  "product": opts.product, "section": opts.section}, ensure_ascii=False, sort_keys=True))
                return 0
            except (OSError, ValueError, StoreWorkflowError, UploadError) as exc:
                # If the form action completed but writing its local receipt
                # failed, the Store state is still potentially changed. Never
                # mislabel that as a preflight HOLD or allow a blind retry.
                write_started = (getattr(exc, "write_started", False) is True
                                 or live_write_succeeded)
                status = "RECONCILE_REQUIRED" if write_started else "HOLD"
                failure = {"schema_version": "all-auto-store-apply/1", "product_key": opts.product,
                           "created_at_utc": datetime.now(timezone.utc).isoformat(),
                           "run_id": uuid4().hex, "status": status, "section": opts.section,
                           "error_type": type(exc).__name__, "error": str(exc)[:1000],
                           "partner_center_write_state": "UNKNOWN" if write_started else "NOT_ATTEMPTED",
                           "writes_performed": write_started,
                           "retry_allowed": not write_started,
                           "certification_executed": False, "publish_executed": False}
                try:
                    report_path = write_unique_report(failure, Path(".store-workflow-runs") / opts.product)
                    print(json.dumps({"status": status, "report": str(report_path),
                                      "product": opts.product, "section": opts.section},
                                     ensure_ascii=False, sort_keys=True), file=sys.stderr)
                except OSError:
                    print(f"STORE APPLY {status}: {exc}", file=sys.stderr)
                return 2
        try:
            config, _ = _load_job(opts.product, Path(__file__).resolve().parent.parent / "uploader" / "config")
            package = opts.package
            if package is not None:
                acquisition = {"status": "EXPLICIT_LOCAL_PACKAGE", "source": "cli_package_argument"}
            elif opts.mode == "READ_ONLY":
                acquisition = {"status": "NOT_ACQUIRED_READ_ONLY", "source": "read_only_mode"}
            else:
                cache_root = opts.cache_root or Path(os.environ.get("STORE_PACKAGE_CACHE_ROOT", ".store-artifacts"))
                try:
                    repo_root = Path(__file__).resolve().parent.parent
                    archive_root = (Path.home() / "Desktop" / "portfolio-audit" / "_runtime" /
                                    "store-fleet-sync" / "durable-package-archive")
                    search_roots = [
                        Path.home() / "Desktop" / "portfolio-audit" / "_runtime" / "store-fleet-sync",
                        Path.home() / "Desktop" / "Windows-all-auto-dca-upload" / ".uploader-run" / opts.product,
                        repo_root / "_runtime" / "store-fleet-sync",
                    ]
                    acquisition = acquire_registered_package(
                        config, product=opts.product, cache_root=cache_root,
                        search_roots=search_roots, archive_root=archive_root)
                    package = Path(acquisition.get("local_path") or acquisition.get("path"))
                except StoreWorkflowError as exc:
                    acquisition = {"status": "PACKAGE_ACQUISITION_HOLD", "error": str(exc)}
            report = build_store_workflow_report(
                product=opts.product,
                config_root=Path(__file__).resolve().parent.parent / "uploader" / "config",
                mode=opts.mode,
                source_root=opts.source_root,
                package=package,
            )
            report["package_acquisition"] = acquisition
            try:
                from .runtime_qa import build_runtime_qa_report
                report["runtime_qa"] = build_runtime_qa_report(
                    product=opts.product,
                    config_root=Path(__file__).resolve().parent.parent / "uploader" / "config",
                    profile_root=Path(__file__).resolve().parent.parent / "uploader" / "config" / "runtime_qa_profiles",
                    package=package)
            except (OSError, StoreWorkflowError, ValueError, UploadError) as exc:
                report["runtime_qa"] = {"status": "RUNTIME_QA_PROFILE_HOLD",
                                        "qa_pass": False, "error": str(exc)[:500]}
            if acquisition["status"] == "PACKAGE_ACQUISITION_HOLD":
                report["package"]["status"] = "PACKAGE_ACQUISITION_HOLD"
                report["package"]["acquisition_error"] = acquisition["error"]
            if package is not None and package.is_file():
                try:
                    from .windows_msix_qa import diagnose_msix_runtime
                    report["windows_msix_diagnostic"] = diagnose_msix_runtime(
                        config=config,
                        package=package)
                except (OSError, ValueError, UploadError) as exc:
                    report["windows_msix_diagnostic"] = {
                        "assessment": "STATIC_DIAGNOSTIC_HOLD",
                        "error_type": type(exc).__name__, "launch_attempted": False,
                        "install_attempted": False,
                    }
            # The orchestrator may only execute scopes explicitly persisted in
            # the exact product profile. DCA remains PLAN_ONLY until its owner
            # approvals, exact-package runtime QA, and remaining section inputs
            # are all recorded. This keeps the single product-key command
            # reusable without widening today's live authorization.
            if opts.mode == "AUTO":
                from .store_run import run_approved_sections
                execution = run_approved_sections(
                    product=opts.product,
                    config_root=Path(__file__).resolve().parent.parent / "uploader" / "config",
                    package=package,
                    ui_map_path=(Path(__file__).resolve().parent.parent / "uploader" / "config" /
                                 "store_ui_maps" / f"{config.get('submission_route', 'msix_pwa_app')}.v1.json"),
                    cdp_endpoint=os.environ.get("PARTNER_CENTER_CDP_URL"),
                )
            else:
                from .store_run import ALLOWED_SECTIONS
                unapproved_sections = sorted(ALLOWED_SECTIONS)
                execution = {"status": "PLAN_ONLY", "reason": "EXECUTE_APPROVED_FLAG_REQUIRED",
                             "approved_sections": [], "completed_sections": [],
                             "pending_sections": unapproved_sections,
                             "unapproved_sections": unapproved_sections,
                             "not_executed_sections": unapproved_sections,
                             "all_approved_sections_completed": False,
                             "actions": [], "writes_performed": False,
                             "certification_executed": False, "publish_executed": False}
            report["execution"] = execution
            report["overall_status"] = _store_overall_status(report, execution)
            out = opts.out or Path(".store-workflow-runs") / opts.product
            report_path = write_unique_report(report, out)
            approval_report = {
                "schema_version": "all-auto-owner-decisions/1",
                "created_at_utc": report["created_at_utc"],
                "run_id": report["run_id"], "product_key": opts.product,
                "product_id": report["binding"]["product_id"],
                "submission_id": report["binding"]["submission_id"],
                "source_package_provenance": report.get("source_package_provenance", {}),
                "owner_decisions": report["owner_decisions"],
                "owner_decision_candidates": report.get("owner_decision_candidates", []),
                "shared_store_policy": report.get("shared_store_policy", {}),
                "owner_decision_batch": report.get("owner_decision_batch", []),
            }
            approval_report_path = write_unique_report(approval_report, out / "owner-decisions")
        except (OSError, StoreWorkflowError) as exc:
            print(f"STORE WORKFLOW HOLD: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"status": report["overall_status"],
                          "readiness_status": report["status"],
                          "execution_status": execution.get("status"),
                          "completed_sections": execution.get("completed_sections", []),
                          "pending_sections": execution.get("pending_sections", []),
                          "unapproved_sections": execution.get("unapproved_sections", []),
                          "not_executed_sections": execution.get("not_executed_sections", []),
                          "product": opts.product,
                          "mode": opts.mode, "report": str(report_path),
                          "owner_decisions_report": str(approval_report_path),
                          "missing_or_unverified": len(report["missing_or_unverified"]),
                          "partner_center_writes": execution.get("writes_performed") is True},
                         ensure_ascii=False, sort_keys=True))
        return _store_run_exit_code(report, execution, acquisition)
    try:
        content = json.loads(opts.manifest.read_text(encoding="utf-8"))
        result = preflight(content, opts.manifest.resolve().parent)
        export_results(result, opts.out)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"MANIFEST ERROR: {exc}", file=sys.stderr)
        return 3
    print(f"OFFLINE PREFLIGHT ONLY — products={result['total']} {result['counts']}")
    print(f"JSON/Markdown results: {opts.out}")
    return 2 if result["counts"]["BLOCKED"] else 1 if result["counts"]["HOLD"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
