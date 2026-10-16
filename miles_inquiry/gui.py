"""Minimal Tk GUI for ``fill``.

    python -m miles_inquiry gui [INPUT.xlsx ...]

Collects workbooks in a list (選擇… / drag-and-drop, several at once or in
several drops; 移除 / Delete key removes them), offers the common ``fill``
switches as checkboxes and runs :func:`miles_inquiry.cli.run` for each file in
a worker thread, showing its console output.

Drag-and-drop from the file manager needs the optional ``tkinterdnd2`` package
(plain tkinter cannot receive OS drops); without it the GUI still works.
"""
from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # optional: GUI works without drag-and-drop
    TkinterDnD = None
    DND_FILES = None

EXTENSIONS = (".xlsx", ".xlsm")

# (cli flag, label, default)
OPTIONS = [
    ("--overwrite", "覆寫已有的距離", False),
    ("--keep-names", "起迄站保留原文（不改為 IATA 代碼）", False),
    ("--fill-hsr-distance", "疑似高鐵列仍填入飛航距離", False),
    ("--no-carbon", "不填碳排量", False),
    ("--overwrite-output", "輸出檔已存在時直接覆寫（預設另存為 (2)）", False),
]

# Messages from the worker thread: ("log", text) | ("status", iid, text) | ("done", None)
Msg = Tuple[str, object, Optional[str]]


class _QueueWriter:
    """File-like object forwarding writes to a queue (read by the Tk thread)."""

    def __init__(self, q: "queue.Queue[Msg]") -> None:
        self.q = q

    def write(self, s: str) -> int:
        if s:
            self.q.put(("log", s, None))
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


def expand_inputs(paths: Iterable[str]) -> Tuple[List[Path], List[str]]:
    """Dropped/chosen paths → workbook files (folders expand to their workbooks) and rejected names."""
    files: List[Path] = []
    rejected: List[str] = []
    for raw in paths:
        p = Path(raw.strip().strip('"'))
        if p.is_dir():
            files.extend(sorted(c for c in p.iterdir() if _is_workbook(c)))
        elif _is_workbook(p):
            files.append(p)
        elif str(p):
            rejected.append(p.name or str(p))
    return files, rejected


def _is_workbook(p: Path) -> bool:
    # ~$name.xlsx is Excel's lock file for an open workbook
    return p.is_file() and p.suffix.lower() in EXTENSIONS and not p.name.startswith("~$")


