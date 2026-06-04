"""
generate_icon.py — 生成标准 Windows 图标 app.ico
用法:
  python generate_icon.py                    # 默认图标（纯代码构造，无需 Pillow）
  python generate_icon.py logo.png           # 用自定义图片

输出: app.ico  (16×16 ~ 256×256 多尺寸)
"""

import struct
import os
import sys
from pathlib import Path

# 尝试 Pillow（可选，有则图标更精美）
try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

OUTPUT = 'app.ico'
SIZES = [16, 24, 32, 48, 64, 128, 256]

# ── 颜色 ──
BG = (0, 103, 192)
ACCENT = (0, 153, 255)
WHITE = (255, 255, 255)
LIGHT = (200, 230, 255)
DARK = (0, 70, 150)


def _make_ico_file(images: list) -> bytes:
    """将多个 RGBA 像素矩阵组装为有效的 .ico 二进制数据。"""
    count = len(images)
    header = struct.pack('<HHH', 0, 1, count)  # reserved, type=icon, count

    # 计算各图像数据
    entries = []
    data_blocks = []
    offset = 6 + 16 * count  # 文件头 + 目录项

    for w, h, pixels in images:
        # ── BITMAPINFOHEADER ──
        bih = struct.pack('<IiiHHIIiiII',
            40,             # biSize
            w,              # biWidth
            h * 2,          # biHeight (ICO 要求翻倍)
            1,              # biPlanes
            32,             # biBitCount (BGRA)
            0,              # biCompression (BI_RGB)
            w * h * 4,      # biSizeImage
            0, 0, 0, 0,     # 其他
        )
        # ── AND mask (32bpp 不需要，但结构必须) ──
        and_row_bytes = (w + 31) // 32 * 4
        and_mask = b'\x00' * (and_row_bytes * h)

        img_data = bih + pixels + and_mask
        entries.append(struct.pack('<BBBBHHII',
            w if w < 256 else 0,
            h if h < 256 else 0,
            0, 0, 1, 32, len(img_data), offset,
        ))
        data_blocks.append(img_data)
        offset += len(img_data)

    return header + b''.join(entries) + b''.join(data_blocks)


def _make_pixels_blue(w: int, h: int, pattern: str = 'default') -> bytes:
    """绘制纯几何图形的 RGBA 像素数据，不依赖任何外部库。"""
    pixels = bytearray()
    for y in range(h):
        for x in range(w):
            # 归一化坐标
            nx, ny = x / w, y / h

            # 圆角裁剪
            cx, cy = w / 2, h / 2
            dx = abs(x - cx) / (w / 2)
            dy = abs(y - cy) / (h / 2)
            corner_r = 0.22
            is_corner = False
            if dx > (1 - corner_r) and dy > (1 - corner_r):
                dist = ((dx - (1 - corner_r)) ** 2 + (dy - (1 - corner_r)) ** 2) ** 0.5
                if dist > corner_r * 1.2:
                    is_corner = True

            if is_corner:
                # 透明
                pixels.extend([0, 0, 0, 0])
                continue

            # 蓝色背景
            r, g, b, a = BG[0], BG[1], BG[2], 255

            # 底部装饰条
            if 0.75 < ny < 0.82 and 0.18 < nx < 0.82:
                r, g, b = ACCENT

            # Z 形条纹（左上方）
            if 0.2 < ny < 0.45 and 0.15 < nx < 0.42:
                stripe = (y * 3 + x * 2) // 12 % 3
                if stripe == 0:
                    r, g, b = WHITE
                elif stripe == 1:
                    r, g, b = LIGHT
                else:
                    r, g, b = BG

            # W 形条纹（右上方）
            if 0.2 < ny < 0.45 and 0.58 < nx < 0.85:
                # 画斜线
                lx = (nx - 0.58) / 0.27  # 0~1
                pat1 = abs(lx - 0.5) * 2 < 0.12 or abs(lx - 0.25) < 0.08 or abs(lx - 0.75) < 0.08
                pat2 = (y + x) // 6 % 3 == 0
                if pat1 or pat2:
                    r, g, b = WHITE
                else:
                    r, g, b = BG

            # 箭头
            if 0.42 < ny < 0.58:
                arrow_left = 0.35
                arrow_right = 0.65
                if arrow_left < nx < arrow_right:
                    rel = (nx - arrow_left) / (arrow_right - arrow_left)
                    arrow_h = 0.08 + rel * 0.08
                    if abs(ny - 0.5) < arrow_h:
                        r, g, b = WHITE

            pixels.extend([b, g, r, a])  # BGRA 顺序

    return bytes(pixels)


def make_default_ico() -> bytes:
    """生成纯 Python 构造的默认图标（零外部依赖）。"""
    images = []
    for s in SIZES:
        pixels = _make_pixels_blue(s, s)
        images.append((s, s, pixels))
    return _make_ico_file(images)


def make_from_pillow(src_img_path: str) -> bytes:
    """用 Pillow 加载图片并转为 .ico（图标更好看）。"""
    img = Image.open(src_img_path).convert('RGBA')
    # 居中裁剪为正方形
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    images = []
    for s in SIZES:
        resized = img.resize((s, s), Image.LANCZOS)
        # 提取 BGRA 像素
        pixels = bytearray()
        for y in range(s):
            for x in range(s):
                r, g, b, a = resized.getpixel((x, y))
                pixels.extend([b, g, r, a])
        images.append((s, s, bytes(pixels)))

    return _make_ico_file(images)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None

    if src:
        if not os.path.isfile(src):
            print(f"  ✗ 文件不存在: {src}")
            sys.exit(1)
        if not HAS_PIL:
            print(f"  ⚠ 使用自定义图片需要 Pillow: pip install pillow")
            print(f"  将使用默认图标代替")
            data = make_default_ico()
        else:
            print(f"使用自定义图片: {src}")
            try:
                data = make_from_pillow(src)
            except Exception as e:
                print(f"  ✗ 图片处理失败: {e}")
                print(f"  使用默认图标")
                data = make_default_ico()
    else:
        print("生成默认图标...")
        data = make_default_ico()

    with open(OUTPUT, 'wb') as f:
        f.write(data)

    size_kb = len(data) / 1024
    print(f"  ✓ {OUTPUT}  ({size_kb:.1f} KB, {len(SIZES)} 种尺寸)")
    print()
    print("重新运行 build_exe.py 即可将图标打包到 exe 中")
    print()
    if not src:
        print("想用自己的图标？")
        print(f"  python {Path(__file__).name} 你的图片.png")


if __name__ == '__main__':
    main()
