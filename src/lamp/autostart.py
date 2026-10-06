"""Windows 当前用户登录自启动，无需管理员权限。"""

import os
import subprocess
import sys

from .bluetooth import require_windows
from .storage import data_dir

KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "PersonalLamp"


def enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            winreg.QueryValueEx(key, NAME)
        return True
    except FileNotFoundError:
        return False


def set_enabled(value: bool) -> None:
    require_windows()
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as key:
        if value:
            executable = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.isfile(executable):
                executable = sys.executable
            # 下次登录时仍使用设置自启动时的用户数据目录。
            launcher = data_dir() / "autostart.py"
            launcher.parent.mkdir(parents=True, exist_ok=True)
            launcher.write_text(
                "import os\n"
                f"os.environ['LAMP_HOME'] = {str(data_dir())!r}\n"
                "from lamp.cli import main\n"
                "raise SystemExit(main(['_autostart']))\n",
                encoding="utf-8",
            )
            command = subprocess.list2cmdline([executable, str(launcher)])
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
