"""Bilingual offline preflight GUI for the Store submission coordinator.

This is an operator-facing internal tool. It intentionally does not expose live
Partner Center submission controls until the Windows adapter and selectors are
verified on a real Windows machine.
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from .core import export_results, preflight

UI_CONTRACT = {
    "pages": ("products", "settings", "queue", "results"),
    "target_viewports": ((1024, 768), (1280, 720)),
    "default_geometry": "1000x680",
    "minimum_size": (860, 560),
    "live_partner_center_enabled": False,
}

STRINGS = {
    "ja": {
        "window_title": "Windows-all-auto — 申請前チェック",
        "products_tab": "製品とファイル",
        "settings_tab": "設定",
        "queue_tab": "実行キュー",
        "results_tab": "結果",
        "heading": "Microsoft Store 申請前チェック",
        "subtitle": "製品一覧JSONを選択し、Identity・SHA・セキュリティ確認・監査証拠をオフラインで検査します。",
        "offline_badge": "安全モード：Partner Centerへの書き込みは行いません",
        "manifest_label": "製品一覧JSON",
        "browse": "ファイルを選択",
        "run": "検査を実行",
        "ready_hint": "JSONを選択すると検査を開始できます。",
        "selected_hint": "準備完了。［検査を実行］を押してください。",
        "settings_heading": "表示と言語",
        "settings_note": "認証情報は保存しません。価格・Identity・セキュリティ回答を自動確定しません。",
        "queue_heading": "実行キュー",
        "queue_locked": "現在はロック中です。Windows実機で3ツール連携とPartner Center操作が検証されるまで有効化しません。",
        "queue_button": "本番キューを開始（未検証のため無効）",
        "queue_safe": "個別HOLD/ERRORは記録して次へ進みます。認証切れは全体停止、UNKNOWNは自動再送しません。",
        "summary_title": "検査結果",
        "output_label": "レポート保存先",
        "col_product": "製品",
        "col_type": "種類",
        "col_status": "状態",
        "col_findings": "要確認数",
        "details": "詳細",
        "error_title": "申請前チェック エラー",
        "no_selection": "製品一覧JSONを選択してください。",
        "total": "対象",
        "ready": "QA候補",
        "hold": "HOLD",
        "blocked": "BLOCKED",
        "raw_note": "詳細欄には選択した製品の検査理由を表示します。",
    },
    "en": {
        "window_title": "Windows-all-auto — Store preflight",
        "products_tab": "Products & files",
        "settings_tab": "Settings",
        "queue_tab": "Queue",
        "results_tab": "Results",
        "heading": "Microsoft Store preflight",
        "subtitle": "Select a product manifest and verify identity, hashes, security confirmation, and audit evidence offline.",
        "offline_badge": "Safe mode: no Partner Center writes are performed",
        "manifest_label": "Product manifest JSON",
        "browse": "Choose file",
        "run": "Run preflight",
        "ready_hint": "Select a JSON manifest to begin.",
        "selected_hint": "Ready. Choose Run preflight.",
        "settings_heading": "Display and language",
        "settings_note": "Credentials are not stored. Price, identity, and security declarations are never auto-confirmed.",
        "queue_heading": "Execution queue",
        "queue_locked": "Locked. It remains disabled until the three-tool Windows integration and Partner Center flow are verified on real hardware.",
        "queue_button": "Start live queue (disabled until verified)",
        "queue_safe": "Per-product HOLD/ERROR can continue. Authentication expiry stops the whole queue; UNKNOWN is never auto-retried.",
        "summary_title": "Preflight results",
        "output_label": "Report output",
        "col_product": "Product",
        "col_type": "Type",
        "col_status": "Status",
        "col_findings": "Findings",
        "details": "Details",
        "error_title": "Preflight error",
        "no_selection": "Select a product manifest JSON.",
        "total": "Total",
        "ready": "QA candidates",
        "hold": "HOLD",
        "blocked": "BLOCKED",
        "raw_note": "The details area shows findings for the selected product.",
    },
}


def localized_text(language: str, key: str) -> str:
    table = STRINGS.get(language)
    if table is None or key not in table:
        raise KeyError(f"Unknown UI text: {language}/{key}")
    return table[key]


def status_summary(report: dict[str, Any], language: str) -> str:
    counts = report["counts"]
    return (
        f"{localized_text(language, 'total')}: {report['total']}   "
        f"{localized_text(language, 'ready')}: {counts['READY_FOR_WINDOWS_QA']}   "
        f"{localized_text(language, 'hold')}: {counts['HOLD']}   "
        f"{localized_text(language, 'blocked')}: {counts['BLOCKED']}"
    )


def start() -> None:
    root = tk.Tk()
    root.geometry(UI_CONTRACT["default_geometry"])
    root.minsize(*UI_CONTRACT["minimum_size"])

    language = tk.StringVar(value="ja")
    manifest = tk.StringVar()
    output = tk.StringVar()
    hint = tk.StringVar()
    summary = tk.StringVar()
    last_rows: list[dict[str, Any]] = []

    outer = ttk.Frame(root, padding=(14, 12))
    outer.pack(fill="both", expand=True)
    tab = ttk.Notebook(outer)
    tab.pack(fill="both", expand=True)
    pages = {name: ttk.Frame(tab, padding=16) for name in UI_CONTRACT["pages"]}
    main = pages["products"]
    settings = pages["settings"]
    queue = pages["queue"]
    result_page = pages["results"]
    for page in pages.values():
        tab.add(page)

    heading = ttk.Label(main, font=("Segoe UI", 16, "bold"))
    heading.pack(anchor="w")
    subtitle = ttk.Label(main, wraplength=820)
    subtitle.pack(anchor="w", pady=(6, 12))

    safe_box = ttk.LabelFrame(main, padding=10)
    safe_box.pack(fill="x", pady=(0, 14))
    safe_label = ttk.Label(safe_box)
    safe_label.pack(anchor="w")

    file_box = ttk.LabelFrame(main, padding=12)
    file_box.pack(fill="x")
    manifest_label = ttk.Label(file_box)
    manifest_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
    entry = ttk.Entry(file_box, textvariable=manifest)
    entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
    file_box.columnconfigure(0, weight=1)

    def pick() -> None:
        value = filedialog.askopenfilename(filetypes=[("JSON manifest", "*.json")])
        if value:
            manifest.set(value)

    pick_button = ttk.Button(file_box, command=pick)
    pick_button.grid(row=1, column=1, sticky="e")
    hint_label = ttk.Label(main, textvariable=hint, wraplength=820)
    hint_label.pack(anchor="w", pady=(10, 2))
    run_button = ttk.Button(main, state="disabled")
    run_button.pack(anchor="w", pady=(10, 0))

    settings_heading = ttk.Label(settings, font=("Segoe UI", 14, "bold"))
    settings_heading.pack(anchor="w")
    settings_note = ttk.Label(settings, wraplength=820)
    settings_note.pack(anchor="w", pady=(8, 16))
    ttk.Radiobutton(settings, text="日本語", value="ja", variable=language).pack(anchor="w", pady=2)
    ttk.Radiobutton(settings, text="English", value="en", variable=language).pack(anchor="w", pady=2)
    viewport_note = ttk.Label(
        settings,
        text="QA target viewports: 1024×768 / 1280×720",
    )
    viewport_note.pack(anchor="w", pady=(18, 0))

    queue_heading = ttk.Label(queue, font=("Segoe UI", 14, "bold"))
    queue_heading.pack(anchor="w")
    queue_locked = ttk.Label(queue, wraplength=820)
    queue_locked.pack(anchor="w", pady=(8, 12))
    queue_button = ttk.Button(queue, state="disabled")
    queue_button.pack(anchor="w")
    queue_safe = ttk.Label(queue, wraplength=820)
    queue_safe.pack(anchor="w", pady=(12, 0))

    result_heading = ttk.Label(result_page, font=("Segoe UI", 14, "bold"))
    result_heading.pack(anchor="w")
    ttk.Label(result_page, textvariable=summary).pack(anchor="w", pady=(6, 8))

    tree_frame = ttk.Frame(result_page)
    tree_frame.pack(fill="both", expand=True)
    columns = ("product", "type", "status", "findings")
    results = ttk.Treeview(tree_frame, columns=columns, show="headings", height=9)
    results.grid(row=0, column=0, sticky="nsew")
    scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=results.yview)
    scrollbar.grid(row=0, column=1, sticky="ns")
    results.configure(yscrollcommand=scrollbar.set)
    tree_frame.rowconfigure(0, weight=1)
    tree_frame.columnconfigure(0, weight=1)
    results.column("product", width=220, anchor="w")
    results.column("type", width=80, anchor="center")
    results.column("status", width=190, anchor="center")
    results.column("findings", width=90, anchor="center")

    output_caption = ttk.Label(result_page)
    output_caption.pack(anchor="w", pady=(10, 0))
    ttk.Label(result_page, textvariable=output, wraplength=820).pack(anchor="w")

    details_caption = ttk.Label(result_page)
    details_caption.pack(anchor="w", pady=(10, 4))
    details = tk.Text(result_page, height=6, wrap="word", state="disabled", font=("Segoe UI", 9))
    details.pack(fill="x")
    raw_note = ttk.Label(result_page, wraplength=820)
    raw_note.pack(anchor="w", pady=(4, 0))

    def show_details(*_: object) -> None:
        selection = results.selection()
        if not selection:
            return
        index = int(results.item(selection[0], "tags")[0])
        row = last_rows[index]
        findings = row.get("findings") or []
        body = "\n".join(f"• {item}" for item in findings) if findings else "✓ No blocking findings in offline preflight."
        body += "\n\n" + str(row.get("meaning") or "")
        details.config(state="normal")
        details.delete("1.0", "end")
        details.insert("end", body)
        details.config(state="disabled")

    results.bind("<<TreeviewSelect>>", show_details)

    def render_results(report: dict[str, Any]) -> None:
        nonlocal last_rows
        last_rows = list(report["products"])
        for item in results.get_children():
            results.delete(item)
        for index, row in enumerate(last_rows):
            results.insert(
                "",
                "end",
                values=(
                    row.get("id", ""),
                    row.get("type", ""),
                    row.get("status", ""),
                    len(row.get("findings") or []),
                ),
                tags=(str(index),),
            )
        summary.set(status_summary(report, language.get()))
        children = results.get_children()
        if children:
            results.selection_set(children[0])
            results.focus(children[0])
            show_details()

    def run_check() -> None:
        raw = manifest.get().strip()
        if not raw:
            messagebox.showwarning(localized_text(language.get(), "error_title"),
                                   localized_text(language.get(), "no_selection"))
            return
        try:
            path = Path(raw)
            data = json.loads(path.read_text(encoding="utf-8"))
            report = preflight(data, path.resolve().parent)
            target = path.resolve().parent / "all-auto-results"
            export_results(report, target)
            output.set(str(target))
            render_results(report)
            tab.select(result_page)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            messagebox.showerror(localized_text(language.get(), "error_title"), str(exc))

    run_button.config(command=run_check)

    def update_manifest_state(*_: object) -> None:
        selected = bool(manifest.get().strip())
        run_button.config(state="normal" if selected else "disabled")
        hint.set(localized_text(language.get(), "selected_hint" if selected else "ready_hint"))

    manifest.trace_add("write", update_manifest_state)

    def render(*_: object) -> None:
        lang = language.get()
        root.title(localized_text(lang, "window_title"))
        tab.tab(main, text=localized_text(lang, "products_tab"))
        tab.tab(settings, text=localized_text(lang, "settings_tab"))
        tab.tab(queue, text=localized_text(lang, "queue_tab"))
        tab.tab(result_page, text=localized_text(lang, "results_tab"))
        heading.config(text=localized_text(lang, "heading"))
        subtitle.config(text=localized_text(lang, "subtitle"))
        safe_box.config(text=localized_text(lang, "offline_badge"))
        safe_label.config(text=localized_text(lang, "offline_badge"))
        manifest_label.config(text=localized_text(lang, "manifest_label"))
        pick_button.config(text=localized_text(lang, "browse"))
        run_button.config(text=localized_text(lang, "run"))
        settings_heading.config(text=localized_text(lang, "settings_heading"))
        settings_note.config(text=localized_text(lang, "settings_note"))
        queue_heading.config(text=localized_text(lang, "queue_heading"))
        queue_locked.config(text=localized_text(lang, "queue_locked"))
        queue_button.config(text=localized_text(lang, "queue_button"))
        queue_safe.config(text=localized_text(lang, "queue_safe"))
        result_heading.config(text=localized_text(lang, "summary_title"))
        output_caption.config(text=localized_text(lang, "output_label"))
        details_caption.config(text=localized_text(lang, "details"))
        raw_note.config(text=localized_text(lang, "raw_note"))
        results.heading("product", text=localized_text(lang, "col_product"))
        results.heading("type", text=localized_text(lang, "col_type"))
        results.heading("status", text=localized_text(lang, "col_status"))
        results.heading("findings", text=localized_text(lang, "col_findings"))
        if last_rows:
            summary.set(status_summary({"total": len(last_rows), "counts": {
                "READY_FOR_WINDOWS_QA": sum(r.get("status") == "READY_FOR_WINDOWS_QA" for r in last_rows),
                "HOLD": sum(r.get("status") == "HOLD" for r in last_rows),
                "BLOCKED": sum(r.get("status") == "BLOCKED" for r in last_rows),
            }}, lang))
        update_manifest_state()

    language.trace_add("write", render)
    render()
    root.mainloop()
