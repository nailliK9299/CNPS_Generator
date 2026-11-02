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
        "--hidden-import=openpyxl",
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
    
    # 2. Copy Playwright Chromium browser (bao gồm cả chromium-*, chromium_headless_shell-*, ffmpeg-*)
    dist_dir = Path("dist/CNPS_Generator")
    app_bundle = Path("dist/CNPS_Generator.app")
    target_chromium_dir = dist_dir / "chromium"
    target_chromium_dir.mkdir(parents=True, exist_ok=True)
    
    possible_caches = [
        Path.home() / "Library/Caches/ms-playwright",
        Path.home() / ".cache/ms-playwright",
    ]
    
    found_chromium = False
    for cache_dir in possible_caches:
        if cache_dir.exists():
            for pattern in ("chromium*", "ffmpeg*"):
                for cdir in cache_dir.glob(pattern):
                    if cdir.is_dir():
                        dest = target_chromium_dir / cdir.name
                        print(f"--> Copying Playwright browser {cdir} to {dest} (preserving symlinks)")
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(cdir, dest, symlinks=True)
                        found_chromium = True

                        # Copy vào bên trong CNPS_Generator.app/Contents/Resources/chromium nếu có .app
                        if app_bundle.exists():
                            app_res_chromium = app_bundle / "Contents" / "Resources" / "chromium" / cdir.name
                            app_res_chromium.parent.mkdir(parents=True, exist_ok=True)
                            if app_res_chromium.exists():
                                shutil.rmtree(app_res_chromium)
                            shutil.copytree(cdir, app_res_chromium, symlinks=True)
                        
    if not found_chromium:
        print("⚠️ Warning: Playwright Chromium cache directory not found.")

    # 3. Copy CNPS_Generator.app vào trong dist/CNPS_Generator để người dùng Mac mở trực tiếp .app
    if app_bundle.exists():
        dest_app = dist_dir / "CNPS_Generator.app"
        if dest_app.exists():
            shutil.rmtree(dest_app)
        shutil.copytree(app_bundle, dest_app, symlinks=True)

        # Tạo script 1-click mở ứng dụng lần đầu (tự gỡ chặn Gatekeeper com.apple.quarantine)
        launcher_script = dist_dir / "Mo_Ung_Dung_Mac.command"
        launcher_script.write_text(
            "#!/bin/bash\n"
            "DIR=\"$(cd \"$(dirname \"$0\")\" && pwd)\"\n"
            "xattr -cr \"$DIR\" 2>/dev/null || true\n"
            "chmod -R +x \"$DIR/CNPS_Generator.app/Contents/MacOS\" \"$DIR/CNPS_Generator\" 2>/dev/null || true\n"
            "open \"$DIR/CNPS_Generator.app\"\n",
            encoding="utf-8",
        )
        os.chmod(launcher_script, 0o755)

        # Ký ad-hoc (codesign) để chạy mượt trên chip Apple Silicon (M1/M2/M3/M4)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(dest_app)], check=False)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(dist_dir / "CNPS_Generator")], check=False)
        
    print("==========================================")
    print("✅ HOÀN THÀNH ĐÓNG GÓI MACOS THÀNH CÔNG!")
    print(f"Ứng dụng tại: {dist_dir.resolve()}")
    print("==========================================")

if __name__ == "__main__":
    build_mac()
