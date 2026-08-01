#!/bin/bash
# Script đóng gói CNPS Generator trên macOS

echo "=========================================="
echo "    BẮT ĐẦU ĐÓNG GÓI CNPS GENERATOR MAC   "
echo "=========================================="

# 1. Cài đặt Python dependencies
echo "--> Đang cài đặt thư viện Python..."
pip install -r requirements.txt
pip install pyinstaller

# 2. Cài đặt trình duyệt Playwright macOS
echo "--> Đang cài đặt Playwright Chromium..."
playwright install chromium

# 3. Chạy PyInstaller
echo "--> Đang biên dịch ứng dụng .app bằng PyInstaller..."
pyinstaller build_mac.spec --noconfirm

# 4. Kiểm tra kết quả
if [ -d "dist/CNPS_Generator.app" ]; then
    echo "=========================================="
    echo "✅ ĐÓNG GÓI MÁY MAC THÀNH CÔNG!"
    echo "Ứng dụng: dist/CNPS_Generator.app"
    echo "=========================================="
    
    # Nén thành file zip để dễ chia sẻ
    cd dist
    zip -r CNPS_Generator_macOS.zip CNPS_Generator.app
    echo "File Zip sẵn sàng chia sẻ: dist/CNPS_Generator_macOS.zip"
else
    echo "❌ LỖI: Không tìm thấy dist/CNPS_Generator.app"
fi
