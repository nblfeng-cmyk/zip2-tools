#!/usr/bin/env python3
"""
zip_image_filter.py — 压缩包图片数量/大小筛选工具
扫描 ZIP 文件，按内部图片数量和文件大小筛选，支持批量提取/剪切/删除
"""

# ── 高 DPI 支持 ──
import sys as _sys
if _sys.platform == 'win32':
    import ctypes as _ctypes
    try:
        _ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            _ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                _ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import queue
import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

# ── Pillow（预览用） ──
try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    Image = None
    ImageTk = None
    HAS_PIL = False

# ── 支持的图片扩展名 ──
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.svg'}
MAX_WORKERS = max(1, int((os.cpu_count() or 4) * 0.8))


# ═══════════════════════════════════════════════
#  扫描引擎
# ═══════════════════════════════════════════════

def count_images_in_zip(zip_path: str) -> int:
    """快速统计一个 ZIP 内的图片数量（仅读文件列表，不解压）。"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            return sum(
                1 for n in zf.namelist()
                if Path(n).suffix.lower() in IMAGE_EXTS
            )
    except Exception:
        return -1  # 损坏


# ═══════════════════════════════════════════════
#  主窗口
# ═══════════════════════════════════════════════

class ZipImageFilterApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("压缩包图片数量筛选工具")
        self.root.resizable(True, True)

        # DPI 缩放
        self._dpi_scale = 1.0
        try:
            if _sys.platform == 'win32':
                dpi = _ctypes.windll.user32.GetDpiForWindow(self.root.winfo_id())
                self._dpi_scale = dpi / 96
                self.root.tk.call('tk', 'scaling', dpi / 72)
        except Exception:
            pass

        _s = self._dpi_scale
        self.root.minsize(int(900 * _s), int(600 * _s))
        self.root.geometry(f"{int(1050*_s)}x{int(720*_s)}+{int(300*_s)}+{int(150*_s)}")

        # Vista 主题
        style = ttk.Style()
        for t in ('vista', 'winnative', 'xpnative', 'clam'):
            if t in style.theme_names():
                style.theme_use(t)
                break

        # Treeview 行高
        _rh = max(20, int(22 * _s))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=_rh)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        # 状态
        self.scanned_files: list[dict] = []   # [{path, size, images, valid}]
        self.filtered_results: list[dict] = []
        self.scanning = False
        self.stop_scan = threading.Event()
        self.recursive_var = tk.BooleanVar(value=True)
        self.msg_queue = queue.Queue()
        self.target_dir = Path(os.path.expanduser('~/Desktop'))

        self._build_ui()
        self._update_counts()
        self.root.after(100, self._poll_queue)

    def _build_ui(self):
        _s = self._dpi_scale
        root = self.root
        main = ttk.Frame(root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ═══ 标题 ═══
        ttk.Label(
            main, text="压缩包图片数量筛选工具",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        # ═══ 第一行：扫描范围 ═══
        scan_frame = ttk.LabelFrame(main, text="扫描范围", padding=4)
        scan_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # 按钮行
        scan_btn_row = ttk.Frame(scan_frame)
        scan_btn_row.pack(fill=tk.X, pady=(0, 3))

        ttk.Button(scan_btn_row, text="添加文件", command=self._add_files, width=10).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(scan_btn_row, text="添加文件夹", command=self._add_directory, width=12).pack(side=tk.LEFT, padx=3)
        ttk.Button(scan_btn_row, text="清空列表", command=self._clear_scan, width=8).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(
            scan_btn_row, text="包含子目录",
            variable=self.recursive_var,
        ).pack(side=tk.LEFT, padx=6)
        self.scan_btn = ttk.Button(scan_btn_row, text="扫描图片数", command=self._start_scan, width=12)
        self.scan_btn.pack(side=tk.LEFT, padx=(3, 0))
        self.stop_scan_btn = ttk.Button(scan_btn_row, text="停止", command=self._stop_scan, width=6, state=tk.DISABLED)
        self.stop_scan_btn.pack(side=tk.LEFT, padx=3)
        self.scan_count_label = ttk.Label(scan_btn_row, text="共 0 个文件", foreground="#555")
        self.scan_count_label.pack(side=tk.RIGHT, padx=4)

        # 扫描列表 Treeview
        scan_cols = ("name", "size", "images", "status")
        self.scan_tree = ttk.Treeview(
            scan_frame, columns=scan_cols, show="headings",
            height=5, selectmode="extended",
        )
        self.scan_tree.heading("name", text="文件名")
        self.scan_tree.heading("size", text="大小", anchor=tk.E)
        self.scan_tree.heading("images", text="图片数", anchor=tk.CENTER)
        self.scan_tree.heading("status", text="状态", anchor=tk.CENTER)
        self.scan_tree.column("name", width=int(300*_s), minwidth=int(150*_s), stretch=True)
        self.scan_tree.column("size", width=int(90*_s), minwidth=int(70*_s), anchor=tk.E)
        self.scan_tree.column("images", width=int(70*_s), minwidth=int(60*_s), anchor=tk.CENTER)
        self.scan_tree.column("status", width=int(100*_s), minwidth=int(70*_s), anchor=tk.CENTER)

        sv = ttk.Scrollbar(scan_frame, orient=tk.VERTICAL, command=self.scan_tree.yview)
        self.scan_tree.configure(yscrollcommand=sv.set)
        self.scan_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sv.pack(side=tk.RIGHT, fill=tk.Y)

        # ═══ 第二行：筛选条件 ═══
        filter_frame = ttk.LabelFrame(main, text="筛选条件", padding=4)
        filter_frame.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(filter_frame, text="图片数量 ≥").pack(side=tk.LEFT)
        self.min_images_var = tk.IntVar(value=10)
        ttk.Spinbox(
            filter_frame, from_=0, to=99999,
            textvariable=self.min_images_var, width=6,
        ).pack(side=tk.LEFT, padx=(3, 12))

        ttk.Label(filter_frame, text="文件大小:").pack(side=tk.LEFT)
        ttk.Label(filter_frame, text="≥").pack(side=tk.LEFT, padx=(3, 0))
        self.min_size_var = tk.IntVar(value=0)
        ttk.Spinbox(
            filter_frame, from_=0, to=999999,
            textvariable=self.min_size_var, width=7,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Label(filter_frame, text="MB").pack(side=tk.LEFT)

        ttk.Label(filter_frame, text="  ≤").pack(side=tk.LEFT)
        self.max_size_var = tk.IntVar(value=99999)
        ttk.Spinbox(
            filter_frame, from_=0, to=999999,
            textvariable=self.max_size_var, width=7,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Label(filter_frame, text="MB").pack(side=tk.LEFT)

        self.filter_btn = ttk.Button(
            filter_frame, text="开始筛选", command=self._do_filter, width=12,
        )
        self.filter_btn.pack(side=tk.LEFT, padx=(12, 0))
        self.filter_count_label = ttk.Label(filter_frame, text="", foreground="#555")
        self.filter_count_label.pack(side=tk.LEFT, padx=8)

        # ═══ 第三行：筛选结果 ═══
        result_frame = ttk.LabelFrame(main, text="筛选结果", padding=4)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        res_cols = ("sel", "name", "size", "images", "path")
        self.res_tree = ttk.Treeview(
            result_frame, columns=res_cols, show="headings",
            height=6, selectmode="extended",
        )
        self.res_tree.heading("sel", text="☑")
        self.res_tree.heading("name", text="文件名")
        self.res_tree.heading("size", text="大小", anchor=tk.E)
        self.res_tree.heading("images", text="图片数", anchor=tk.CENTER)
        self.res_tree.heading("path", text="完整路径")
        self.res_tree.column("sel", width=int(35*_s), minwidth=int(30*_s), anchor=tk.CENTER)
        self.res_tree.column("name", width=int(220*_s), minwidth=int(120*_s), stretch=True)
        self.res_tree.column("size", width=int(90*_s), minwidth=int(70*_s), anchor=tk.E)
        self.res_tree.column("images", width=int(70*_s), minwidth=int(60*_s), anchor=tk.CENTER)
        self.res_tree.column("path", width=int(350*_s), minwidth=int(150*_s), stretch=True)

        rv = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.res_tree.yview)
        self.res_tree.configure(yscrollcommand=rv.set)
        self.res_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        rv.pack(side=tk.RIGHT, fill=tk.Y)

        # 勾选操作 + 双击预览
        self.res_tree.bind('<ButtonRelease-1>', self._toggle_sel)
        self.res_tree.bind('<Double-1>', self._preview_images)
        # 全选/取消按钮
        sel_row = ttk.Frame(result_frame)
        sel_row.pack(fill=tk.X, pady=2)

        ttk.Button(sel_row, text="全选", command=self._select_all, width=6).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(sel_row, text="取消全选", command=self._deselect_all, width=8).pack(side=tk.LEFT)

        # ═══ 第四行：操作栏 ═══
        action_frame = ttk.LabelFrame(main, text="操作", padding=4)
        action_frame.pack(fill=tk.X)

        self.no_extract_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            action_frame, text="不解压缩（仅复制/移动 ZIP）",
            variable=self.no_extract_var,
        ).pack(side=tk.LEFT)

        ttk.Label(action_frame, text="目标目录:").pack(side=tk.LEFT, padx=(12, 0))
        self.dir_label = ttk.Label(action_frame, text=str(self.target_dir), foreground="#333")
        self.dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(action_frame, text="浏览...", command=self._select_target_dir, width=8).pack(side=tk.RIGHT, padx=(0, 4))

        btn_row = ttk.Frame(action_frame)
        btn_row.pack(fill=tk.X, pady=(4, 0))

        self.extract_btn = ttk.Button(btn_row, text="提取到目标目录", command=lambda: self._do_action('extract'), width=16)
        self.extract_btn.pack(side=tk.LEFT, padx=(0, 4))

        self.cut_btn = ttk.Button(btn_row, text="剪切到目标目录", command=lambda: self._do_action('cut'), width=16)
        self.cut_btn.pack(side=tk.LEFT, padx=4)

        self.delete_btn = ttk.Button(btn_row, text="删除选中文件", command=lambda: self._do_action('delete'), width=14)
        self.delete_btn.pack(side=tk.LEFT, padx=4)

        # 状态栏
        self.status_bar = ttk.Label(main, text="就绪", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(fill=tk.X, pady=(4, 0))

    # ── 扫描文件管理 ──

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 ZIP 文件",
            filetypes=[("ZIP 压缩包", "*.zip"), ("所有文件", "*.*")],
        )
        added = 0
        existing = {d['path'] for d in self.scanned_files}
        for f in files:
            p = Path(f)
            if str(p) not in existing:
                self.scanned_files.append({
                    'path': str(p),
                    'name': p.name,
                    'size': p.stat().st_size,
                    'images': -1,
                    'valid': True,
                })
                existing.add(str(p))
                self.scan_tree.insert("", tk.END, values=(p.name, self._fmt_size(p.stat().st_size), "待扫描", ""))
                added += 1
        if added:
            self._update_counts()

    def _add_directory(self):
        d = filedialog.askdirectory(title="选择包含 ZIP 文件的文件夹")
        if not d:
            return
        existing = {d['path'] for d in self.scanned_files}
        added = 0
        pattern = Path(d).rglob('*.zip') if self.recursive_var.get() else Path(d).glob('*.zip')
        for p in pattern:
            if p.is_file() and str(p) not in existing:
                self.scanned_files.append({
                    'path': str(p),
                    'name': p.name,
                    'size': p.stat().st_size,
                    'images': -1,
                    'valid': True,
                })
                existing.add(str(p))
                self.scan_tree.insert("", tk.END, values=(p.name, self._fmt_size(p.stat().st_size), "待扫描", ""))
                added += 1
        if added:
            self._update_counts()

    def _clear_scan(self):
        self.scanned_files.clear()
        for item in self.scan_tree.get_children():
            self.scan_tree.delete(item)
        for item in self.res_tree.get_children():
            self.res_tree.delete(item)
        self.filtered_results.clear()
        self._update_counts()
        self.filter_count_label.config(text="")
        self.status_bar.config(text="已清空")

    def _update_counts(self):
        self.scan_count_label.config(text=f"共 {len(self.scanned_files)} 个文件")

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024: return f"{size} B"
        elif size < 1024**2: return f"{size/1024:.1f} KB"
        elif size < 1024**3: return f"{size/1024**2:.1f} MB"
        else: return f"{size/1024**3:.2f} GB"

    # ── 扫描（统计各 ZIP 内图片数） ──

    def _start_scan(self):
        if self.scanning:
            return
        if not self.scanned_files:
            messagebox.showinfo("提示", "请先添加要扫描的 ZIP 文件")
            return

        # 重置所有状态
        for item in self.scan_tree.get_children():
            vals = list(self.scan_tree.item(item, 'values'))
            vals[2] = "待扫描"
            vals[3] = ""
            self.scan_tree.item(item, values=vals)

        self.scanning = True
        self.stop_scan.clear()
        self.scan_btn.config(state=tk.DISABLED)
        self.stop_scan_btn.config(state=tk.NORMAL)
        self.status_bar.config(text=f"正在统计 {len(self.scanned_files)} 个文件的图片数...")

        thread = threading.Thread(target=self._do_scan, daemon=True)
        thread.start()

    def _stop_scan(self):
        """停止扫描。"""
        self.stop_scan.set()
        self.stop_scan_btn.config(state=tk.DISABLED)
        self.status_bar.config(text="正在停止...")

    def _do_scan(self):
        """后台扫描所有文件的图片数量。"""
        total = len(self.scanned_files)
        for i, data in enumerate(self.scanned_files):
            if self.stop_scan.is_set():
                self.msg_queue.put(("scan_stopped",))
                return
            count = count_images_in_zip(data['path'])
            data['images'] = count
            if count >= 0:
                status_text = f"{count} 张"
                status_tag = "正常"
            else:
                status_text = "损坏"
                status_tag = "损坏"

            self.msg_queue.put(("scan_update", i, status_text, status_tag))
            pct = (i + 1) / total * 100
            self.msg_queue.put(("status", f"扫描中... {i+1}/{total} ({pct:.0f}%)"))

        self.msg_queue.put(("scan_done",))

    # ── 筛选 ──

    def _do_filter(self):
        if not self.scanned_files:
            messagebox.showinfo("提示", "请先添加并扫描文件")
            return

        min_img = self.min_images_var.get()
        min_size_mb = self.min_size_var.get()
        max_size_mb = self.max_size_var.get()

        for item in self.res_tree.get_children():
            self.res_tree.delete(item)

        self.filtered_results.clear()
        for data in self.scanned_files:
            if data['images'] < 0:
                continue  # 损坏或未扫描
            size_mb = data['size'] / 1024 / 1024
            if data['images'] >= min_img and min_size_mb <= size_mb <= max_size_mb:
                self.filtered_results.append(data)
                self.res_tree.insert("", tk.END,
                    values=("☐", data['name'], self._fmt_size(data['size']), data['images'], data['path']),
                )

        self.filter_count_label.config(text=f"找到 {len(self.filtered_results)} 个")
        self.status_bar.config(
            text=f"筛选完成: {len(self.filtered_results)} 个文件满足条件"
        )

    # ── 结果勾选 ──

    def _toggle_sel(self, event):
        """点击勾选列切换勾选状态。"""
        col = self.res_tree.identify_column(event.x)
        if col == '#0' or col == '#1':  # sel 列
            item = self.res_tree.identify_row(event.y)
            if item:
                vals = list(self.res_tree.item(item, 'values'))
                vals[0] = "☑" if vals[0] == "☐" else "☐"
                self.res_tree.item(item, values=vals)

    def _select_all(self):
        for item in self.res_tree.get_children():
            vals = list(self.res_tree.item(item, 'values'))
            vals[0] = "☑"
            self.res_tree.item(item, values=vals)

    def _deselect_all(self):
        for item in self.res_tree.get_children():
            vals = list(self.res_tree.item(item, 'values'))
            vals[0] = "☐"
            self.res_tree.item(item, values=vals)

    def _get_selected_results(self) -> list[dict]:
        """获取所有勾选的结果。"""
        selected = []
        for i, item in enumerate(self.res_tree.get_children()):
            vals = self.res_tree.item(item, 'values')
            if vals[0] == "☑" and i < len(self.filtered_results):
                selected.append(self.filtered_results[i])
        return selected

    # ── 目标目录 ──

    def _select_target_dir(self):
        d = filedialog.askdirectory(title="选择目标目录", initialdir=str(self.target_dir))
        if d:
            self.target_dir = Path(d)
            text = str(self.target_dir)
            if len(text) > 65:
                text = text[:30] + '...' + text[-32:]
            self.dir_label.config(text=text)

    # ── 批量操作 ──

    def _do_action(self, action: str):
        selected = self._get_selected_results()
        if not selected:
            messagebox.showwarning("提示", "请先在结果列表中勾选文件（点击 ☐ 列切换）")
            return

        n = len(selected)
        action_names = {'extract': '提取', 'cut': '剪切', 'delete': '删除'}
        label = action_names.get(action, action)

        if action == 'delete':
            ok = messagebox.askyesno(
                "确认删除",
                f"确定要永久删除以下 {n} 个文件吗？\n\n" +
                "\n".join(d['name'] for d in selected[:10]) +
                ("\n..." if n > 10 else ""),
                icon='warning',
            )
            if not ok:
                return
        else:
            if not self.target_dir.exists():
                self.target_dir.mkdir(parents=True)
            ok = messagebox.askyesno(
                "确认操作",
                f"将 {label} {n} 个文件到:\n{self.target_dir}\n\n" +
                "\n".join(d['name'] for d in selected[:10]) +
                ("\n..." if n > 10 else ""),
            )
            if not ok:
                return

        # 后台执行
        self.extract_btn.config(state=tk.DISABLED)
        self.cut_btn.config(state=tk.DISABLED)
        self.delete_btn.config(state=tk.DISABLED)
        self.status_bar.config(text=f"正在{label}...")

        thread = threading.Thread(
            target=self._do_action_thread,
            args=(action, selected),
            daemon=True,
        )
        thread.start()

    def _do_action_thread(self, action: str, files: list[dict]):
        no_extract = self.no_extract_var.get()
        success = 0
        failed = 0
        total = len(files)

        for i, data in enumerate(files):
            src = Path(data['path'])
            try:
                if action == 'extract':
                    if no_extract:
                        # 仅复制 ZIP
                        shutil.copy2(src, self.target_dir / data['name'])
                    else:
                        # 解压到目标目录的子文件夹
                        dest_dir = self.target_dir / data['name'].replace('.zip', '')
                        with zipfile.ZipFile(src, 'r') as zf:
                            zf.extractall(dest_dir)
                    success += 1
                elif action == 'cut':
                    if no_extract:
                        # 仅移动 ZIP
                        shutil.move(str(src), str(self.target_dir / data['name']))
                    else:
                        # 解压后删除原文件
                        dest_dir = self.target_dir / data['name'].replace('.zip', '')
                        with zipfile.ZipFile(src, 'r') as zf:
                            zf.extractall(dest_dir)
                        src.unlink()
                    success += 1
                elif action == 'delete':
                    src.unlink()
                    success += 1
            except Exception as e:
                failed += 1
                self.msg_queue.put(("log", f"  ✗ {data['name']}: {e}"))

            self.msg_queue.put(("status", f"正在处理... {i+1}/{total}"))

        self.msg_queue.put(("action_done", action, success, failed))

    # ── 队列轮询 ──

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]

                if kind == "scan_update":
                    idx, text, tag = msg[1], msg[2], msg[3]
                    children = self.scan_tree.get_children()
                    if idx < len(children):
                        vals = list(self.scan_tree.item(children[idx], 'values'))
                        vals[2] = text
                        vals[3] = tag
                        self.scan_tree.item(children[idx], values=vals)

                elif kind == "scan_done":
                    self.scanning = False
                    self.scan_btn.config(state=tk.NORMAL)
                    self.stop_scan_btn.config(state=tk.DISABLED)
                    self.status_bar.config(text="扫描完成")

                elif kind == "scan_stopped":
                    self.scanning = False
                    self.scan_btn.config(state=tk.NORMAL)
                    self.stop_scan_btn.config(state=tk.DISABLED)
                    self.status_bar.config(text="扫描已停止")

                elif kind == "status":
                    self.status_bar.config(text=msg[1])

                elif kind == "log":
                    # 简化日志：直接更新状态栏
                    pass

                elif kind == "action_done":
                    action, success, failed = msg[1], msg[2], msg[3]
                    names = {'extract': '提取', 'cut': '剪切', 'delete': '删除'}
                    label = names.get(action, action)
                    self.extract_btn.config(state=tk.NORMAL)
                    self.cut_btn.config(state=tk.NORMAL)
                    self.delete_btn.config(state=tk.NORMAL)
                    self.status_bar.config(
                        text=f"{label}完成: 成功 {success}, 失败 {failed}"
                    )
                    if action in ('cut', 'delete'):
                        # 从扫描列表中移除已处理文件
                        self._remove_processed()
                    messagebox.showinfo("操作完成", f"{label}完成\n成功: {success}\n失败: {failed}")

        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    def _remove_processed(self):
        """删除/剪切后，从扫描列表移除已不存在的文件。"""
        to_remove = []
        for i, data in enumerate(self.scanned_files):
            if not os.path.isfile(data['path']):
                to_remove.append(i)

        for i in reversed(to_remove):
            del self.scanned_files[i]
            children = self.scan_tree.get_children()
            if i < len(children):
                self.scan_tree.delete(children[i])

        # 同时清理结果列表
        for item in self.res_tree.get_children():
            self.res_tree.delete(item)
        self.filtered_results = [
            d for d in self.filtered_results if os.path.isfile(d['path'])
        ]
        for data in self.filtered_results:
            self.res_tree.insert("", tk.END,
                values=("☐", data['name'], self._fmt_size(data['size']), data['images'], data['path']),
            )

        self._update_counts()

    # ── 图片预览 ──

    def _preview_images(self, event):
        """双击结果行，弹出图片预览窗口。"""
        item = self.res_tree.identify_row(event.y)
        if not item:
            return
        idx = self.res_tree.index(item)
        if idx >= len(self.filtered_results):
            return

        data = self.filtered_results[idx]
        zip_path = data['path']

        # 先读取图片列表
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                all_files = zf.namelist()
                img_files = [n for n in all_files if Path(n).suffix.lower() in IMAGE_EXTS]
        except Exception as e:
            messagebox.showerror("错误", f"无法读取压缩包:\n{e}")
            return

        if not img_files:
            messagebox.showinfo("提示", "该压缩包内没有图片")
            return

        # 创建预览窗口
        _s = self._dpi_scale
        win = tk.Toplevel(self.root)
        win.title(f"预览 — {data['name']} ({len(img_files)} 张图片)")
        win.geometry(f"{int(900*_s)}x{int(600*_s)}+{int(400*_s)}+{int(200*_s)}")
        win.minsize(int(600*_s), int(400*_s))
        win.transient(self.root)

        # DPI 缩放
        try:
            if _sys.platform == 'win32':
                dpi = _ctypes.windll.user32.GetDpiForWindow(win.winfo_id())
                win.tk.call('tk', 'scaling', dpi / 72)
        except Exception:
            pass

        # 主布局
        main = ttk.Frame(win, padding=6)
        main.pack(fill=tk.BOTH, expand=True)

        # 左侧：文件列表
        left = ttk.Frame(main, width=int(250*_s))
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
        left.pack_propagate(False)

        ttk.Label(left, text="图片列表", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)

        listbox = tk.Listbox(
            left, font=("Consolas", 9),
            selectbackground="#0078D7", selectforeground="white",
        )
        sv = ttk.Scrollbar(left, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=sv.set)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sv.pack(side=tk.RIGHT, fill=tk.Y)

        for f in img_files:
            listbox.insert(tk.END, f)

        # 右侧：预览区域
        right = ttk.Frame(main)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        ttk.Label(right, text="图片预览", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)

        # Canvas + 滚动条
        canvas_frame = ttk.Frame(right)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL)
        vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL)
        canvas = tk.Canvas(
            canvas_frame, bg="#1e1e1e",
            xscrollcommand=hbar.set, yscrollcommand=vbar.set,
        )
        hbar.config(command=canvas.xview)
        vbar.config(command=canvas.yview)

        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        # 状态信息
        info_label = ttk.Label(right, text="", foreground="#555")
        info_label.pack(fill=tk.X)

        # ── 选择预览函数 ──
        self._current_img = None
        self._current_photo = None

        def show_preview(event=None):
            sel = listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            fname = img_files[idx]
            info_label.config(text=f"加载中: {fname}")
            win.update()

            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    with zf.open(fname) as f:
                        img = Image.open(f)
                        # 复制到内存（避免文件句柄问题）
                        img.load()
                        img_copy = img.copy()

                # 缩放显示
                max_w, max_h = canvas.winfo_width() - 10, canvas.winfo_height() - 10
                if max_w < 50:
                    max_w = 400
                if max_h < 50:
                    max_h = 300

                display = img_copy.copy()
                display.thumbnail((max_w, max_h), Image.LANCZOS)

                self._current_photo = ImageTk.PhotoImage(display)
                self._current_img = img_copy

                canvas.delete('all')
                canvas.create_image(
                    max_w // 2, max_h // 2,
                    image=self._current_photo, anchor=tk.CENTER,
                )
                canvas.configure(scrollregion=(0, 0, max_w, max_h))

                info_label.config(
                    text=f"{fname}  —  {img_copy.size[0]}×{img_copy.size[1]}  "
                         f"({idx+1}/{len(img_files)})"
                )
            except Exception as e:
                info_label.config(text=f"  ✗ {e}")

        listbox.bind('<<ListboxSelect>>', show_preview)

        # 键盘导航
        def on_key(event):
            if event.keysym == 'Down':
                sel = listbox.curselection()
                if sel and sel[0] < listbox.size() - 1:
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(sel[0] + 1)
                    listbox.activate(sel[0] + 1)
                    show_preview()
            elif event.keysym == 'Up':
                sel = listbox.curselection()
                if sel and sel[0] > 0:
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(sel[0] - 1)
                    listbox.activate(sel[0] - 1)
                    show_preview()

        win.bind('<Down>', on_key)
        win.bind('<Up>', on_key)

        # ── 鼠标滚轮切换图片 ──
        def on_mousewheel(event):
            sel = listbox.curselection()
            if not sel:
                return
            if event.delta > 0:  # 滚轮向上 → 上一张
                if sel[0] > 0:
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(sel[0] - 1)
                    listbox.activate(sel[0] - 1)
                    show_preview()
            else:  # 滚轮向下 → 下一张
                if sel[0] < listbox.size() - 1:
                    listbox.selection_clear(0, tk.END)
                    listbox.selection_set(sel[0] + 1)
                    listbox.activate(sel[0] + 1)
                    show_preview()

        # 绑定到窗口和列表、Canvas（鼠标在哪都能滚）
        for widget in (win, listbox, canvas, info_label):
            widget.bind('<MouseWheel>', on_mousewheel)

        # ── 鼠标中键全屏 ──
        _is_fullscreen = [False]

        def toggle_fullscreen(event=None):
            _is_fullscreen[0] = not _is_fullscreen[0]
            win.attributes('-fullscreen', _is_fullscreen[0])
            if _is_fullscreen[0]:
                # 全屏时隐藏列表和标题栏装饰
                left.pack_forget()
                ttk.Label(right, text="").pack_forget()  # 占位清理
                info_label.pack_forget()
                # 重绘图片占满全屏
                win.after(100, show_preview)
            else:
                left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
                info_label.pack(fill=tk.X)
                win.after(100, show_preview)

        win.bind('<Button-2>', toggle_fullscreen)   # 鼠标中键

        def exit_fullscreen(event=None):
            if win.attributes('-fullscreen'):
                _is_fullscreen[0] = False
                win.attributes('-fullscreen', False)
                left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 4))
                info_label.pack(fill=tk.X)
                win.after(100, show_preview)

        win.bind('<Escape>', exit_fullscreen)

        # 窗口大小变化时重绘
        def on_resize(event):
            if not _is_fullscreen[0]:
                sel = listbox.curselection()
                if sel:
                    win.after(100, show_preview)
        canvas.bind('<Configure>', on_resize)

        # 默认选中第一张
        if img_files:
            listbox.selection_set(0)
            listbox.activate(0)
            win.after(200, show_preview)

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
    app = ZipImageFilterApp()
    app.run()
