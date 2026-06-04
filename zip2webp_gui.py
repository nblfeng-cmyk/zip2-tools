#!/usr/bin/env python3
"""
zip2webp_gui.py — Windows 原生风格 ZIP → WebP 批量转换工具
将 JPG/PNG 批量并行转为 WebP（质量80%），打包到指定目录
"""

# ── 高 DPI 支持（4K 显示器自适应，必须在创建窗口前调用） ──
import sys as _sys
if _sys.platform == 'win32':
    import ctypes as _ctypes
    try:
        _ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor V2
    except Exception:
        try:
            _ctypes.windll.shcore.SetProcessDpiAwareness(1)  # System DPI
        except Exception:
            try:
                _ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import queue
import os
import sys
import time
import zipfile
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# ── 转换引擎 ──
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png'}
MAX_WORKERS = max(1, int((os.cpu_count() or 4) * 0.8))
# WEBP_QUALITY 改为实例变量 self.quality，默认 80


# ═══════════════════════════════════════════════
#  子进程转换函数
# ═══════════════════════════════════════════════

def convert_one(args: tuple) -> tuple:
    """子进程：转换单张图片 → WebP，删除原图。"""
    src_str, idx, total, quality = args
    try:
        src = Path(src_str)
        webp = src.with_suffix('.webp')
        with Image.open(src) as img:
            img.save(webp, 'WEBP', quality=quality, method=6)
        src.unlink()
        return (True, src.name, webp.name, idx, None)
    except Exception as e:
        return (False, Path(src_str).name, None, idx, str(e))


# ═══════════════════════════════════════════════
#  主窗口
# ═══════════════════════════════════════════════

