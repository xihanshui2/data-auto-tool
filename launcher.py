"""
launcher.py —— .exe 的入口文件
PyInstaller 将此文件作为打包入口。
该脚本在内部运行 Streamlit（不弹出新 CMD 窗口）。
"""

import sys
import os
import threading
import webbrowser
import time
from pathlib import Path
import psutil


def get_base_dir():
    """获取基础目录：打包后使用 .exe 所在文件夹，开发时使用脚本所在文件夹。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def ensure_dirs(base: Path):
    """创建 data/ 文件夹，并确保 mallard.duckdb 可以被创建。"""
    (base / "data").mkdir(exist_ok=True)


def open_browser():
    """Streamlit 就绪后打开浏览器（延迟 3 秒）。"""
    time.sleep(3)
    webbrowser.open("http://localhost:8501")


def main():
    base = get_base_dir()
    ensure_dirs(base)

    # 切换到基础目录，使 mallard.duckdb 和 data/ 相对于 .exe 保持固定位置
    os.chdir(base)

    # 将基础目录加入 sys.path，以便可以导入 mallard.py
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    for proc in psutil.process_iter(['pid']):
        try:
            for conn in proc.net_connections():
                if conn.laddr.port == 8501:
                    proc.kill()
                    break
        except:
            continue

    # 在后台线程中打开浏览器
    threading.Thread(target=open_browser, daemon=True).start()

    # 运行 Streamlit
    from streamlit.web import cli as stcli

    app_path = base / "mallard.py"
    if not app_path.exists():
        app_path = base / "_internal" / "mallard.py"
    app_path = str(app_path)
    sys.argv = [
        "streamlit", "run", app_path,
        "--global.developmentMode=false",  # ← 关键参数：关闭开发模式
        "--server.port=8501",
        "--server.headless=true",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
        "--browser.gatherUsageStats=false",
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
