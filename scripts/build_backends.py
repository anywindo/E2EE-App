#!/usr/bin/env python3
"""
Cross-platform build script for packaging app.py and chat_demo.py into standalone binaries
suitable for bundling inside an Electron application package.
"""

import os
import sys
import shutil
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST_DIR = os.path.join(PROJECT_ROOT, "build", "bin")
WORK_DIR = os.path.join(PROJECT_ROOT, "build", "pyinstaller_temp")

def get_pyinstaller_cmd():
    is_win = sys.platform == "win32"
    venv_pyinstaller = os.path.join(PROJECT_ROOT, "venv", "Scripts" if is_win else "bin", "pyinstaller.exe" if is_win else "pyinstaller")
    venv_python = os.path.join(PROJECT_ROOT, "venv", "Scripts" if is_win else "bin", "python.exe" if is_win else "python")

    if os.path.exists(venv_pyinstaller):
        return [venv_pyinstaller]
    
    if os.path.exists(venv_python):
        return [venv_python, "-m", "PyInstaller"]

    found = shutil.which("pyinstaller")
    if found:
        return [found]
    
    return [sys.executable, "-m", "PyInstaller"]

def safe_remove_dir(target_path):
    if not os.path.exists(target_path):
        return
    for root, dirs, files in os.walk(target_path, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except Exception:
                pass
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except Exception:
                pass
    try:
        shutil.rmtree(target_path, ignore_errors=True)
    except Exception:
        pass

def build_binary(script_name, target_name):
    print(f"\n==========================================")
    print(f"  Building {target_name} from {script_name}")
    print(f"==========================================")

    target_dir = os.path.join(DIST_DIR, target_name)
    safe_remove_dir(target_dir)

    script_path = os.path.join(PROJECT_ROOT, script_name)
    pyinstaller = get_pyinstaller_cmd()

    cmd = [
        *pyinstaller,
        "--onedir",
        "--clean",
        "--noconfirm",
        "--name", target_name,
        "--distpath", DIST_DIR,
        "--workpath", WORK_DIR,
        "--collect-all", "gradio",
        "--collect-all", "safehttpx",
        "--collect-all", "groovy",
        "--collect-all", "plotly",
        "--collect-all", "pandas",
        "--copy-metadata", "gradio",
        "--copy-metadata", "safehttpx",
        "--copy-metadata", "groovy",
        "--copy-metadata", "tqdm",
        "--copy-metadata", "requests",
        "--copy-metadata", "packaging",
        "--exclude-module", "tkinter",
        "--exclude-module", "tcl",
        "--exclude-module", "pytest",
        "--exclude-module", "IPython",
        "--exclude-module", "pandas.tests",
        "--exclude-module", "numpy.tests",
        "--exclude-module", "matplotlib.tests",
        "--exclude-module", "PIL.tests",
        "--exclude-module", "pydoc",
        script_path
    ]

    print(f"Running: {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

def main():
    os.makedirs(DIST_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    print(f"Project root: {PROJECT_ROOT}")
    print(f"Binaries target: {DIST_DIR}")

    build_binary("app.py", "app_backend")
    build_binary("chat_demo.py", "chat_backend")

    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    print("\n[SUCCESS] Python backends built successfully into build/bin!")

if __name__ == "__main__":
    main()
