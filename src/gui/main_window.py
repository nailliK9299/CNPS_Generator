# -*- coding: utf-8 -*-
"""
Giao diện chính của ứng dụng CNPS Generator.
Tkinter GUI dạng form nhập liệu, hỗ trợ nhập nhiều khoản mục.
"""
import os
import csv
import shutil
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from pathlib import Path

import sys
# Thêm thư mục cha vào path để import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    APP_TITLE, APP_VERSION, DEFAULT_OUTPUT_DIR, TEMPLATE_PATH,
    FB_STORAGE_STATE_PATH,
)
from utils.helpers import generate_output_filename, open_folder_in_explorer
from utils.table_parser import parse_csv_or_excel_file, parse_clipboard_text
from core.docx_generator import generate_cnps
from core.screenshot import capture_screenshots, SessionExpiredError


class CNPSApp(tk.Tk):
    """Cửa sổ chính của ứng dụng CNPS Generator."""
    
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("920x780")
        self.minsize(850, 700)
        self.configure(bg="#f5f5f5")
        
        # Danh sách khoản mục đã thêm
        self._items: list[dict] = []
        # Thư mục lưu output
        self._output_dir = tk.StringVar(value=DEFAULT_OUTPUT_DIR)
        # Trạng thái đang xử lý
        self._processing = False
        
        self._build_ui()
    
    # ══════════════════════════════════════════════
    # Xây dựng giao diện
    # ══════════════════════════════════════════════
    
    def _build_ui(self):
        """Dựng toàn bộ giao diện co giãn 100% chiều ngang và hiện đại hóa thẩm mỹ."""
        # Font gia đình chuẩn Windows
        FONT_FAMILY = "Segoe UI"
        
        # Style setup
        style = ttk.Style(self)
        style.theme_use("clam")
        
        BG_COLOR = "#f8fafc"
        TITLE_COLOR = "#0f172a"
        FRAME_BG = "#ffffff"
        PRIMARY_BLUE = "#2563eb"
        PRIMARY_HOVER = "#1d4ed8"
        TEXT_DARK = "#334155"
        
        self.configure(bg=BG_COLOR)
        
        style.configure("Title.TLabel", font=(FONT_FAMILY, 14, "bold"), foreground=TITLE_COLOR, background=BG_COLOR)
        style.configure("Section.TLabelframe", background=FRAME_BG, relief="solid", borderwidth=1)
        style.configure("Section.TLabelframe.Label", font=(FONT_FAMILY, 10, "bold"), foreground="#1e293b", background=FRAME_BG)
        style.configure("TLabel", font=(FONT_FAMILY, 10), background=FRAME_BG, foreground=TEXT_DARK)
        style.configure("TFrame", background=FRAME_BG)
        style.configure("TButton", font=(FONT_FAMILY, 10), padding=(10, 6))
        style.configure("Action.TButton", font=(FONT_FAMILY, 11, "bold"), padding=(14, 8), background=PRIMARY_BLUE, foreground="#ffffff")
        style.map("Action.TButton", background=[("active", PRIMARY_HOVER)])
        style.configure("Treeview", font=(FONT_FAMILY, 9), rowheight=28, fieldbackground="#ffffff")
        style.configure("Treeview.Heading", font=(FONT_FAMILY, 9, "bold"), background="#f1f5f9", foreground="#0f172a")
        
        # Scrollable main frame
        main_canvas = tk.Canvas(self, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=main_canvas.yview)
        self._main_frame = ttk.Frame(main_canvas, style="TFrame")
        
        self._main_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )
        canvas_window_id = main_canvas.create_window((0, 0), window=self._main_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        
        # KEY FIX: Ép _main_frame tự co giãn theo chiều rộng canvas khi window thay đổi kích thước
        main_canvas.bind(
            "<Configure>",
            lambda e: main_canvas.itemconfig(canvas_window_id, width=e.width)
        )
        
        scrollbar.pack(side="right", fill="y")
        main_canvas.pack(side="left", fill="both", expand=True)
        
        # Bind mousewheel
        self.bind_all("<MouseWheel>",
                      lambda e: main_canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        
        # Configure main_frame column 0 to stretch 100%
        self._main_frame.columnconfigure(0, weight=1)
        
        pad = {"padx": 8, "pady": 4}
        
        # ── Tiêu đề ──
        ttk.Label(
            self._main_frame, text="📋 Chứng Nhận Phát Sóng — Nhập liệu",
            style="Title.TLabel"
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 8))
        
        # ── Phần 1: Thông tin chung (dùng cho tất cả khoản mục) ──
        frame_common = ttk.LabelFrame(
            self._main_frame, text="  Thông tin chung  ", style="Section.TLabelframe"
        )
        frame_common.grid(row=1, column=0, sticky="ew", padx=15, pady=6)
        frame_common.columnconfigure(1, weight=1)
        frame_common.columnconfigure(3, weight=1)
        
        # Row 0: Tên KH + Tên viết tắt
        ttk.Label(frame_common, text="Tên khách hàng:").grid(row=0, column=0, sticky="e", **pad)
        self._ent_ten_kh = ttk.Entry(frame_common)
        self._ent_ten_kh.grid(row=0, column=1, sticky="ew", **pad)
        
        ttk.Label(frame_common, text="Tên viết tắt:").grid(row=0, column=2, sticky="e", **pad)
        self._ent_ten_vt = ttk.Entry(frame_common, width=15)
        self._ent_ten_vt.grid(row=0, column=3, sticky="ew", **pad)
        
        # Row 1: Hợp đồng + Nhãn hàng
        ttk.Label(frame_common, text="Hợp đồng:").grid(row=1, column=0, sticky="e", **pad)
        self._ent_hop_dong = ttk.Entry(frame_common)
        self._ent_hop_dong.grid(row=1, column=1, sticky="ew", **pad)
        
        ttk.Label(frame_common, text="Nhãn hàng:").grid(row=1, column=2, sticky="e", **pad)
        self._ent_nhan = ttk.Entry(frame_common)
        self._ent_nhan.grid(row=1, column=3, sticky="ew", **pad)
        
        # Row 2: Chiến dịch
        ttk.Label(frame_common, text="Chiến dịch:").grid(row=2, column=0, sticky="e", **pad)
        self._ent_chien_dich = ttk.Entry(frame_common)
        self._ent_chien_dich.grid(row=2, column=1, columnspan=3, sticky="ew", **pad)
        
        # Row 3: Thư mục lưu file
        ttk.Label(frame_common, text="Thư mục lưu:").grid(row=3, column=0, sticky="e", **pad)
        frame_output = ttk.Frame(frame_common, style="TFrame")
        frame_output.grid(row=3, column=1, columnspan=3, sticky="ew", **pad)
        frame_output.columnconfigure(0, weight=1)
        
        ent_output = ttk.Entry(frame_output, textvariable=self._output_dir)
        ent_output.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(
            frame_output, text="Chọn...", width=10,
            command=self._browse_output_dir
        ).grid(row=0, column=1)
        
        # ── Phần 2: Nhập khoản mục ──
        frame_item = ttk.LabelFrame(
            self._main_frame, text="  Thêm khoản mục  ", style="Section.TLabelframe"
        )
        frame_item.grid(row=2, column=0, sticky="ew", padx=15, pady=6)
        frame_item.columnconfigure(1, weight=1)
        frame_item.columnconfigure(3, weight=1)
        
        # Nội dung khoản mục
        ttk.Label(frame_item, text="Nội dung khoản mục:").grid(row=0, column=0, sticky="e", **pad)
        self._ent_noi_dung = ttk.Entry(frame_item)
        self._ent_noi_dung.grid(row=0, column=1, columnspan=3, sticky="ew", **pad)
        
        # Link bài
        ttk.Label(frame_item, text="Link bài:").grid(row=1, column=0, sticky="e", **pad)
        self._ent_link = ttk.Entry(frame_item)
        self._ent_link.grid(row=1, column=1, columnspan=3, sticky="ew", **pad)
        
        # Loại + ĐVT
        ttk.Label(frame_item, text="Loại:").grid(row=2, column=0, sticky="e", **pad)
        self._cmb_loai = ttk.Combobox(
            frame_item, values=["Báo chí", "Facebook"],
            state="readonly", width=15
        )
        self._cmb_loai.set("Báo chí")
        self._cmb_loai.grid(row=2, column=1, sticky="w", **pad)
        
        ttk.Label(frame_item, text="Đơn vị (ĐVT):").grid(row=2, column=2, sticky="e", **pad)
        self._ent_don_vi = ttk.Entry(frame_item, width=15)
        self._ent_don_vi.insert(0, "Bài")
        self._ent_don_vi.grid(row=2, column=3, sticky="w", **pad)
        
        # Số lượng + Ngày đăng
        ttk.Label(frame_item, text="Số lượng:").grid(row=3, column=0, sticky="e", **pad)
        self._spn_so_luong = ttk.Spinbox(frame_item, from_=1, to=999, width=10)
        self._spn_so_luong.set(1)
        self._spn_so_luong.grid(row=3, column=1, sticky="w", **pad)
        
        ttk.Label(frame_item, text="Ngày đăng (dd/mm/yyyy):").grid(row=3, column=2, sticky="e", **pad)
        self._ent_ngay = ttk.Entry(frame_item, width=16)
        self._ent_ngay.insert(0, datetime.now().strftime("%d/%m/%Y"))
        self._ent_ngay.grid(row=3, column=3, sticky="w", **pad)
        
        # Nút thêm khoản mục & Bảng kê
        frame_item_btns = ttk.Frame(frame_item, style="TFrame")
        frame_item_btns.grid(row=4, column=0, columnspan=4, sticky="e", padx=10, pady=8)
        
        ttk.Button(
            frame_item_btns, text="➕ Thêm khoản mục",
            command=self._add_item
        ).pack(side="left", padx=4)
        
        ttk.Button(
            frame_item_btns, text="📋 Dán từ Bảng kê (Clipboard)",
            command=self._paste_clipboard
        ).pack(side="left", padx=4)
        
        ttk.Button(
            frame_item_btns, text="📂 Nhập Bảng kê (CSV/Excel)",
            command=self._import_csv
        ).pack(side="left", padx=4)
        
        ttk.Button(
            frame_item_btns, text="📄 File Mẫu Bảng Kê",
            command=self._open_sample_template
        ).pack(side="left", padx=4)
        
        # ── Phần 3: Danh sách khoản mục đã thêm ──
        frame_list = ttk.LabelFrame(
            self._main_frame, text="  Danh sách khoản mục  ", style="Section.TLabelframe"
        )
        frame_list.grid(row=3, column=0, sticky="ew", padx=15, pady=6)
        frame_list.columnconfigure(0, weight=1)
        
        columns = ("stt", "noi_dung", "link", "loai", "dvt", "sl", "ngay")
        self._tree = ttk.Treeview(
            frame_list, columns=columns, show="headings", height=7,
            selectmode="browse"
        )
        
        col_config = [
            ("stt",      "STT",             45,  "center", False),
            ("noi_dung", "Nội dung",        250, "w",      True),
            ("link",     "Link bài",        250, "w",      True),
            ("loai",     "Loại",            80,  "center", False),
            ("dvt",      "ĐVT",            60,  "center", False),
            ("sl",       "SL",             50,  "center", False),
            ("ngay",     "Ngày đăng",       95,  "center", False),
        ]
        for col_id, heading, width, anchor, stretch in col_config:
            self._tree.heading(col_id, text=heading)
            self._tree.column(col_id, width=width, anchor=anchor, minwidth=width, stretch=stretch)
        
        tree_scroll = ttk.Scrollbar(frame_list, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=tree_scroll.set)
        self._tree.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=8)
        tree_scroll.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)
        
        # Nút xoá khoản mục
        ttk.Button(
            frame_list, text="🗑 Xoá khoản mục đã chọn",
            command=self._remove_selected_item
        ).grid(row=1, column=0, columnspan=2, sticky="e", padx=10, pady=(0, 8))
        
        # ── Phần 4: Nút hành động chính ──
        frame_actions = ttk.Frame(self._main_frame, style="TFrame")
        frame_actions.grid(row=4, column=0, sticky="ew", padx=15, pady=10)
        
        self._btn_generate = ttk.Button(
            frame_actions, text="🚀 Tạo Chứng Nhận Phát Sóng",
            style="Action.TButton", command=self._start_generate
        )
        self._btn_generate.pack(side="left", padx=5)
        
        self._btn_fb_login = ttk.Button(
            frame_actions, text="🔑 Đăng nhập Facebook",
            command=self._facebook_login
        )
        self._btn_fb_login.pack(side="left", padx=5)
        
        self._btn_open_folder = ttk.Button(
            frame_actions, text="📁 Mở thư mục output",
            command=self._open_output_folder, state="disabled"
        )
        self._btn_open_folder.pack(side="left", padx=5)
        
        # ── Phần 5: Thanh tiến trình & Log ──
        frame_progress = ttk.LabelFrame(
            self._main_frame, text="  Tiến trình  ", style="Section.TLabelframe"
        )
        frame_progress.grid(row=5, column=0, sticky="ew", padx=15, pady=(0, 15))
        frame_progress.columnconfigure(0, weight=1)
        
        self._lbl_status = ttk.Label(frame_progress, text="Sẵn sàng.", font=(FONT_FAMILY, 10))
        self._lbl_status.grid(row=0, column=0, sticky="w", padx=10, pady=4)
        
        self._progress = ttk.Progressbar(frame_progress, mode="determinate")
        self._progress.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        
        self._txt_log = tk.Text(
            frame_progress, height=6, font=("Consolas", 9),
            state="disabled", bg="#0f172a", fg="#e2e8f0",
            wrap="word", relief="flat"
        )
        self._txt_log.grid(row=2, column=0, sticky="ew", padx=10, pady=(4, 10))
    
    # ══════════════════════════════════════════════
    # Xử lý sự kiện
    # ══════════════════════════════════════════════
    
    def _browse_output_dir(self):
        """Chọn thư mục lưu file đầu ra."""
        d = filedialog.askdirectory(
            title="Chọn thư mục lưu file CNPS",
            initialdir=self._output_dir.get()
        )
        if d:
            self._output_dir.set(d)
    
    def _add_item(self):
        """Thêm 1 khoản mục vào danh sách."""
        # Validate
        noi_dung = self._ent_noi_dung.get().strip()
        link = self._ent_link.get().strip()
        ngay = self._ent_ngay.get().strip()
        
        if not noi_dung:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập Nội dung khoản mục.")
            self._ent_noi_dung.focus()
            return
        if not link:
            messagebox.showwarning("Thiếu thông tin", "Vui lòng nhập Link bài.")
            self._ent_link.focus()
            return
        
        # Validate ngày
        try:
            datetime.strptime(ngay, "%d/%m/%Y")
        except ValueError:
            messagebox.showwarning(
                "Sai định dạng",
                f"Ngày đăng '{ngay}' không đúng định dạng dd/mm/yyyy."
            )
            self._ent_ngay.focus()
            return
        
        item = {
            "noi_dung_khoan_muc": noi_dung,
            "link_bai": link,
            "loai": self._cmb_loai.get(),
            "don_vi": self._ent_don_vi.get().strip() or "Bài",
            "so_luong": self._spn_so_luong.get(),
            "ngay_dang": ngay,
        }
        
        self._items.append(item)
        stt = len(self._items)
        self._tree.insert("", "end", values=(
            stt,
            noi_dung[:50] + ("..." if len(noi_dung) > 50 else ""),
            link[:50] + ("..." if len(link) > 50 else ""),
            item["loai"],
            item["don_vi"],
            item["so_luong"],
            ngay,
        ))
        
        # Xoá form khoản mục để nhập tiếp
        self._ent_noi_dung.delete(0, tk.END)
        self._ent_link.delete(0, tk.END)
        self._ent_noi_dung.focus()
        
        self._log(f"✅ Đã thêm khoản mục #{stt}: {noi_dung[:60]}")
    
    def _remove_selected_item(self):
        """Xoá khoản mục đang chọn trong bảng."""
        selected = self._tree.selection()
        if not selected:
            messagebox.showinfo("Chọn khoản mục", "Vui lòng chọn 1 khoản mục để xoá.")
            return
        
        item_id = selected[0]
        idx = self._tree.index(item_id)
        self._tree.delete(item_id)
        self._items.pop(idx)
        
        # Cập nhật lại STT
        for i, tree_id in enumerate(self._tree.get_children()):
            vals = list(self._tree.item(tree_id, "values"))
            vals[0] = i + 1
            self._tree.item(tree_id, values=vals)
        
        self._log(f"🗑 Đã xoá khoản mục #{idx + 1}")
    
    def _import_csv(self):
        """Nhập khoản mục từ file Bảng kê Google Sheet (CSV / Excel .xlsx)."""
        filepath = filedialog.askopenfilename(
            title="Chọn file Bảng kê (Excel hoặc CSV)",
            filetypes=[
                ("File Bảng kê (Excel/CSV)", "*.xlsx;*.xls;*.csv;*.tsv"),
                ("Excel files", "*.xlsx;*.xls"),
                ("CSV files", "*.csv;*.tsv"),
                ("All files", "*.*")
            ]
        )
        if not filepath:
            return
        
        try:
            items, metadata = parse_csv_or_excel_file(filepath)
            self._apply_imported_data(items, metadata, source_name=os.path.basename(filepath))
        except Exception as e:
            messagebox.showerror("Lỗi đọc file Bảng kê", f"Không đọc được file Bảng kê:\n{e}")

    def _paste_clipboard(self):
        """Nhập dữ liệu copy trực tiếp từ Google Sheet / Excel qua Clipboard."""
        try:
            clip_text = self.clipboard_get()
        except Exception:
            messagebox.showwarning(
                "Bộ nhớ tạm trống",
                "Không tìm thấy dữ liệu trong Clipboard.\n"
                "Vui lòng bôi đen và Copy (Ctrl+C) các dòng từ Bảng kê Google Sheet rồi bấm lại nút này."
            )
            return
            
        try:
            items, metadata = parse_clipboard_text(clip_text)
            if not items:
                messagebox.showwarning(
                    "Không tìm thấy dữ liệu",
                    "Dữ liệu đã copy không đúng định dạng Bảng kê (cần chứa cột Nội dung / Link bài)."
                )
                return
            self._apply_imported_data(items, metadata, source_name="Clipboard (Google Sheet)")
        except Exception as e:
            messagebox.showerror("Lỗi đọc Clipboard", f"Không phân tích được dữ liệu copy:\n{e}")

    def _apply_imported_data(self, items: list[dict], metadata: dict, source_name: str):
        """Áp dụng các items & metadata đã parse từ Bảng kê vào GUI."""
        # Tự động điền thông tin chung nếu GUI đang trống
        if metadata.get("ten_khach_hang") and not self._ent_ten_kh.get().strip():
            self._ent_ten_kh.delete(0, tk.END)
            self._ent_ten_kh.insert(0, metadata["ten_khach_hang"])
            
        if metadata.get("nhan_hang") and not self._ent_nhan.get().strip():
            self._ent_nhan.delete(0, tk.END)
            self._ent_nhan.insert(0, metadata["nhan_hang"])
            
        if metadata.get("chien_dich") and not self._ent_chien_dich.get().strip():
            self._ent_chien_dich.delete(0, tk.END)
            self._ent_chien_dich.insert(0, metadata["chien_dich"])
            
        # Thêm từ item đầu tiên nếu GUI vẫn trống
        if items:
            first = items[0]
            if first.get("hop_dong") and not self._ent_hop_dong.get().strip():
                self._ent_hop_dong.delete(0, tk.END)
                self._ent_hop_dong.insert(0, first["hop_dong"])
            if first.get("nhan_hang") and not self._ent_nhan.get().strip():
                self._ent_nhan.delete(0, tk.END)
                self._ent_nhan.insert(0, first["nhan_hang"])
            if first.get("chien_dich") and not self._ent_chien_dich.get().strip():
                self._ent_chien_dich.delete(0, tk.END)
                self._ent_chien_dich.insert(0, first["chien_dich"])
        
        count = 0
        for item in items:
            if item.get("noi_dung_khoan_muc") and item.get("link_bai"):
                self._items.append(item)
                stt = len(self._items)
                self._tree.insert("", "end", values=(
                    stt,
                    item["noi_dung_khoan_muc"][:50] + ("..." if len(item["noi_dung_khoan_muc"]) > 50 else ""),
                    item["link_bai"][:50] + ("..." if len(item["link_bai"]) > 50 else ""),
                    item["loai"],
                    item["don_vi"],
                    item["so_luong"],
                    item["ngay_dang"],
                ))
                count += 1
                
        self._log(f"📂 Đã nhập {count} khoản mục từ {source_name}.")
        messagebox.showinfo(
            "Thành công",
            f"Đã nhập thành công {count} khoản mục từ {source_name}.\n"
            "Vui lòng kiểm tra lại thông tin trước khi bấm 'Tạo Chứng Nhận Phát Sóng'."
        )

    def _open_sample_template(self):
        """Mở file Bảng kê mẫu (Excel/CSV) để nhân viên tham khảo / copy."""
        from config import SAMPLE_XLSX_PATH, SAMPLE_CSV_PATH
        
        target = SAMPLE_XLSX_PATH if os.path.exists(SAMPLE_XLSX_PATH) else SAMPLE_CSV_PATH
        if os.path.exists(target):
            os.startfile(target)
            self._log(f"📄 Đã mở file Bảng kê mẫu: {os.path.basename(target)}")
        else:
            messagebox.showwarning("Không tìm thấy file mẫu", f"Chưa tìm thấy file Bảng kê mẫu tại:\n{target}")
    
    def _facebook_login(self):
        """Mở Chromium headed cho nhân viên đăng nhập Facebook, lưu session."""
        self._log("🔑 Đang mở trình duyệt để đăng nhập Facebook...")
        self._btn_fb_login.configure(state="disabled")
        
        thread = threading.Thread(target=self._do_facebook_login, daemon=True)
        thread.start()
    
    def _do_facebook_login(self):
        """Thực hiện đăng nhập Facebook trên thread riêng."""
        try:
            import asyncio
            asyncio.run(self._async_facebook_login())
        except ImportError:
            self.after(0, lambda: self._log("❌ Chưa cài Playwright. Chạy: pip install playwright"))
            self.after(0, lambda: messagebox.showerror(
                "Thiếu thư viện",
                "Chưa cài Playwright.\nChạy: pip install playwright\nsau đó: playwright install chromium"
            ))
        except Exception as e:
            self.after(0, lambda: self._log(f"❌ Lỗi đăng nhập Facebook: {e}"))
            self.after(0, lambda: messagebox.showerror("Lỗi", f"Đăng nhập Facebook thất bại:\n{e}"))
        finally:
            self.after(0, lambda: self._btn_fb_login.configure(state="normal"))
    
    async def _async_facebook_login(self):
        """Mở Chromium headed, chờ đăng nhập, lưu storage_state."""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            
            await page.goto("https://www.facebook.com/")
            
            self.after(0, lambda: self._log(
                "ℹ️ Vui lòng đăng nhập Facebook trong cửa sổ trình duyệt vừa mở.\n"
                "   Sau khi đăng nhập xong (thấy trang News Feed), đóng trình duyệt."
            ))
            self.after(0, lambda: messagebox.showinfo(
                "Đăng nhập Facebook",
                "Vui lòng đăng nhập Facebook trong cửa sổ trình duyệt vừa mở.\n\n"
                "Sau khi đăng nhập xong (thấy trang News Feed), đóng trình duyệt lại."
            ))
            
            # Chờ cho đến khi trình duyệt đóng
            try:
                await page.wait_for_event("close", timeout=300_000)  # 5 phút
            except Exception:
                pass
            
            # Lưu session
            os.makedirs(os.path.dirname(FB_STORAGE_STATE_PATH), exist_ok=True)
            await context.storage_state(path=FB_STORAGE_STATE_PATH)
            await browser.close()
        
        self.after(0, lambda: self._log("✅ Đã lưu session Facebook thành công."))
        self.after(0, lambda: messagebox.showinfo(
            "Thành công",
            f"Đã lưu session Facebook vào:\n{FB_STORAGE_STATE_PATH}"
        ))
    
    def _start_generate(self):
        """Bắt đầu quy trình tạo CNPS (trên thread riêng)."""
        if self._processing:
            messagebox.showinfo("Đang xử lý", "Vui lòng đợi quá trình hiện tại hoàn tất.")
            return
        
        # Validate thông tin chung
        ten_kh = self._ent_ten_kh.get().strip()
        ten_vt = self._ent_ten_vt.get().strip()
        hop_dong = self._ent_hop_dong.get().strip()
        nhan = self._ent_nhan.get().strip()
        chien_dich = self._ent_chien_dich.get().strip()
        
        missing = []
        if not ten_kh:
            missing.append("Tên khách hàng")
        if not ten_vt:
            missing.append("Tên viết tắt")
        if not hop_dong:
            missing.append("Hợp đồng")
        if not nhan:
            missing.append("Nhãn hàng")
        if not chien_dich:
            missing.append("Chiến dịch")
        
        if missing:
            messagebox.showwarning(
                "Thiếu thông tin chung",
                "Vui lòng nhập đầy đủ:\n• " + "\n• ".join(missing)
            )
            return
        
        if not self._items:
            messagebox.showwarning(
                "Chưa có khoản mục",
                "Vui lòng thêm ít nhất 1 khoản mục trước khi tạo CNPS."
            )
            return
        
        # Kiểm tra template tồn tại
        if not os.path.exists(TEMPLATE_PATH):
            messagebox.showerror(
                "Thiếu file template",
                f"Không tìm thấy file template tại:\n{TEMPLATE_PATH}\n\n"
                "Vui lòng đặt file 'CNPS template.docx' vào thư mục data/."
            )
            return
        
        # Chuẩn bị dữ liệu chung
        common_data = {
            "ten_khach_hang": ten_kh,
            "ten_viet_tat": ten_vt,
            "hop_dong": hop_dong,
            "nhan_hang": nhan,
            "chien_dich": chien_dich,
        }
        
        # Disable UI, bắt đầu xử lý
        self._processing = True
        self._btn_generate.configure(state="disabled")
        self._progress["value"] = 0
        self._progress["maximum"] = len(self._items)
        
        thread = threading.Thread(
            target=self._do_generate,
            args=(common_data,),
            daemon=True
        )
        thread.start()
    
    def _do_generate(self, common_data: dict):
        """
        Thực hiện tạo CNPS cho từng khoản mục (chạy trên thread riêng).
        Mỗi khoản mục = 1 file CNPS.
        """
        output_dir = self._output_dir.get()
        os.makedirs(output_dir, exist_ok=True)
        
        results = {"success": [], "failed": []}
        total = len(self._items)
        
        for i, item in enumerate(self._items):
            idx = i + 1
            noi_dung_short = item["noi_dung_khoan_muc"][:40]
            
            self.after(0, lambda idx=idx, total=total, s=noi_dung_short:
                self._update_status(f"Đang xử lý khoản mục {idx}/{total}: {s}..."))
            
            # Thư mục tạm cho ảnh screenshot của khoản mục này
            temp_dir = None
            try:
                # Merge dữ liệu chung + riêng
                data = {**common_data, **item}
                
                # Tạo tên file
                filename = generate_output_filename(data)
                output_path = os.path.join(output_dir, filename)
                
                # Thư mục tạm cho ảnh screenshot
                temp_dir = tempfile.mkdtemp(prefix="cnps_screenshots_")
                
                # Chụp screenshot
                def _progress_cb(msg, _idx=idx, _total=total):
                    self.after(0, lambda m=msg: self._log(f"📷 [{_idx}/{_total}] {m}"))
                
                self.after(0, lambda idx=idx:
                    self._log(f"📷 [{idx}/{total}] Đang chụp ảnh..."))
                
                screenshot_paths = capture_screenshots(
                    url=data["link_bai"],
                    article_type=data["loai"],
                    output_dir=temp_dir,
                    progress_callback=_progress_cb,
                )
                
                # Tạo file DOCX
                self.after(0, lambda idx=idx:
                    self._log(f"📝 [{idx}/{total}] Đang tạo file DOCX..."))
                
                result_path = generate_cnps(
                    data=data,
                    screenshot_paths=screenshot_paths,
                    template_path=TEMPLATE_PATH,
                    output_path=output_path,
                )
                
                results["success"].append((idx, noi_dung_short, str(result_path)))
                self.after(0, lambda idx=idx, p=str(result_path):
                    self._log(f"✅ [{idx}/{total}] Đã tạo: {os.path.basename(p)}"))
                
            except SessionExpiredError as e:
                results["failed"].append((idx, noi_dung_short, str(e)))
                self.after(0, lambda idx=idx, err=str(e):
                    self._log(f"🔑 [{idx}/{total}] Session hết hạn: {err}"))
                self.after(0, lambda err=str(e): messagebox.showwarning(
                    "Session Facebook", err))
            except Exception as e:
                results["failed"].append((idx, noi_dung_short, str(e)))
                self.after(0, lambda idx=idx, err=str(e):
                    self._log(f"❌ [{idx}/{total}] Lỗi: {err}"))
            finally:
                # Dọn thư mục tạm
                if temp_dir and os.path.isdir(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except Exception:
                        pass
            
            # Cập nhật progress
            self.after(0, lambda v=idx: self._update_progress(v))
        
        # Hoàn tất
        self.after(0, lambda: self._on_generate_complete(results))
    
    def _on_generate_complete(self, results: dict):
        """Xử lý sau khi tạo CNPS hoàn tất."""
        self._processing = False
        self._btn_generate.configure(state="normal")
        self._btn_open_folder.configure(state="normal")
        
        n_ok = len(results["success"])
        n_fail = len(results["failed"])
        
        self._update_status(f"Hoàn tất: {n_ok} thành công, {n_fail} thất bại.")
        
        # Tạo thông báo chi tiết
        msg = f"✅ Thành công: {n_ok}/{n_ok + n_fail} khoản mục\n"
        if results["failed"]:
            msg += f"\n❌ Thất bại: {n_fail} khoản mục:\n"
            for idx, name, err in results["failed"]:
                msg += f"  • #{idx} {name}: {err}\n"
        
        if n_fail == 0:
            messagebox.showinfo("Hoàn tất", msg)
        else:
            messagebox.showwarning("Hoàn tất (có lỗi)", msg)
    
    def _open_output_folder(self):
        """Mở thư mục chứa file CNPS vừa tạo."""
        output_dir = self._output_dir.get()
        if os.path.isdir(output_dir):
            open_folder_in_explorer(output_dir)
        else:
            messagebox.showinfo("Thư mục không tồn tại", f"Không tìm thấy: {output_dir}")
    
    # ══════════════════════════════════════════════
    # Cập nhật UI
    # ══════════════════════════════════════════════
    
    def _update_status(self, text: str):
        """Cập nhật dòng trạng thái."""
        self._lbl_status.configure(text=text)
    
    def _update_progress(self, value: int):
        """Cập nhật thanh tiến trình."""
        self._progress["value"] = value
    
    def _log(self, message: str):
        """Ghi log vào vùng text log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._txt_log.configure(state="normal")
        self._txt_log.insert("end", f"[{timestamp}] {message}\n")
        self._txt_log.see("end")
        self._txt_log.configure(state="disabled")
