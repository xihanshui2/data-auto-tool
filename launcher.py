"""
launcher.py —— .exe 的入口文件
PyInstaller 将此文件作为打包入口。
该脚本在内部运行 Streamlit（不弹出新 CMD 窗口）。
打包后的程序默认启动 mallard_auto.py（自动化处理模式）。
"""

import sys
import os
import threading
import webbrowser
import time
from pathlib import Path
import psutil


PORT = 8502
APP_FILE = "mallard_auto.py"


def get_base_dir():
    """获取基础目录：打包后使用 .exe 所在文件夹，开发时使用脚本所在文件夹。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def ensure_dirs(base: Path):
    """创建 data/ 文件夹，并确保数据库文件可以被创建。"""
    (base / "data").mkdir(exist_ok=True)


def open_browser(port: int = PORT):
    """Streamlit 就绪后打开浏览器（延迟 3 秒）。"""
    time.sleep(3)
    webbrowser.open(f"http://localhost:{port}")


def main():
    base = get_base_dir()
    ensure_dirs(base)

    # 切换到基础目录，使数据库和 data/ 相对于 .exe 保持固定位置
    os.chdir(base)

    # 将基础目录加入 sys.path
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    # 结束占用端口的现有进程
    for proc in psutil.process_iter(['pid']):
        try:
            for conn in proc.net_connections():
                if conn.laddr.port == PORT:
                    proc.kill()
                    break
        except Exception:
            continue

    # 在后台线程中打开浏览器
    threading.Thread(target=lambda: open_browser(PORT), daemon=True).start()

    # 运行 Streamlit
    from streamlit.web import cli as stcli

    app_path = base / APP_FILE
    if not app_path.exists():
        app_path = base / "_internal" / APP_FILE
    app_path = str(app_path)
    sys.argv = [
        "streamlit", "run", app_path,
        "--global.developmentMode=false",
        f"--server.port={PORT}",
        "--server.headless=true",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
        "--browser.gatherUsageStats=false",
    ]
    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
