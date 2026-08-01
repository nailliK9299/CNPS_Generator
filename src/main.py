# -*- coding: utf-8 -*-
"""
CNPS Generator — Chứng Nhận Phát Sóng
Entry point chính của ứng dụng.

Chạy: python src/main.py
"""
import os
import sys

# Đảm bảo src/ nằm trong Python path
src_dir = os.path.dirname(os.path.abspath(__file__))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# Set Playwright browsers path (cho đóng gói exe)
from config import setup_playwright_browsers
setup_playwright_browsers()


def main():
    """Khởi chạy ứng dụng."""
    from gui.main_window import CNPSApp
    
    app = CNPSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
