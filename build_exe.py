"""
build_exe.py — 生成图标 + 打包 zip2webp 图形界面版
用法: python build_exe.py
"""

import subprocess
import sys
import os
import shutil

ICON_FILE = os.path.abspath('app.ico')

# ── 第一步：生成图标 ──
print("=" * 50)
print("  第一步：生成应用图标")
print("=" * 50)
icon_ok = False
if os.path.isfile(ICON_FILE):
    # 验证是否为有效的 .ico 文件（头部应为 00 00 01 00）
    with open(ICON_FILE, 'rb') as _f:
        _header = _f.read(4)
    if _header == b'\x00\x00\x01\x00':
        icon_ok = True
        print(f"  ✓ 图标已存在且格式正确: {ICON_FILE}")
    else:
        print(f"  ⚠ 图标格式异常，重新生成")

if not icon_ok:
    icon_result = subprocess.run([sys.executable, 'generate_icon.py'])
    if icon_result.returncode == 0 and os.path.isfile(ICON_FILE):
        with open(ICON_FILE, 'rb') as _f:
            if _f.read(4) == b'\x00\x00\x01\x00':
                icon_ok = True
                print(f"  ✓ 图标生成成功")
    if not icon_ok:
        print("  ⚠ 图标生成失败，将使用 PyInstaller 默认图标")
        ICON_FILE = None

print()

# ── 第二步：清理旧构建 ──
for d in ['dist', 'build']:
    if os.path.isdir(d):
        shutil.rmtree(d)
for f in os.listdir('.'):
    if f.endswith('.spec'):
        os.remove(f)

print("=" * 50)
print("  第二步：打包 zip2webp.exe")
print("=" * 50)

# ── 第三步：PyInstaller 构建 ──
cmd = [
    sys.executable, '-m', 'PyInstaller',
    'zip2webp_gui.py',
    '--onefile',
    '--windowed',
    '--name=zip2webp',
    '--hidden-import=PIL',
    '--hidden-import=PIL._webp',
    '--hidden-import=multiprocessing',
    '--collect-submodules=concurrent',
    '--clean',
    '--noconfirm',
]

if ICON_FILE:
    cmd.append(f'--icon={ICON_FILE}')

result = subprocess.run(cmd)

if result.returncode == 0:
    print()
    print("=" * 50)
    print("  构建成功！")
    output = os.path.abspath('dist/zip2webp.exe')
    print(f"  输出: {output}")
    print(f"  大小: {os.path.getsize(output) / 1024 / 1024:.1f} MB")
    print()
    print("  使用方式：双击 zip2webp.exe 运行图形界面")
    print("=" * 50)
else:
    print()
    print("构建失败，请检查上面的错误信息")
    print("常见原因：未安装 PyInstaller → pip install pyinstaller")

input("按回车键退出...")
