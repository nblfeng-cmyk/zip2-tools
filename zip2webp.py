#!/usr/bin/env python3
"""
zip2webp.py — 将 ZIP 内的 JPG/PNG 批量并行转为 WebP，打包为新 ZIP
用法：把 .zip 文件拖到 .exe 上（或 python zip2webp.py *.zip）
"""

import zipfile
import tempfile
import os
import sys
import shutil
import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

try:
    from PIL import Image
except ImportError:
    print("错误: 请先安装 Pillow 库:  pip install Pillow")
    input("\n按回车键退出...")
    sys.exit(1)

SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png'}
WEBP_QUALITY = 80
MAX_WORKERS = max(1, int((os.cpu_count() or 4) * 0.8))


def convert_one(args: tuple) -> tuple:
    """在子进程中执行：转换单张图片 → WebP，删除原图。"""
    src_str, idx, total = args
    try:
        src = Path(src_str)
        webp = src.with_suffix('.webp')
        with Image.open(src) as img:
            # 保留原始尺寸和模式（RGBA 透明通道自动保留）
            img.save(webp, 'WEBP', quality=WEBP_QUALITY, method=6)
        src.unlink()  # 删除原图
        return (True, src.name, webp.name, idx, None)
    except Exception as e:
        return (False, Path(src_str).name, None, idx, str(e))


def process_zip(zip_path: Path) -> bool:
    """处理单个 .zip 文件。"""
    print(f"\n{'='*55}")
    print(f"  处理: {zip_path.name}")

    if not zip_path.exists():
        print(f"  ✗ 文件不存在")
        return False

    # ── 输出路径 ──
    out_name = zip_path.stem + '_webp.zip'
    out_path = zip_path.with_name(out_name)
    if out_path.exists():
        print(f"  ✗ 已存在: {out_name}，先删除或在重命名后再试")
        return False

    start = time.time()

    # ── 解压到临时目录 ──
    with tempfile.TemporaryDirectory(prefix='zip2webp_') as tmpdir:
        tmp = Path(tmpdir)
        print(f"  解压中...")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile:
            print(f"  ✗ 损坏的压缩包")
            return False

        # ── 扫描图片（Windows 大小写不敏感，一次扫描即可） ──
        images = [p for p in tmp.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

        if not images:
            print(f"  – 未找到 JPG/PNG 图片，跳过")
            shutil.copy2(zip_path, out_path)
            print(f"  复制原文件为: {out_name}（无变化）")
            return True  # still "succeeded", just nothing to convert

        total = len(images)
        print(f"  图片: {total} 张 | 并行数: {MAX_WORKERS} 核")

        # ── 并行转换 ──
        converted = 0
        failed = 0
        tasks = [(str(p), i, total) for i, p in enumerate(images, 1)]

        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(convert_one, t): t[1] for t in tasks}

            for future in as_completed(futures):
                ok, fname, wname, idx, err = future.result()
                if ok:
                    converted += 1
                    if converted == 1 or converted % 25 == 0 or converted == total - failed:
                        print(f"    进度: {converted + failed}/{total}  (✓{converted}  ✗{failed})")
                else:
                    failed += 1
                    print(f"    跳过: {fname} → {err}")

        elapsed = time.time() - start
        print(f"  转换完成: ✓{converted} 张成功, ✗{failed} 张跳过  ({elapsed:.1f}秒)")

        if converted == 0 and failed > 0:
            print(f"  ✗ 所有图片转换失败，跳过打包")
            return False

        # ── 打包为 _webp.zip ──
        print(f"  打包中...")
        try:
            with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for f in tmp.rglob('*'):
                    if f.is_file():
                        zf.write(f, f.relative_to(tmp))
            elapsed_total = time.time() - start
            print(f"  ✓ 生成: {out_name}  ({elapsed_total:.1f}秒)")
            return True
        except Exception as e:
            print(f"  ✗ 打包失败: {e}")
            return False


def main():
    if len(sys.argv) < 2:
        print("=" * 55)
        print("  ZIP → WebP 批量转换工具")
        print("=" * 55)
        print()
        print("用法：")
        print("  把 .zip 文件拖拽到这个程序图标上")
        print("  或在命令行：zip2webp.exe 文件1.zip [文件2.zip ...]")
        print()
        print("流程：")
        print("  解压 → 扫描 JPG/PNG → 并行转 WebP (80%) → 打包为 原名_webp.zip")
        print("  原文件保留不变")
        print()
        input("按回车键退出...")
        return

    zip_files = [Path(a) for a in sys.argv[1:] if a.lower().endswith('.zip')]
    if not zip_files:
        print("没有找到 .zip 文件（拖拽的文件必须后缀是 .zip）")
        input("按回车键退出...")
        return

    ok = fail = 0
    for zf in zip_files:
        if process_zip(zf):
            ok += 1
        else:
            fail += 1

    print(f"\n{'='*55}")
    print(f"全部完成: 成功 {ok}, 失败 {fail}")
    print(f"{'='*55}")
    input("\n按回车键退出...")


if __name__ == '__main__':
    # Windows 多进程入口保护
    main()
