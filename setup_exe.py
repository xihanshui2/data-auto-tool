"""
运行方式：python setup_exe.py

PyInstaller 钩子已自动处理 Streamlit 和 Altair。
这里只指定隐藏导入；无需手动配置 add-data。
"""

import subprocess
import sys
import os
from pathlib import Path

BASE = Path(__file__).parent

# ── 检查 PyInstaller ────────────────────────────────────────────────────────
try:
    import PyInstaller
    print(f"[OK] PyInstaller {PyInstaller.__version__} 已找到。")
except ImportError:
    print("[!] 未找到 PyInstaller，正在安装...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

# ── 检查 pyinstaller-hooks-contrib（Streamlit 钩子需要） ────────────────────
try:
    import _pyinstaller_hooks_contrib
    print(f"[OK] pyinstaller-hooks-contrib 已找到。")
except ImportError:
    print("[!] 正在安装 pyinstaller-hooks-contrib...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller-hooks-contrib"])

# ── 图标 ─────────────────────────────────────────────────────────────────────
icon_path = BASE / "mallard_icon.ico"
icon_arg  = ["--icon", str(icon_path)] if icon_path.exists() else []

# ── 构建 PyInstaller 参数 ────────────────────────────────────────────────────
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onedir",
    "--windowed",
    "--name", "MALLARD",
    *icon_arg,

    # --- 兜底修复（确保包含 Streamlit 元数据） ---
    "--copy-metadata", "streamlit",
    # ----------------------------

    "--add-data", f"mallard.py{os.pathsep}.",
    "--add-data", f"mallard_auto.py{os.pathsep}.",
    "--add-data", f"config{os.pathsep}config",
    "--add-data", f"{os.path.dirname(__import__('streamlit').__file__)}{os.pathsep}streamlit",

    # ── 隐藏导入 ────────────────────────────────────────────────────────────
    "--hidden-import", "streamlit",
    "--hidden-import", "streamlit.web.cli",
    "--hidden-import", "streamlit.runtime.scriptrunner.magic_funcs",
    "--hidden-import", "duckdb",
    "--hidden-import", "pandas",
    "--hidden-import", "plotly",
    "--hidden-import", "plotly.express",
    "--hidden-import", "openpyxl",
    "--hidden-import", "pyarrow",
    "--hidden-import", "xlrd",
    "--hidden-import", "tornado",
    "--hidden-import", "click",
    "--hidden-import", "pydantic",
    "--hidden-import", "pydantic_settings",
    "--hidden-import", "tomli_w",
    "--hidden-import", "email",
    "--hidden-import", "imaplib",

    # ── 入口文件 ─────────────────────────────────────────────────────────────
    "launcher.py",
]

print()
print("=" * 60)
print("MALLARD -- 构建可执行文件")
print("=" * 60)
print(f"  入口文件 : launcher.py")
print(f"  图标     : {'mallard_icon.ico [FOUND]' if icon_path.exists() else '未找到 [WARN]'}")
print(f"  模式     : --onedir")
print("=" * 60)
print()

result = subprocess.run(cmd, cwd=str(BASE))

if result.returncode == 0:
    dist_dir = BASE / "dist" / "MALLARD"
    print()
    print("=" * 60)
    print("[SUCCESS] 构建成功！")
    print(f"[DIR] 输出目录 : {dist_dir}")
    print()
    print("分发方式：")
    print("  1. 将整个 dist/MALLARD/ 文件夹打包为 zip")
    print("  2. 在其他机器上解压，运行 MALLARD.exe")
    print("  3. 浏览器会自动打开 http://localhost:8501")
    print("=" * 60)
else:
    print()
    print("[FAILED] 构建失败。请先尝试运行以下命令：")
    print("   pip install --upgrade pyinstaller pyinstaller-hooks-contrib")
    print("   然后重新运行：python setup_exe.py")
    sys.exit(1)
