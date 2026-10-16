"""Minimal Tk GUI for ``fill``.

    python -m miles_inquiry gui [INPUT.xlsx]

Picks a workbook, offers the common ``fill`` switches as checkboxes and runs
:func:`miles_inquiry.cli.main` in a worker thread, showing its console output.
"""
from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# (cli flag, label, default)
OPTIONS = [
    ("--overwrite", "覆寫已有的距離", False),
    ("--keep-names", "起迄站保留原文（不改為 IATA 代碼）", False),
    ("--fill-hsr-distance", "疑似高鐵列仍填入飛航距離", False),
    ("--no-carbon", "不填碳排量", False),
    ("--overwrite-output", "輸出檔已存在時直接覆寫（預設另存為 (2)）", False),
]


class _QueueWriter:
    """File-like object forwarding writes to a queue (read by the Tk thread)."""

    def __init__(self, q: "queue.Queue[Optional[str]]") -> None:
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(s)
        return len(s)

    def flush(self) -> None:
        pass


def open_path(path: Path) -> None:
    """Open a file or folder with the system default app."""
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App:
    def __init__(self, root: tk.Tk, initial: Optional[str] = None) -> None:
        self.root = root
        self.q: "queue.Queue[Optional[str]]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        root.title("miles-inquiry 航空距離填入")
        root.minsize(560, 420)

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(4, weight=1)

        ttk.Label(frm, text="活頁簿：").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar(value=initial or "")
        ttk.Entry(frm, textvariable=self.path_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="選擇…", command=self.browse).grid(row=0, column=2)

        box = ttk.LabelFrame(frm, text="選項", padding=8)
        box.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 6))
        self.flags = {}
        for i, (flag, label, default) in enumerate(OPTIONS):
            var = tk.BooleanVar(value=default)
            ttk.Checkbutton(box, text=label, variable=var).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 16))
            self.flags[flag] = var
        self.open_after = tk.BooleanVar(value=True)
        row = (len(OPTIONS) + 1) // 2
        ttk.Checkbutton(box, text="完成後自動開啟輸出的 xlsx", variable=self.open_after).grid(
            row=row, column=0, columnspan=2, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=2, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.run_btn = ttk.Button(btns, text="開始填入", command=self.run)
        self.run_btn.pack(side="left")
        ttk.Button(btns, text="開啟資料夾", command=self.open_dir).pack(side="left", padx=6)

        ttk.Label(frm, text="執行訊息：").grid(row=3, column=0, columnspan=3, sticky="w")
        self.log = ScrolledText(frm, height=14, wrap="word", state="disabled")
        self.log.grid(row=4, column=0, columnspan=3, sticky="nsew")

        root.after(100, self.poll)

    # -- actions -------------------------------------------------------------
    def browse(self) -> None:
        path = filedialog.askopenfilename(title="選擇碳盤查活頁簿",
                                          filetypes=[("Excel 活頁簿", "*.xlsx *.xlsm"), ("所有檔案", "*.*")])
        if path:
            self.path_var.set(path)

    def _input(self) -> Optional[Path]:
        raw = self.path_var.get().strip().strip('"')
        if not raw:
            messagebox.showwarning("未選擇檔案", "請先選擇要處理的 .xlsx 檔")
            return None
        path = Path(raw)
        if not path.is_file():
            messagebox.showerror("找不到檔案", f"找不到：{path}")
            return None
        return path

    def open_dir(self) -> None:
        raw = self.path_var.get().strip().strip('"')
        folder = Path(raw).parent if raw else Path.cwd()
        if folder.is_dir():
            open_path(folder)

    def run(self) -> None:
        path = self._input()
        if path is None or (self.worker and self.worker.is_alive()):
            return
        argv: List[str] = ["fill", str(path)] + [f for f, v in self.flags.items() if v.get()]
        self._clear()
        self._append(f"處理 {path.name} …\n\n")
        self.run_btn.configure(state="disabled")
        self.worker = threading.Thread(target=self._work, args=(argv, self.open_after.get()), daemon=True)
        self.worker.start()

    def _work(self, argv: Sequence[str], open_after: bool) -> None:
        from .cli import build_parser, run

        writer = _QueueWriter(self.q)
        args = build_parser().parse_args(argv)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                code = run(args)
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected in the log
            writer.write(f"錯誤：{exc!r}\n")
            code = 1
        self.q.put("\n完成。\n" if code == 0 else "\n執行失敗，請檢查上方訊息。\n")
        output = getattr(args, "written_output", None)
        if code == 0 and open_after and output is not None:
            try:
                open_path(output)
            except OSError as exc:
                self.q.put(f"無法自動開啟 {output}：{exc}\n")
        self.q.put(None)

    # -- log -----------------------------------------------------------------
    def poll(self) -> None:
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:
                    self.run_btn.configure(state="normal")
                else:
                    self._append(item)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def _append(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


def main(initial: Optional[str] = None) -> int:
    if sys.platform.startswith("win"):
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
    root = tk.Tk()
    # Under pythonw there is no console, so startup failures must be shown in a dialog.
    try:
        from . import cli  # noqa: F401 - fail early (and visibly) if openpyxl is missing
        App(root, initial)
    except ImportError as exc:
        root.withdraw()
        messagebox.showerror("缺少套件", f"{exc}\n\n請先執行：pip install openpyxl geographiclib")
        return 1
    except Exception:  # noqa: BLE001
        import traceback
        root.withdraw()
        messagebox.showerror("啟動失敗", traceback.format_exc())
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
