# ZIP & WebP 工具集

一套 Windows 原生风格的 Python 工具，用于批量处理 ZIP 压缩包中的图片。

---

## 📦 项目一览

| 工具 | 文件 | 用途 |
|---|---|---|
| **ZIP → WebP 转换** | `zip2webp_gui.py` | 将 ZIP 内 JPG/PNG 批量转为 WebP，保持目录结构，输出到指定目录 |
| **压缩包图片筛选** | `zip_image_filter.py` | 按图片数量和文件大小筛选 ZIP，支持提取/剪切/删除/预览 |
| **图标生成器** | `generate_icon.py` | 生成标准 Windows .ico 图标文件 |

---

## 1. ZIP → WebP 批量转换 (`zip2webp`)

### 功能

- 将 ZIP 压缩包内的 `.jpg` / `.jpeg` / `.png` 图片自动转换为 `.webp` 格式
- 保留原始目录结构，打包为同名的 ZIP 文件
- 支持指定输出目录（默认桌面）
- **多核并行转换**（占用 80% CPU 核心，不拖垮前台）
- **压缩质量可选**（50%~100%，每 5% 一档，默认 80%）
- 支持**重命名为序号**（001.webp, 002.webp, ...）
- 4K 高 DPI 自适应（窗口大小和字体随系统缩放比例自动调整）

### 操作方式

```
1. 添加 .zip 文件到列表
2. 选压缩质量（可选）
3. 勾选「转换为序号文件名」（可选）
4. 选输出目录
5. 点「开始转换」
```

### 技术要点

| 模块 | 说明 |
|---|---|
| `Pillow` | 图片解码 + WebP 编码 |
| `concurrent.futures.ProcessPoolExecutor` | 多进程并行，80% CPU 核心 |
| `tkinter.ttk` | Windows Vista 原生主题 |
| `zipfile` | 解压 + 重新打包 |

---

## 2. 压缩包图片数量筛选 (`zip_image_filter`)

### 功能

- 快速扫描 ZIP 文件，统计内部图片数量（仅读文件列表，不解压）
- 按**图片数量 ≥ N** 和**文件大小范围**筛选
- 支持**批量操作**：提取 / 剪切 / 删除
- **不解压缩模式**：仅复制/移动 ZIP 本身，不解开内容
- **图片预览**：双击结果 → 弹出预览窗口，直接从 ZIP 内读取显示
- 预览支持：**滚轮翻页**、**方向键切换**、**鼠标中键全屏**
- 扫描可随时**停止**
- 支持**递归/非递归**扫描子目录
- 4K 高 DPI 自适应

### 操作流程

```
1. 添加文件或文件夹（可勾选是否包含子目录）
2. 点击「扫描图片数」统计每个 ZIP 内的图片数量
3. 设置筛选条件（图片数 ≥ N，文件大小范围）
4. 点击「开始筛选」
5. 在结果列表中勾选需要操作的文件
6. 选择操作：
   - 提取：解压到目标目录（或勾选「不解压缩」→ 仅复制）
   - 剪切：解压后删除原文件（或勾选「不解压缩」→ 仅移动）
   - 删除：永久删除选中的 ZIP
7. 双击任意结果行 → 预览内部图片
```

### 扫描机制

仅读取 ZIP 文件的 `namelist()`，不解压任何内容，因此扫描速度极快。

支持的图片格式：

`.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` `.tiff` `.tif` `.svg`

---

## 3. 图标生成器 (`generate_icon`)

用纯 Python 构造标准 `.ico` 文件。

```
python generate_icon.py                   # 生成默认图标（蓝色背景 + Z→W 箭头）
python generate_icon.py 你的图片.png      # 用自定义图片生成图标
```

输出：`app.ico`，包含 16×16 到 256×256 共 7 种尺寸。

---

## 🔧 构建独立 .exe

每个工具都有对应的构建脚本，生成单文件 exe（无需 Python 环境）。

```powershell
# ZIP → WebP 转换
python build_exe.py
# 输出: dist\zip2webp.exe

# 压缩包图片筛选
python build_image_filter.py
# 输出: dist\zip_image_filter.exe
```

构建依赖：`pyinstaller`（自动安装）

```powershell
pip install pyinstaller
```

### 注意事项

- exe 打包后**不需要**安装 Python
- 依赖已全部打包进 exe（含 Pillow、tkinter）
- 可能需安装 [VC++ 运行库](https://aka.ms/vs/17/release/vc_redist.x64.exe)（Windows 10/11 通常预装）

---

## 🖥️ 系统要求

- Windows 10 / 11（64 位）
- 若运行 Python 源码：Python 3.10+，`pip install pillow pyinstaller`
- 4K 显示器可正常显示（DPI 自适应）

---

## 📁 文件清单

| 文件 | 说明 |
|---|---|
| `zip2webp_gui.py` | ZIP → WebP 图形界面主程序 |
| `zip2webp.py` | ZIP → WebP 命令行版（供参考） |
| `zip2webp.bat` | 命令行版批处理包装 |
| `zip_image_filter.py` | 压缩包图片筛选工具 |
| `generate_icon.py` | 图标生成器 |
| `build_exe.py` | ZIP → WebP 构建脚本 |
| `build_image_filter.py` | 图片筛选工具构建脚本 |
| `app.ico` | 生成的图标文件 |

---

## ⚠️ 说明

- ZIP → WebP 转换**不会修改原文件**，输出到指定目录
- 筛选工具的「删除」为**永久删除**，不会进回收站，操作前会有确认弹窗
- 预览功能需要 Pillow 库（已打包在 exe 中）