class App:
    def __init__(self, root: tk.Tk, initial: Sequence[str] = ()) -> None:
        self.root = root
        self.q: "queue.Queue[Msg]" = queue.Queue()
        self.worker: Optional[threading.Thread] = None
        self.files: dict = {}  # tree iid -> Path, in insertion order
        root.title("miles-inquiry 航空距離填入")
        root.minsize(620, 560)

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(1, weight=1)
        frm.rowconfigure(6, weight=1)

        dnd = TkinterDnD is not None and hasattr(root, "drop_target_register")
        hint = "活頁簿（可拖曳多個 .xlsx 或資料夾到下方清單，可分次拖曳）：" if dnd else \
            "活頁簿（按「新增…」選擇；pip install tkinterdnd2 可啟用拖曳）："
        ttk.Label(frm, text=hint).grid(row=0, column=0, sticky="w")

        lst = ttk.Frame(frm)
        lst.grid(row=1, column=0, sticky="nsew", pady=(4, 4))
        lst.columnconfigure(0, weight=1)
        lst.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(lst, columns=("status", "folder"), height=6, selectmode="extended")
        self.tree.heading("#0", text="檔名")
        self.tree.heading("status", text="狀態")
        self.tree.heading("folder", text="資料夾")
        self.tree.column("#0", width=220, stretch=True)
        self.tree.column("status", width=80, stretch=False)
        self.tree.column("folder", width=260, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lst, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<BackSpace>", lambda e: self.remove_selected())
        if dnd:
            for w in (root, self.tree):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

        fb = ttk.Frame(frm)
        fb.grid(row=2, column=0, sticky="w", pady=(0, 6))
        ttk.Button(fb, text="新增…", command=self.browse).pack(side="left")
        self.remove_btn = ttk.Button(fb, text="移除選取", command=self.remove_selected)
        self.remove_btn.pack(side="left", padx=6)
        self.clear_btn = ttk.Button(fb, text="全部清除", command=self.clear_files)
        self.clear_btn.pack(side="left")

        box = ttk.LabelFrame(frm, text="選項", padding=8)
        box.grid(row=3, column=0, sticky="ew", pady=(4, 6))
        self.flags = {}
        for i, (flag, label, default) in enumerate(OPTIONS):
            var = tk.BooleanVar(value=default)
            ttk.Checkbutton(box, text=label, variable=var).grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 16))
            self.flags[flag] = var
        self.open_after = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="完成後自動開啟輸出的 xlsx", variable=self.open_after).grid(
            row=(len(OPTIONS) + 1) // 2, column=0, columnspan=2, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, sticky="w", pady=(0, 6))
        self.run_btn = ttk.Button(btns, text="開始填入", command=self.run)
        self.run_btn.pack(side="left")
        ttk.Button(btns, text="開啟資料夾", command=self.open_dir).pack(side="left", padx=6)

        ttk.Label(frm, text="執行訊息：").grid(row=5, column=0, sticky="w")
        self.log = ScrolledText(frm, height=10, wrap="word", state="disabled")
        self.log.grid(row=6, column=0, sticky="nsew")

        self.add_files([s for s in initial if s])
        root.after(100, self.poll)

    # -- file list -------------------------------------------------------------
    def add_files(self, paths: Iterable[str]) -> int:
        files, rejected = expand_inputs(paths)
        known = {os.path.normcase(str(p.resolve())) for p in self.files.values()}
        added = 0
        for p in files:
            key = os.path.normcase(str(p.resolve()))
            if key in known:
                continue
            known.add(key)
            iid = self.tree.insert("", "end", text=p.name, values=("待處理", str(p.parent)))
            self.files[iid] = p
            added += 1
        if rejected:
            self._append(f"略過（不是 .xlsx/.xlsm）：{'、'.join(rejected)}\n")
        return added

    def on_drop(self, event) -> str:
        self.add_files(self.root.tk.splitlist(event.data))
        return getattr(event, "action", "copy")

    def browse(self) -> None:
        paths = filedialog.askopenfilenames(title="選擇碳盤查活頁簿",
                                            filetypes=[("Excel 活頁簿", "*.xlsx *.xlsm"), ("所有檔案", "*.*")])
        if paths:
            self.add_files(self.root.tk.splitlist(paths) if isinstance(paths, str) else paths)

    def remove_selected(self) -> None:
        if self._busy():
            return
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.files.pop(iid, None)

    def clear_files(self) -> None:
        if self._busy():
            return
        self.tree.delete(*self.tree.get_children())
        self.files.clear()

    def open_dir(self) -> None:
        sel = self.tree.selection() or tuple(self.files)
        folder = self.files[sel[0]].parent if sel else Path.cwd()
        if folder.is_dir():
            open_path(folder)

    # -- run -------------------------------------------------------------------
    def _busy(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def run(self) -> None:
        if self._busy():
            return
        if not self.files:
            messagebox.showwarning("未選擇檔案", "請先拖曳或「新增…」要處理的 .xlsx 檔")
            return
        jobs = list(self.files.items())
        flags = [f for f, v in self.flags.items() if v.get()]
        for iid, _ in jobs:
            self.tree.set(iid, "status", "等待中")
        self._clear()
        for b in (self.run_btn, self.remove_btn, self.clear_btn):
            b.configure(state="disabled")
        self.worker = threading.Thread(target=self._work, args=(jobs, flags, self.open_after.get()), daemon=True)
        self.worker.start()

    def _work(self, jobs: Sequence[Tuple[str, Path]], flags: Sequence[str], open_after: bool) -> None:
        from .cli import build_parser, run

        writer = _QueueWriter(self.q)
        failed = 0
        for n, (iid, path) in enumerate(jobs, 1):
            self.q.put(("status", iid, "處理中"))
            writer.write(f"{'=' * 8} [{n}/{len(jobs)}] {path.name} {'=' * 8}\n")
            args = build_parser().parse_args(["fill", str(path), *flags])
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    code = run(args)
            except Exception as exc:  # noqa: BLE001 - surface anything unexpected in the log
                writer.write(f"錯誤：{exc!r}\n")
                code = 1
            output = getattr(args, "written_output", None)
            if code == 0:
                self.q.put(("status", iid, "完成"))
                if open_after and output is not None:
                    try:
                        open_path(output)
                    except OSError as exc:
                        writer.write(f"無法自動開啟 {output}：{exc}\n")
            else:
                failed += 1
                self.q.put(("status", iid, "失敗"))
            writer.write("\n")
        writer.write(f"全部完成（{len(jobs)} 個檔案）。\n" if not failed else
                     f"完成 {len(jobs) - failed} 個、失敗 {failed} 個，請檢查上方訊息。\n")
        self.q.put(("done", None, None))

    # -- log -------------------------------------------------------------------
    def poll(self) -> None:
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "log":
                    self._append(str(a))
                elif kind == "status":
                    if self.tree.exists(a):
                        self.tree.set(a, "status", b)
                else:
                    for btn in (self.run_btn, self.remove_btn, self.clear_btn):
                        btn.configure(state="normal")
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


def main(initial: Sequence[str] = ()) -> int:
    if isinstance(initial, str):
        initial = [initial]
    if sys.platform.startswith("win"):
        with contextlib.suppress(Exception):
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # sharp text on high-DPI screens
    root = None
    if TkinterDnD is not None:
        with contextlib.suppress(Exception):  # tkdnd binary missing for this platform → no drag-and-drop
            root = TkinterDnD.Tk()
    if root is None:
        globals()["TkinterDnD"] = None
        root = tk.Tk()
    # Under pythonw there is no console, so startup failures must be shown in a dialog.
    try:
        from . import cli  # noqa: F401 - fail early (and visibly) if openpyxl is missing
        App(root, initial or ())
    except ImportError as exc:
        root.withdraw()
        messagebox.showerror("缺少套件", f"{exc}\n\n請先執行：pip install openpyxl geographiclib tkinterdnd2")
        return 1
    except Exception:  # noqa: BLE001
        import traceback
        root.withdraw()
        messagebox.showerror("啟動失敗", traceback.format_exc())
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
