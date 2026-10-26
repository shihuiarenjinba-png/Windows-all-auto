"""Small Japanese/English offline preflight viewer.

NOT a Partner Center upload GUI. Any submission button would be deceptive.
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .core import preflight, export_results

STRINGS = {
    "ja": ("Windows-all-auto / 申請前チェック", "製品一覧JSONを選択", "オフライン検査", "対象", "合格候補", "要確認", "不合格", "現在のアプリはPartner Centerに書き込みません。"),
    "en": ("Windows-all-auto / Store preflight", "Select product manifest", "Offline preflight", "Total", "QA candidates", "HOLD", "BLOCKED", "This tool NEVER writes to Partner Center."),
}


def start() -> None:
    root = tk.Tk()
    root.title("Windows-all-auto — QA_ONLY")
    root.geometry("880x600")
    root.minsize(760, 480)
    language = tk.StringVar(value="ja")
    manifest = tk.StringVar()
    output = tk.StringVar()
    status = tk.StringVar()
    tab = ttk.Notebook(root)
    tab.pack(fill="both", expand=True, padx=16, pady=12)
    tabs = [ttk.Frame(tab, padding=16) for _ in range(4)]
    for page in tabs:
        tab.add(page)
    main, settings, queue, result_page = tabs
    heading = ttk.Label(main, font=("Segoe UI", 15, "bold"))
    heading.pack(anchor="w", pady=(0, 12))
    note = ttk.Label(main, wraplength=750)
    note.pack(anchor="w", pady=(0, 16))
    ttk.Entry(main, textvariable=manifest, width=80).pack(fill="x", pady=(0, 8))

    def pick() -> None:
        value = filedialog.askopenfilename(filetypes=[("JSON manifest", "*.json")])
        if value:
            manifest.set(value)

    pick_button = ttk.Button(main, command=pick)
    pick_button.pack(anchor="w")
    text_area = tk.Text(result_page, wrap="none", font=("Consolas", 10), state="disabled")
    text_area.pack(fill="both", expand=True)

    def run_check() -> None:
        try:
            path = Path(manifest.get())
            data = json.loads(path.read_text(encoding="utf-8"))
            report = preflight(data, path.resolve().parent)
            target = path.resolve().parent / "all-auto-results"
            export_results(report, target)
            output.set(str(target))
            counts = report["counts"]
            status.set(f"{report['total']}  /  QA: {counts['READY_FOR_WINDOWS_QA']}  /  HOLD: {counts['HOLD']}  /  BLOCKED: {counts['BLOCKED']}")
            text_area.config(state="normal")
            text_area.delete("1.0", "end")
            text_area.insert("end", json.dumps(report["products"], ensure_ascii=False, indent=2))
            text_area.config(state="disabled")
            tab.select(result_page)
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Offline QA error", str(exc))

    run_button = ttk.Button(main, command=run_check)
    run_button.pack(anchor="w", pady=12)
    ttk.Label(result_page, textvariable=status).pack(anchor="w")
    ttk.Label(result_page, textvariable=output).pack(anchor="w")
    ttk.Label(settings, text="No credentials are stored. Partner Center access is disabled in this build.").pack(anchor="w")
    ttk.Label(queue, text="Queue execution is held until real Windows adapter verification.").pack(anchor="w")

    def render(*_: object) -> None:
        lang = language.get()
        title, pick_caption, check_caption, *_rest = STRINGS[lang]
        heading.config(text=title)
        note.config(text=STRINGS[lang][-1])
        pick_button.config(text=pick_caption)
        run_button.config(text=check_caption)
        for page, text in zip(tabs, (("製品とファイル", "設定", "実行キュー", "結果") if lang == "ja" else ("Products", "Settings", "Queue", "Results"))):
            tab.tab(page, text=text)

    ttk.Radiobutton(settings, text="日本語", value="ja", variable=language, command=render).pack(anchor="w")
    ttk.Radiobutton(settings, text="English", value="en", variable=language, command=render).pack(anchor="w")
    render()
    root.mainloop()
