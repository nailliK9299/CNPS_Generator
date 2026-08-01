# -*- coding: utf-8 -*-
"""
Script đóng gói CNPS Generator cho macOS.
Sử dụng PyInstaller CLI + tự động copy Playwright Chromium.
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

def build_mac():
    print("==========================================")
    print("  BẮT ĐẦU ĐÓNG GÓI CNPS GENERATOR MAC OS  ")
    print("==========================================")
    
    # 1. Chạy PyInstaller CLI
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        "--name=CNPS_Generator",
        "--add-data=data/CNPS template.docx:data",
        "--add-data=data/Bang_Ke_Mau.csv:data",
        "--add-data=data/Bang_Ke_Mau.xlsx:data",
        "--add-data=src/core/Readability.js:src/core",
        "--add-data=src/core/Readability.js:core",
        "--hidden-import=docx",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=numpy",
        "--hidden-import=playwright",
        "--hidden-import=playwright.async_api",
        "--hidden-import=tkinter",
        "--hidden-import=tkinter.ttk",
        "--noconfirm",
        "--clean",
        "src/main.py"
    ]
    
    print("--> Dang chay PyInstaller...")
    subprocess.run(cmd, check=True)
    
    # 2. Copy Playwright Chromium browser
    dist_dir = Path("dist/CNPS_Generator")
    target_chromium_dir = dist_dir / "chromium"
    target_chromium_dir.mkdir(parents=True, exist_ok=True)
    
    possible_caches = [
        Path.home() / "Library/Caches/ms-playwright",
        Path.home() / ".cache/ms-playwright",
    ]
    
    found_chromium = False
    for cache_dir in possible_caches:
        if cache_dir.exists():
            for cdir in cache_dir.glob("chromium-*"):
                if cdir.is_dir():
                    dest = target_chromium_dir / cdir.name
                    print(f"--> Copying Playwright Chromium from {cdir} to {dest}")
                    shutil.copytree(cdir, dest, dirs_exist_ok=True)
                    found_chromium = True
                    
    if not found_chromium:
        print("⚠️ Warning: Playwright Chromium cache directory not found.")
        
    print("==========================================")
    print("✅ HOÀN THÀNH ĐÓNG GÓI MACOS THÀNH CÔNG!")
    print(f"Ứng dụng tại: {dist_dir.resolve()}")
    print("==========================================")

if __name__ == "__main__":
    build_mac()
