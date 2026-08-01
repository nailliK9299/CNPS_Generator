# -*- coding: utf-8 -*-
"""
Xử lý ảnh: phân trang ảnh dài thành nhiều ảnh có chiều cao phù hợp khổ A4.
Dùng Pillow — Căn chính xác dải pixel khoảng trắng giữa các đoạn văn bản.
"""
import io
import math
import logging
from pathlib import Path

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def smart_paginate(
    screenshot_bytes: bytes,
    block_positions: list[dict],
    target_page_height: int,
    output_dir: str | Path,
    device_scale_factor: int = 3,
) -> list[Path]:
    """
    Cắt ảnh dài thành các trang cân bằng tối ưu khổ A4.
    Căn chính xác dải pixel khoảng trắng giữa các đoạn văn bản (không cắt ngang chữ).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    img = Image.open(io.BytesIO(screenshot_bytes))
    img_width, img_height = img.size  # pixel vật lý
    scale = device_scale_factor
    
    max_page_height_px = int(target_page_height * scale)  # ~4860px ở 3x scale
    
    # Tính các điểm cắt dựa trên phân tích dòng pixel khoảng trắng trên ảnh
    cut_points_px = _compute_pixel_whitespace_cuts(img, max_page_height_px)
    
    page_images = []
    for i in range(len(cut_points_px) - 1):
        top = cut_points_px[i]
        bottom = cut_points_px[i + 1]
        
        if bottom <= top:
            continue
            
        page_img = img.crop((0, top, img_width, bottom))
        
        # Kiểm tra khoảng trắng
        white_ratio = _calculate_white_ratio(page_img)
        if white_ratio >= 0.96 or page_img.height < int(50 * scale):
            logger.warning(
                f"Bỏ qua lát cắt ảnh {i + 1}: {white_ratio * 100:.0f}% khoảng trắng / height={page_img.height}px (trang trống)"
            )
            continue
            
        page_path = output_dir / f"page_{len(page_images) + 1:03d}.png"
        page_img.save(str(page_path), "PNG")
        page_images.append(page_path)
        logger.info(f"Trang {len(page_images)}: {page_img.width}x{page_img.height}px ({page_img.height / scale:.0f} CSS px), trắng={white_ratio:.1%}")
        
    return page_images


def _compute_pixel_whitespace_cuts(
    img: Image.Image,
    max_page_height_px: int,
    bg_threshold: int = 245,
) -> list[int]:
    """
    Phân chia chiều cao ảnh thành N trang CÂN BẰNG NHẤT,
    đảm bảo không trang nào vượt quá max_page_height_px và KHÔNG TRANG NÀO BỊ LẺ ẢNH BÉ.
    Mỗi điểm ngắt được căn vào dải pixel trắng giữa các đoạn văn bản.
    """
    img_width, img_height = img.size
    if img_height <= max_page_height_px:
        return [0, img_height]
        
    if img.mode != "RGB":
        img_rgb = img.convert("RGB")
    else:
        img_rgb = img
        
    arr = np.array(img_rgb)
    white_mask = np.all(arr >= bg_threshold, axis=2)
    row_white_ratios = white_mask.mean(axis=1)  # Mảng 1D độ dài img_height
    
    n_pages = max(1, math.ceil(img_height / max_page_height_px))
    
    cut_points = [0]
    y_start = 0
    
    for i in range(1, n_pages):
        remaining = img_height - y_start
        pages_left = n_pages - (i - 1)
        step = math.ceil(remaining / pages_left)
        step = min(step, max_page_height_px)
        
        target_y = y_start + step
        search_start = max(y_start + int(step * 0.65), target_y - int(350 * 3))
        search_end = min(y_start + max_page_height_px, target_y + int(200 * 3))
        search_end = min(search_end, img_height - 50)
        
        best_y = target_y
        best_score = -1.0
        
        for y in range(search_end, search_start, -1):
            y_min = max(0, y - 2)
            y_max = min(img_height, y + 3)
            band_score = row_white_ratios[y_min:y_max].mean()
            
            if band_score >= 0.97:
                best_y = y
                best_score = band_score
                break
            elif band_score > best_score:
                best_score = band_score
                best_y = y
                
        cut_points.append(best_y)
        y_start = best_y
        
    if cut_points[-1] != img_height:
        cut_points.append(img_height)
        
    return cut_points


def _calculate_white_ratio(img: Image.Image, threshold: int = 250) -> float:
    """Tính tỷ lệ pixel 'trắng' (gần trắng) trong ảnh."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.array(img)
    white_mask = np.all(arr >= threshold, axis=2)
    return float(white_mask.sum()) / float(white_mask.size)
