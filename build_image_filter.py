"""
build_image_filter.py — 打包压缩包图片筛选工具为独立 exe
用法: python build_image_filter.py
"""

import subprocess
import sys
import os
import shutil

ICON_FILE = os.path.abspath('app.ico')

# ── 清理 ──
for d in ['dist', 'build']:
    if os.path.isdir(d):
        shutil.rmtree(d)
for f in os.listdir('.'):
    if f.endswith('.spec'):
        os.remove(f)

print("打包 zip_image_filter.exe ...")
print()

cmd = [
    sys.executable, '-m', 'PyInstaller',
    'zip_image_filter.py',
    '--onefile',
    '--windowed',
    '--name=zip_image_filter',
    '--hidden-import=multiprocessing',
    '--clean',
    '--noconfirm',
]

if os.path.isfile(ICON_FILE):
    with open(ICON_FILE, 'rb') as f:
        if f.read(4) == b'\x00\x00\x01\x00':
            cmd.append(f'--icon={ICON_FILE}')

result = subprocess.run(cmd)

if result.returncode == 0:
    print()
    print("=" * 50)
    print("  构建成功！")
    output = os.path.abspath('dist/zip_image_filter.exe')
    print(f"  输出: {output}")
    print(f"  大小: {os.path.getsize(output) / 1024 / 1024:.1f} MB")
    print()
    print("  使用方式：双击运行")
    print("=" * 50)
else:
    print()
    print("构建失败")

input("按回车键退出...")