class Zip2WebpApp:
    def __init__(self):
        self.root = tk.Tk()

        # ── 自适应 DPI 缩放（4K 屏文字清晰） ──
        try:
            if _sys.platform == 'win32':
                dpi = _ctypes.windll.user32.GetDpiForWindow(self.root.winfo_id())
                self.root.tk.call('tk', 'scaling', dpi / 72)
        except Exception:
            pass

        # ── 窗口图标 ──
        try:
            if getattr(sys, 'frozen', False):
                # PyInstaller 打包后，图标已内嵌在 exe 中
                pass
            elif os.path.isfile('app.ico'):
                self.root.iconbitmap('app.ico')
        except Exception:
            pass

        self.root.title("ZIP → WebP 批量转换")
        # 窗口大小随 DPI 缩放（4K 不拥挤）
        self._dpi_scale = 1.0
        try:
            if _sys.platform == 'win32':
                self._dpi_scale = _ctypes.windll.user32.GetDpiForWindow(self.root.winfo_id()) / 96
        except Exception:
            pass
        bw, bh = int(800 * self._dpi_scale), int(600 * self._dpi_scale)
        self.root.minsize(int(700 * self._dpi_scale), int(560 * self._dpi_scale))
        self.root.geometry(f"{bw}x{bh}+{int(400 * self._dpi_scale)}+{int(200 * self._dpi_scale)}")
        self.root.resizable(True, True)

        # Windows 原生视觉风格
        style = ttk.Style()
        available = style.theme_names()
        for t in ('vista', 'winnative', 'xpnative', 'clam'):
            if t in available:
                style.theme_use(t)
                break

        # Treeview 样式随 DPI 缩放
        _rh = max(20, int(22 * self._dpi_scale))
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=_rh)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        # 状态变量
        self.file_list: list[Path] = []
        self.running = False
        self.msg_queue = queue.Queue()
        self.output_dir = Path(os.path.expanduser('~/Desktop'))
        self.quality = 80  # 默认压缩质量
        self.rename_files = False

        self._build_menu()
        self._build_ui()
        self.root.after(100, self._poll_queue)

    # ── 菜单栏 ──

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="添加文件...", command=self._add_files, accelerator="Ctrl+O")
        file_menu.add_command(label="清空列表", command=self._clear_list)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menubar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.bind("<Control-o>", lambda e: self._add_files())

    # ── UI 布局 ──

    def _build_ui(self):
        root = self.root

        # 主容器
        main = ttk.Frame(root, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ── 顶部标题区 ──
        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(
            header, text="ZIP → WebP 批量转换",
            font=("Segoe UI", 14, "bold"),
        ).pack(side=tk.LEFT)

        ttk.Label(
            header,
            text="JPG/PNG → WebP → 输出到指定目录",
            font=("Segoe UI", 9),
            foreground="#555",
        ).pack(side=tk.LEFT, padx=(12, 0))

        # ── 文件列表（Treeview，更多列信息） ──
        list_frame = ttk.LabelFrame(main, text="文件列表", padding=4)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        # Treeview
        columns = ("name", "size", "status")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, show="headings",
            selectmode="extended", height=8,
        )
        self.tree.heading("name", text="文件名")
        self.tree.heading("size", text="大小", anchor=tk.E)
        self.tree.heading("status", text="状态", anchor=tk.CENTER)
        _s = self._dpi_scale
        self.tree.column("name", width=int(400*_s), minwidth=int(200*_s), stretch=True)
        self.tree.column("size", width=int(100*_s), minwidth=int(80*_s), stretch=False, anchor=tk.E)
        self.tree.column("status", width=int(120*_s), minwidth=int(80*_s), stretch=False, anchor=tk.CENTER)

        # 滚动条
        vbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # 拖拽提示覆盖层（轻量文字，放在列表下方）
        hint_text = "点击「添加文件」按钮添加 ZIP 压缩包"
        self.drop_hint = ttk.Label(
            main,
            text=hint_text,
            foreground="#888",
            font=("Segoe UI", 9),
        )
        self.drop_hint.pack()

        # ── 压缩质量设置 ──
        qual_frame = ttk.Frame(main)
        qual_frame.pack(fill=tk.X, pady=1)

        ttk.Label(qual_frame, text="压缩质量:").pack(side=tk.LEFT)
        self.quality_var = tk.IntVar(value=80)
        self.quality_combo = ttk.Combobox(
            qual_frame,
            textvariable=self.quality_var,
            values=[str(v) for v in range(50, 105, 5)],
            width=6, state='readonly',
        )
        self.quality_combo.pack(side=tk.LEFT, padx=(4, 2))
        ttk.Label(qual_frame, text="%   (值越大画质越好，文件越大)", foreground="#888").pack(side=tk.LEFT)

        # ── 自动重命名选项 ──
        opt_frame = ttk.Frame(main)
        opt_frame.pack(fill=tk.X, pady=1)

        self.rename_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opt_frame, text="转换为序号文件名 (001.webp, 002.webp, ...)",
            variable=self.rename_var,
        ).pack(side=tk.LEFT)

        # ── 输出目录 ──
        dir_frame = ttk.Frame(main)
        dir_frame.pack(fill=tk.X, pady=1)

        ttk.Label(dir_frame, text="输出目录:").pack(side=tk.LEFT)
        self.dir_label = ttk.Label(dir_frame, text="", foreground="#333")
        self.dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ttk.Button(dir_frame, text="浏览...", command=self._select_output_dir, width=8).pack(side=tk.RIGHT)
        self._update_dir_label()

        # ── 操作按钮栏 ──
        btn_bar = ttk.Frame(main)
        btn_bar.pack(fill=tk.X, pady=4)

        ttk.Button(btn_bar, text="添加文件", command=self._add_files, width=12).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(btn_bar, text="移除选中", command=self._remove_selected, width=12).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_bar, text="清空列表", command=self._clear_list, width=10).pack(side=tk.LEFT, padx=4)

        # 右侧文件计数
        self.count_label = ttk.Label(btn_bar, text="共 0 个文件", foreground="#555")
        self.count_label.pack(side=tk.RIGHT, padx=4)

        # ── 进度条 ──
        prog_frame = ttk.Frame(main)
        prog_frame.pack(fill=tk.X, pady=2)

        self.progress = ttk.Progressbar(prog_frame, mode='determinate')
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.progress_text = ttk.Label(prog_frame, text="就绪", width=24, anchor=tk.E)
        self.progress_text.pack(side=tk.RIGHT, padx=(8, 0))

        # ── 日志输出 ──
        log_frame = ttk.LabelFrame(main, text="处理日志", padding=2)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 4))

        self.log = scrolledtext.ScrolledText(
            log_frame,
            font=("Consolas", 9),
            wrap=tk.WORD,
            state=tk.DISABLED,
            relief=tk.SUNKEN,
            borderwidth=1,
            height=8,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        # ── 底部操作栏 ──
        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X)

        self.start_btn = ttk.Button(
            bottom, text="开始转换", command=self._start_convert, width=18,
        )
        self.start_btn.pack(side=tk.RIGHT)

    # ── 按钮回调 ──

    def _select_output_dir(self):
        """选择输出目录。"""
        d = filedialog.askdirectory(title="选择输出目录", initialdir=str(self.output_dir))
        if d:
            self.output_dir = Path(d)
            self._update_dir_label()

    def _update_dir_label(self):
        """更新输出目录显示文字。"""
        text = str(self.output_dir)
        # 如果路径太长就缩写中间部分
        if len(text) > 60:
            text = text[:25] + '...' + text[-32:]
        self.dir_label.config(text=text)

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="选择 ZIP 文件",
            filetypes=[("ZIP 压缩包", "*.zip"), ("所有文件", "*.*")],
        )
        added = 0
        for f in files:
            p = Path(f)
            if p not in self.file_list:
                self.file_list.append(p)
                size_str = self._format_size(p.stat().st_size)
                self.tree.insert("", tk.END, values=(p.name, size_str, "待处理"))
                added += 1
        if added:
            self._update_count()

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        indices = [self.tree.index(i) for i in sel]
        for idx in sorted(indices, reverse=True):
            self.tree.delete(self.tree.get_children()[idx])
            del self.file_list[idx]
        self._update_count()

    def _clear_list(self):
        self.file_list.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._update_count()

    def _update_count(self):
        n = len(self.file_list)
        self.count_label.config(text=f"共 {n} 个文件")

    # ── 工具方法 ──

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        elif size < 1024 ** 2:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 ** 3:
            return f"{size / 1024 ** 2:.1f} MB"
        else:
            return f"{size / 1024 ** 3:.2f} GB"

    # ── 日志与进度 ──

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, f"[{ts}] {msg}\n")
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _set_progress(self, value: float, text: str = ""):
        self.progress['value'] = value
        self.progress_text.config(text=text if text else f"{value:.0f}%")

    # ── 转换 ──

    def _start_convert(self):
        if self.running:
            return
        if not self.file_list:
            self._log("请先添加要处理的 ZIP 文件")
            return
        if not HAS_PIL:
            messagebox.showerror("缺少依赖", "请先安装 Pillow 库：pip install pillow")
            return

        self.running = True
        self.start_btn.config(text="处理中...", state=tk.DISABLED)
        self._set_progress(0, "准备中...")

        # 重置所有条目状态为 "待处理"
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, 'values'))
            vals[2] = "待处理"
            self.tree.item(item, values=vals)

        self.quality = self.quality_var.get()
        self.rename_files = self.rename_var.get()
        self._log(f"开始处理 {len(self.file_list)} 个文件，质量 {self.quality}%，并行 {MAX_WORKERS} 核")
        threading.Thread(target=self._convert_all, daemon=True).start()

    def _convert_all(self):
        total = len(self.file_list)
        results = []

        for i, zip_path in enumerate(self.file_list):
            pct = (i / total) * 100
            self.msg_queue.put(("progress", pct, f"({i+1}/{total}) {zip_path.name}"))
            self.msg_queue.put(("log", f"\n{'='*50}"))
            self.msg_queue.put(("log", f"({i+1}/{total}) 处理: {zip_path.name}"))

            ok = self._process_single_zip(zip_path, i + 1, total)
            results.append((i, zip_path.name, ok))

        # 最终更新
        self.msg_queue.put(("progress", 100, "处理完成"))
        success = sum(1 for _, _, ok in results if ok)
        failed = total - success
        self.msg_queue.put(("log", f"\n{'='*50}"))
        self.msg_queue.put(("log", f"全部完成: 成功 {success}, 失败 {failed}"))

        # 更新列表中每个文件的状态
        for idx, name, ok in results:
            self.msg_queue.put(("item_status", idx, "完成 ✔" if ok else "失败 ✘"))

        self.msg_queue.put(("done",))

    def _process_single_zip(self, zip_path: Path, idx: int, total: int) -> bool:
        if not zip_path.exists():
            self.msg_queue.put(("log", f"  ✗ 文件不存在"))
            return False

        out_path = self.output_dir / zip_path.name
        if out_path == zip_path:
            self.msg_queue.put(("log", f"  ✗ 输出目录与源文件相同，请选择其他目录"))
            return False
        if out_path.exists():
            self.msg_queue.put(("log", f"  ✗ 已存在: {out_path.name}"))
            return False

        start_t = time.time()

        with tempfile.TemporaryDirectory(prefix='zip2webp_') as tmpdir:
            tmp = Path(tmpdir)

            self.msg_queue.put(("log", f"  解压中..."))
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(tmp)
            except zipfile.BadZipFile:
                self.msg_queue.put(("log", f"  ✗ 损坏的压缩包"))
                return False

            images = [p for p in tmp.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

            if not images:
                self.msg_queue.put(("log", f"  – 未找到 JPG/PNG 图片"))
                shutil.copy2(zip_path, out_path)
                self.msg_queue.put(("log", f"  已复制: {out_path.name}（无转换）"))
                return True

            img_total = len(images)
            self.msg_queue.put(("log", f"  图片: {img_total} 张 | 质量 {self.quality}% | 并行 {MAX_WORKERS} 核"))

            converted = 0
            failed = 0
            tasks = [(str(p), i, img_total, self.quality) for i, p in enumerate(images, 1)]

            with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = {pool.submit(convert_one, t): t[1] for t in tasks}
                for future in as_completed(futures):
                    ok, fname, wname, img_idx, err = future.result()
                    if ok:
                        converted += 1
                    else:
                        failed += 1
                        self.msg_queue.put(("log", f"    跳过: {fname} → {err}"))

                    done = converted + failed
                    if done % 10 == 0 or done == img_total:
                        pct = done / img_total * 100
                        self.msg_queue.put((
                            "progress",
                            (idx - 1) / total * 100 + pct / total,
                            f"({idx}/{total}) {zip_path.name}  {done}/{img_total}",
                        ))

            elapsed = time.time() - start_t
            self.msg_queue.put(("log", f"  转换: ✓{converted}  ✗{failed}  ({elapsed:.1f}秒)"))

            if converted == 0 and failed > 0:
                self.msg_queue.put(("log", f"  ✗ 所有图片转换失败"))
                return False

            # ── 可选：重命名为序号 ──
            if self.rename_files:
                webp_files = sorted(tmp.rglob('*.webp'))
                if webp_files:
                    self.msg_queue.put(("log", f"  重命名: {len(webp_files)} 个文件 → 001 ~ {len(webp_files):03d}"))
                    for i, fp in enumerate(webp_files, 1):
                        new_name = f"{i:03d}.webp"
                        new_path = tmp / new_name
                        # 如果目标文件已存在，加上随机后缀避免冲突
                        if new_path.exists():
                            import random
                            new_path = tmp / f"{i:03d}_{random.randint(100,999)}.webp"
                        fp.rename(new_path)

            self.msg_queue.put(("log", f"  打包中..."))
            try:
                with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f in tmp.rglob('*'):
                        if f.is_file():
                            zf.write(f, f.relative_to(tmp))
                total_elapsed = time.time() - start_t
                self.msg_queue.put(("log", f"  ✓ 生成: {out_path.name}  ({total_elapsed:.1f}秒)"))
                return True
            except Exception as e:
                self.msg_queue.put(("log", f"  ✗ 打包失败: {e}"))
                return False

    # ── 消息轮询 ──

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    self._set_progress(msg[1], msg[2])
                elif kind == "item_status":
                    idx, status = msg[1], msg[2]
                    children = self.tree.get_children()
                    if idx < len(children):
                        vals = list(self.tree.item(children[idx], 'values'))
                        vals[2] = status
                        self.tree.item(children[idx], values=vals)
                elif kind == "done":
                    self.running = False
                    self.start_btn.config(text="开始转换", state=tk.NORMAL)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_queue)

    # ── 关于对话框 ──

    def _show_about(self):
        messagebox.showinfo(
            "关于 ZIP → WebP 批量转换",
            "ZIP → WebP 批量转换工具  v1.0\n\n"
            "将 ZIP 压缩包内的 JPG/PNG 图片自动转换为 WebP 格式，\n"
            "保留原始目录结构，打包到指定目录。\n\n"
            "核心引擎: Pillow | 多核并行: ProcessPoolExecutor\n"
            f"并行核心数: {MAX_WORKERS} | 压缩质量: 50%~100% 可选",
        )

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()

    if not HAS_PIL:
        messagebox.showerror("缺少依赖", "请安装 Pillow 库：\npip install pillow")
        sys.exit(1)

    app = Zip2WebpApp()
    app.run()
