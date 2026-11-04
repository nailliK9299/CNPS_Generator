/* ══════════════════════════════════════════════════════════════
   CNPS Core — port từ bản Python (src/utils, src/core) sang JS.
   Không phụ thuộc UI. Chạy được trong trình duyệt (và Node cho phần parser).
   ══════════════════════════════════════════════════════════════ */
(function (root) {
  'use strict';

  // ─── Cấu hình (tương đương src/config.py) ───
  const CONFIG = {
    VIEWPORT_WIDTH: 1080,          // px CSS — chuẩn chiều rộng trang chụp
    VIEWPORT_HEIGHT: 900,
    PAGE_HEIGHT_RATIO: 1.5,        // TARGET_PAGE_HEIGHT_PX = VIEWPORT_WIDTH * 1.5
    IMAGE_WIDTH_CM: 15.92,         // vùng in ngang A4 trong DOCX
    EMU_PER_CM: 360000,
  };

  const HIDE_ADS_CSS = `
ins.adsbygoogle,
[class*="adsbygoogle"]:not(html):not(body):not(main):not(article),
[class*="advertisement"]:not(html):not(body):not(main):not(article),
[id^="div-gpt-ad"],[id^="google_ads"],[id^="admzone"],[id^="ads_"],
[class^="ads-"]:not(html):not(body):not(main):not(article),
.ads-box,.box-ads,.banner-ads,.ad-container,.ad-slot,.ad-banner,
iframe[src*="doubleclick"],iframe[src*="googlesyndication"],iframe[src*="facebook.com/plugins"],iframe[id*="google_ads"],
.popup:not(html):not(body):not(main):not(article),.modal:not(html):not(body):not(main):not(article),
[class*="popup"]:not(html):not(body):not(main):not(article),
[class*="cookie"]:not(html):not(body):not(main):not(article),[class*="gdpr"]:not(html):not(body):not(main):not(article),[class*="consent"]:not(html):not(body):not(main):not(article),
.comment-section,#ykcb-form,.box-comment,.site-footer,.page-footer,#site-footer,#footer-site
{display:none!important;height:0!important;min-height:0!important;max-height:0!important;padding:0!important;margin:0!important;overflow:hidden!important}`.trim();

  // ══════════════════════════════════════════════
  // helpers.py
  // ══════════════════════════════════════════════
  function removeVietnameseDiacritics(text) {
    return String(text == null ? '' : text)
      .normalize('NFKD')
      .replace(/\p{M}/gu, '')
      .replace(/đ/g, 'd').replace(/Đ/g, 'D');
  }

  function sanitizeFilename(text) {
    let t = removeVietnameseDiacritics(text || '');
    t = t.trim().replace(/ /g, '_');
    t = t.replace(/[^\w\-.]/g, '');
    t = t.replace(/_+/g, '_');
    return t.replace(/^_+|_+$/g, '');
  }

  const pad = (n, l = 2) => String(n).padStart(l, '0');

  function isValidDate(d, m, y) {
    const dt = new Date(y, m - 1, d);
    return dt.getFullYear() === y && dt.getMonth() === m - 1 && dt.getDate() === d;
  }

  /** Parse chặt 'dd/mm/yyyy' (giống datetime.strptime(..., "%d/%m/%Y")). */
  function parseDMY(s) {
    const m = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(String(s || '').trim());
    if (!m) return null;
    const d = +m[1], mo = +m[2], y = +m[3];
    return isValidDate(d, mo, y) ? { d, m: mo, y } : null;
  }

  function todayDMY() {
    const n = new Date();
    return `${pad(n.getDate())}/${pad(n.getMonth() + 1)}/${n.getFullYear()}`;
  }

  /** CNPS_{TenVietTat}_{HopDong}_{Nhan}_{ChienDich}_{ddMMyyyy}.docx */
  function generateOutputFilename(data, indexSuffix) {
    const parts = [
      'CNPS',
      sanitizeFilename(data.ten_viet_tat || ''),
      sanitizeFilename(data.hop_dong || ''),
      sanitizeFilename(data.nhan_hang || ''),
      sanitizeFilename(data.chien_dich || ''),
    ];
    const dt = parseDMY(data.ngay_dang || '');
    parts.push(dt ? `${pad(dt.d)}${pad(dt.m)}${dt.y}` : sanitizeFilename(data.ngay_dang || ''));
    if (indexSuffix != null && indexSuffix !== '') {
      parts.push(typeof indexSuffix === 'number' ? pad(indexSuffix, 2) : sanitizeFilename(String(indexSuffix)));
    }
    return parts.filter(Boolean).join('_') + '.docx';
  }

  /** Đảm bảo tên file không bị trùng lặp trong cùng đợt xuất */
  function ensureUniqueFilename(filename, usedNames) {
    if (!usedNames) return filename;
    const dot = filename.lastIndexOf('.');
    const stem = dot > 0 ? filename.slice(0, dot) : filename;
    const ext = dot > 0 ? filename.slice(dot) : '.docx';
    let candidate = `${stem}${ext}`;
    if (!usedNames.has(candidate.toLowerCase())) {
      usedNames.add(candidate.toLowerCase());
      return candidate;
    }
    let counter = 2;
    while (true) {
      candidate = `${stem}_${pad(counter, 2)}${ext}`;
      if (!usedNames.has(candidate.toLowerCase())) {
        usedNames.add(candidate.toLowerCase());
        return candidate;
      }
      counter++;
    }
  }

  // ══════════════════════════════════════════════
  // table_parser.py
  // ══════════════════════════════════════════════
  const COLUMN_ALIASES = {
    hop_dong: ['hợp đồng', 'mã hợp đồng', 'hop dong', 'ma hop dong', 'mã hd', 'hd'],
    so_ht: ['số ht', 'so ht'],
    nhan_hang: ['nhãn', 'nhãn hàng', 'nhan', 'nhan hang', 'brand'],
    chien_dich: ['chiến dịch', 'chien dich', 'campaign'],
    noi_dung_khoan_muc: [
      'nội dung quảng cáo', 'nội dung', 'khoản mục', 'noi dung quang cao',
      'noi dung', 'khoan muc', 'tên bài', 'bài viết', 'hạng mục',
      'tên khoản mục', 'diễn giải', 'bài pr', 'tiêu đề', 'nội dung bài', 'tên nội dung',
    ],
    ngay_dang: ['lịch đăng', 'ngày đăng', 'lich dang', 'ngay dang', 'ngày', 'ngay', 'date', 'thời gian'],
    so_luong: ['số lượng', 'so luong', 'sl', 'qty'],
    don_vi: ['đvt', 'đơn vị', 'don vi', 'unit'],
    link_bai: ['link bài', 'link', 'url', 'link bai', 'đường dẫn', 'duong dan', 'link bài viết', 'link bài đăng'],
    loai: ['loại', 'loai', 'loại bài', 'kênh', 'kenh', 'loại tin', 'type'],
  };
  const NORM_ALIASES = Object.entries(COLUMN_ALIASES).map(([k, arr]) =>
    [k, arr.map(a => removeVietnameseDiacritics(a).trim().toLowerCase())]);

  const str = v => (v == null ? '' : String(v));
  const isDigits = v => /^\d+$/.test(v);

  function normalizeText(text) {
    if (!text) return '';
    return removeVietnameseDiacritics(str(text)).trim().toLowerCase().replace(/\s+/g, ' ');
  }

  function mapColumnName(headerName) {
    const norm = normalizeText(headerName);
    if (!norm || norm.length > 30 || norm.includes('http') || norm.includes('.com') || norm.includes('.vn')) return null;
    if (norm.split(' ').length > 5) return null;
    for (const [key, aliases] of NORM_ALIASES) {
      for (const a of aliases) {
        if (a === norm) return key;
        if (norm.startsWith(a) && norm.length <= a.length + 8) return key;
      }
    }
    return null;
  }

  function formatDateString(dateVal) {
    if (!dateVal) return todayDMY();
    let s = str(dateVal).trim();
    if (s.includes(' ')) s = s.split(' ')[0];
    let m;
    // %d/%m/%Y, %d-%m-%Y
    if ((m = /^(\d{1,2})([\/-])(\d{1,2})\2(\d{4})$/.exec(s)) && isValidDate(+m[1], +m[3], +m[4]))
      return `${pad(+m[1])}/${pad(+m[3])}/${pad(+m[4], 4)}`;
    // %d/%m/%y, %d-%m-%y
    if ((m = /^(\d{1,2})([\/-])(\d{1,2})\2(\d{2})$/.exec(s))) {
      const yy = +m[4], y = yy < 69 ? 2000 + yy : 1900 + yy;
      if (isValidDate(+m[1], +m[3], y)) return `${pad(+m[1])}/${pad(+m[3])}/${y}`;
    }
    // %Y-%m-%d, %Y/%m/%d
    if ((m = /^(\d{4})([\/-])(\d{1,2})\2(\d{1,2})$/.exec(s)) && isValidDate(+m[4], +m[3], +m[1]))
      return `${pad(+m[4])}/${pad(+m[3])}/${m[1]}`;
    const parts = s.split(/[\/\-.]/);
    if (parts.length === 3 && parts.every(isDigits)) {
      const [p1, p2, p3] = parts.map(Number);
      let d, mo, y;
      if (p3 > 1000) { d = p1; mo = p2; y = p3; }
      else if (p1 > 1000) { y = p1; mo = p2; d = p3; }
      else { d = p1; mo = p2; y = p3 < 100 ? p3 + 2000 : p3; }
      return `${pad(d)}/${pad(mo)}/${pad(y, 4)}`;
    }
    return s;
  }

  function detectArticleType(url) {
    const u = str(url).toLowerCase();
    return ['facebook.com', 'fb.com', 'fb.watch', 'fb.gg'].some(d => u.includes(d)) ? 'Facebook' : 'Báo chí';
  }

  function extractHeaderMetadata(rows) {
    const meta = {};
    for (const row of rows.slice(0, 15)) {
      const rowStr = row.filter(c => c).map(str).join(' ');
      let m;
      if (/B[êe]n A:/i.test(rowStr) && (m = /B[êe]n A:\s*(.+)/i.exec(rowStr)))
        meta.ten_khach_hang = m[1].split('Bên B')[0].split('Người đại diện')[0].trim();
      if (/Nh[ãa]n:/i.test(rowStr) && (m = /Nh[ãa]n:\s*(.+)/i.exec(rowStr)))
        meta.nhan_hang = m[1].split('Chiến dịch')[0].trim();
      if (/Chi[ếe]n d[ịi]ch:/i.test(rowStr) && (m = /Chi[ếe]n d[ịi]ch:\s*(.+)/i.exec(rowStr)))
        meta.chien_dich = m[1].trim();
    }
    return meta;
  }

  function parseRowsData(rows) {
    const items = [];
    for (const row of rows) {
      const mapped = {};
      for (const [col, val] of Object.entries(row)) {
        const key = mapColumnName(col);
        if (key && val != null && str(val).trim() && !(key in mapped)) mapped[key] = str(val).trim();
      }
      if (!('hop_dong' in mapped) && 'so_ht' in mapped) mapped.hop_dong = mapped.so_ht;
      const link = (mapped.link_bai || '').trim();
      const noiDung = (mapped.noi_dung_khoan_muc || '').trim();
      if (!link && !noiDung) continue;
      items.push({
        hop_dong: mapped.hop_dong || '',
        nhan_hang: mapped.nhan_hang || '',
        chien_dich: mapped.chien_dich || '',
        noi_dung_khoan_muc: noiDung || link,
        link_bai: link || noiDung,
        loai: normalizeLoai(mapped.loai) || detectArticleType(link),
        don_vi: mapped.don_vi || 'Bài',
        so_luong: mapped.so_luong || '1',
        ngay_dang: formatDateString(mapped.ngay_dang || ''),
      });
    }
    const itemsWithUrl = items.filter(it => isUrl(it.link_bai || ''));
    return itemsWithUrl.length ? itemsWithUrl : items;
  }

  /** Chuẩn hoá giá trị cột Loại về 'Facebook' / 'Báo chí' (UI chỉ hỗ trợ 2 loại). */
  function normalizeLoai(v) {
    if (!v) return '';
    const n = removeVietnameseDiacritics(v).trim().toLowerCase();
    if (['facebook', 'fb', 'fanpage', 'group', 'social'].some(k => n.includes(k))) return 'Facebook';
    return 'Báo chí';
  }

  // Bảng kê mẫu dùng cặp alias header → chuyển rows (mảng) thành dict theo header
  function rowsToDicts(allRows, headerIdx) {
    const headers = allRows[headerIdx];
    const out = [];
    for (const row of allRows.slice(headerIdx + 1)) {
      if (row.some(c => str(c).trim())) {
        const d = {};
        const n = Math.min(headers.length, row.length);
        for (let i = 0; i < n; i++) {
          // Python dict: header trùng tên → giá trị sau ghi đè giá trị trước
          d[headers[i]] = row[i];
        }
        out.push(d);
      }
    }
    return out;
  }

  function findHeaderRow(allRows) {
    let headerIdx = -1, best = 0;
    allRows.slice(0, 25).forEach((row, idx) => {
      let matches = 0;
      for (const cell of row) if (mapColumnName(cell) !== null) matches++;
      if (matches > best) { best = matches; headerIdx = idx; }
    });
    return { headerIdx, best };
  }

  const KNOWN_DOMAINS = ['facebook.com', 'fb.com', 'fb.watch', 'kenh14.vn', 'vnexpress.net',
    'dantri.com.vn', 'znews.vn', 'tuoitre.vn', 'thanhnien.vn',
    'vietnamnet.vn', 'vtv.vn', '24h.com.vn', 'laodong.vn', 'tienphong.vn'];

  function isUrl(val) {
    if (!val) return false;
    const v = val.trim().toLowerCase();
    if (/^(https?:\/\/|www\.)/.test(v)) return true;
    if (KNOWN_DOMAINS.some(d => v.includes(d))) return true;
    if (/https?:\/\/[^\s]+/i.test(val)) return true;
    if (/\b[\w\-]+\.(com|vn|net|org|gov|edu|me|co|info|tv|io|site|online)(?:\/[^\s]*)?$/.test(v)) return true;
    return false;
  }
  function isDate(val) {
    if (!val) return false;
    return /^\s*\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}\s*$/.test(val) || /^\s*\d{4}[\/\-.]\d{1,2}[\/\-.]\d{1,2}\s*$/.test(val);
  }
  function isUnit(val) {
    if (!val) return false;
    const v = removeVietnameseDiacritics(val).trim().toLowerCase();
    return ['bai', 'post', 'suat', 'goi', 'tap', 'lan', 'clip', 'video', 'banner', 'trang', 'unit'].includes(v);
  }
  function isType(val) {
    if (!val) return false;
    const v = removeVietnameseDiacritics(val).trim().toLowerCase();
    return ['bao chi', 'facebook', 'fb', 'social', 'fanpage', 'group', 'youtube', 'tiktok'].includes(v);
  }
  function isQty(val) {
    if (!val) return false;
    const v = val.trim();
    return isDigits(v) && +v >= 1 && +v <= 999;
  }

  function parseRowsWithoutHeaders(allRows, metadata) {
    if (!allRows.length) return [];
    const dataRows = [];
    for (const row of allRows) {
      const cells = row.map(c => str(c).trim());
      if (!cells.some(Boolean)) continue;
      const hasUrl = cells.some(isUrl);
      const headerMatches = cells.filter(c => mapColumnName(c) !== null).length;
      if (!hasUrl && headerMatches >= 2) continue;
      const rowStr = cells.join(' ');
      if (['Bên A:', 'Ben A:', 'Bên B:', 'Người đại diện'].some(k => rowStr.includes(k))) continue;
      dataRows.push(row.map(str));
    }
    if (!dataRows.length) return [];

    const maxCols = Math.max(...dataRows.map(r => r.length));
    const colInfo = {};
    for (let c = 0; c < maxCols; c++) {
      const vals = dataRows.filter(r => c < r.length && r[c].trim()).map(r => r[c].trim());
      const n = vals.length;
      if (!n) { colInfo[c] = { empty: true }; continue; }
      const cnt = fn => vals.filter(fn).length;
      colInfo[c] = {
        empty: false, vals,
        url: cnt(isUrl) / n, date: cnt(isDate) / n, unit: cnt(isUnit) / n,
        type: cnt(isType) / n, qty: cnt(isQty) / n,
        finance: (cnt(v => v.includes('%')) / n > 0.3) || (cnt(v => isDigits(v) && +v >= 1000) / n > 0.3),
        avgLen: vals.reduce((s, v) => s + v.length, 0) / n,
      };
    }
    const pick = (field, exclude) => {
      let best = 0, col = null;
      for (let c = 0; c < maxCols; c++) {
        const info = colInfo[c];
        if (info.empty || exclude.includes(c)) continue;
        if (info[field] > best && info[field] >= 0.3) { best = info[field]; col = c; }
      }
      return col;
    };
    const linkCol = pick('url', []);
    const dateCol = pick('date', [linkCol]);
    const unitCol = pick('unit', [linkCol, dateCol]);
    const typeCol = pick('type', [linkCol, dateCol, unitCol]);
    let sttCol = null;
    if (colInfo[0] && !colInfo[0].empty && colInfo[0].vals.length && colInfo[0].vals.every(isDigits)) sttCol = 0;
    const qtyCol = pick('qty', [linkCol, dateCol, unitCol, typeCol, sttCol]);

    const assigned = new Set([linkCol, dateCol, unitCol, typeCol, qtyCol, sttCol].filter(c => c !== null));
    const textCols = [];
    for (let c = 0; c < maxCols; c++) {
      if (assigned.has(c)) continue;
      const info = colInfo[c] || {};
      if (info.empty || info.finance) continue;
      textCols.push(c);
    }

    let hopDongCol = null, nhanCol = null, chienDichCol = null, noiDungCol = null;
    if (textCols.length) {
      if (dateCol !== null && textCols.includes(dateCol - 1)) noiDungCol = dateCol - 1;
      else if (textCols.includes(5)) noiDungCol = 5;
      else if (textCols.includes(4) && sttCol === null) noiDungCol = 4;
      else noiDungCol = textCols.reduce((a, b) => (colInfo[b].avgLen > colInfo[a].avgLen ? b : a));

      const remaining = textCols.filter(c => c !== noiDungCol);
      if (sttCol === 0) {
        if (remaining.includes(1)) hopDongCol = 1;
        if (remaining.includes(3)) nhanCol = 3;
        if (remaining.includes(4) && noiDungCol !== 4) chienDichCol = 4;
      } else if (sttCol === null) {
        if (remaining.includes(0)) hopDongCol = 0;
        if (remaining.includes(2)) nhanCol = 2;
        if (remaining.includes(3) && noiDungCol !== 3) chienDichCol = 3;
      }
      for (const c of remaining.filter(c => ![hopDongCol, nhanCol, chienDichCol].includes(c))) {
        if (hopDongCol === null) hopDongCol = c;
        else if (nhanCol === null) nhanCol = c;
        else if (chienDichCol === null) chienDichCol = c;
      }
    }

    const items = [];
    for (const r of dataRows) {
      const get = c => (c !== null && c < r.length ? r[c].trim() : '');
      let link = get(linkCol), noiDung = get(noiDungCol);
      if (!link && !noiDung) {
        for (const cell of r) {
          const s = cell.trim();
          if (isUrl(s)) link = s;
          else if (s.length > 2 && !isDate(s) && !isDigits(s) && !noiDung) noiDung = s;
        }
      }
      if (!link && !noiDung) continue;
      items.push({
        hop_dong: get(hopDongCol) || metadata.hop_dong || '',
        nhan_hang: get(nhanCol) || metadata.nhan_hang || '',
        chien_dich: get(chienDichCol) || metadata.chien_dich || '',
        noi_dung_khoan_muc: noiDung || link,
        link_bai: link || noiDung,
        loai: normalizeLoai(get(typeCol)) || detectArticleType(link),
        don_vi: get(unitCol) || 'Bài',
        so_luong: get(qtyCol) || '1',
        ngay_dang: formatDateString(get(dateCol)),
      });
    }
    return items;
  }

  /** CSV parser chuẩn RFC-4180 (hỗ trợ ô có xuống dòng trong dấu nháy). */
  function parseCSV(text, delim) {
    const rows = [];
    let row = [], field = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') {
          if (text[i + 1] === '"') { field += '"'; i++; } else q = false;
        } else field += c;
        continue;
      }
      if (c === '"' && field === '') { q = true; continue; }
      if (c === delim) { row.push(field); field = ''; continue; }
      if (c === '\r') continue;
      if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; continue; }
      field += c;
    }
    if (field !== '' || row.length) { row.push(field); rows.push(row); }
    return rows;
  }

  function parseTableRows(allRows) {
    if (!allRows.length) return { items: [], metadata: {} };
    const metadata = extractHeaderMetadata(allRows);
    const { headerIdx, best } = findHeaderRow(allRows);
    if (headerIdx !== -1 && best >= 1) {
      const items = parseRowsData(rowsToDicts(allRows, headerIdx));
      return { items, metadata, viaHeader: true };
    }
    return { items: parseRowsWithoutHeaders(allRows, metadata), metadata };
  }

  /** Dữ liệu dán từ Clipboard (Google Sheet / Excel). */
  function parseClipboardText(text) {
    if (!text || !text.trim()) return { items: [], metadata: {} };
    const trimmed = text.replace(/^\s+|\s+$/g, '');
    const firstLine = trimmed.split(/\r?\n/).find(l => l.trim()) || '';
    let delim = '\t';
    if (!firstLine.includes('\t')) {
      if (firstLine.includes(',')) delim = ',';
      else if (firstLine.includes(';')) delim = ';';
    }
    const allRows = parseCSV(trimmed, delim).filter(r => r.some(c => c.trim()));
    if (!allRows.length) return { items: [], metadata: {} };
    const metadata = extractHeaderMetadata(allRows);
    const { headerIdx, best } = findHeaderRow(allRows);
    if (headerIdx !== -1 && best >= 1) {
      const items = parseRowsData(rowsToDicts(allRows, headerIdx));
      if (items.length && items.some(i => i.link_bai && (i.link_bai.includes('http') || i.link_bai.includes('.'))))
        return { items, metadata };
    }
    return { items: parseRowsWithoutHeaders(allRows, metadata), metadata };
  }

  /** Giải mã file CSV/TSV (thử nhiều encoding giống bản Python). */
  function decodeTextFile(bytes) {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
    if (u8[0] === 0xFF && u8[1] === 0xFE) return new TextDecoder('utf-16le').decode(u8.subarray(2));
    if (u8[0] === 0xFE && u8[1] === 0xFF) return new TextDecoder('utf-16be').decode(u8.subarray(2));
    try {
      let t = new TextDecoder('utf-8', { fatal: true }).decode(u8);
      if (t.charCodeAt(0) === 0xFEFF) t = t.slice(1);
      return t;
    } catch (_) {
      return new TextDecoder('windows-1252').decode(u8);
    }
  }

  function parseDelimitedFile(bytes) {
    const content = decodeTextFile(bytes);
    if (!content) throw new Error('Không đọc được mã hoá file CSV/TSV.');
    const tabs = (content.match(/\t/g) || []).length, commas = (content.match(/,/g) || []).length;
    const delim = tabs && tabs > commas ? '\t' : ',';
    return parseTableRows(parseCSV(content, delim));
  }

  // ─── Đọc XLSX (tự viết, dùng JSZip — không cần SheetJS) ───
  const BUILTIN_DATE_FMTS = new Set([14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58]);

  function colToIndex(letters) {
    let n = 0;
    for (const ch of letters) n = n * 26 + (ch.charCodeAt(0) - 64);
    return n - 1;
  }

  async function readXlsxRows(bytes, JSZipLib) {
    const zip = await JSZipLib.loadAsync(bytes);
    const parse = async path => {
      const f = zip.file(path);
      if (!f) return null;
      return new DOMParser().parseFromString(await f.async('string'), 'application/xml');
    };
    const byTag = (doc, tag) => Array.from(doc.getElementsByTagNameNS('*', tag));
    const wb = await parse('xl/workbook.xml');
    if (!wb) throw new Error('File Excel không hợp lệ (thiếu workbook.xml). Nếu là file .xls cũ, hãy lưu lại dạng .xlsx hoặc .csv.');
    const date1904 = byTag(wb, 'workbookPr').some(e => ['1', 'true'].includes(e.getAttribute('date1904')));
    const sheets = byTag(wb, 'sheet');
    const view = byTag(wb, 'workbookView')[0];
    const active = Math.min(+(view && view.getAttribute('activeTab')) || 0, sheets.length - 1);
    const sheetEl = sheets[active];
    const rid = sheetEl.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id') || sheetEl.getAttribute('r:id');
    const rels = await parse('xl/_rels/workbook.xml.rels');
    let target = 'worksheets/sheet1.xml';
    if (rels) {
      const rel = byTag(rels, 'Relationship').find(r => r.getAttribute('Id') === rid);
      if (rel) target = rel.getAttribute('Target');
    }
    const sheetPath = target.startsWith('/') ? target.slice(1) : 'xl/' + target.replace(/^\.\//, '');

    // Shared strings
    const sst = [];
    const ss = await parse('xl/sharedStrings.xml');
    if (ss) for (const si of byTag(ss, 'si')) {
      sst.push(Array.from(si.getElementsByTagNameNS('*', 't'))
        .filter(t => !(t.parentNode && t.parentNode.localName === 'rPh'))
        .map(t => t.textContent).join(''));
    }

    // Styles → xf index là ngày tháng?
    const dateXf = [];
    const st = await parse('xl/styles.xml');
    if (st) {
      const custom = {};
      for (const nf of byTag(st, 'numFmt')) custom[+nf.getAttribute('numFmtId')] = nf.getAttribute('formatCode') || '';
      const cellXfs = byTag(st, 'cellXfs')[0];
      if (cellXfs) for (const xf of Array.from(cellXfs.children).filter(e => e.localName === 'xf')) {
        const id = +xf.getAttribute('numFmtId') || 0;
        let isD = BUILTIN_DATE_FMTS.has(id);
        if (!isD && custom[id]) {
          const code = custom[id].replace(/"[^"]*"/g, '').replace(/\[[^\]]*\]/g, '').replace(/\\./g, '');
          isD = /[dy]/i.test(code) || /m/i.test(code) && /[hs:]/i.test(code) === false && /^[\sdmy\/\-.,]+$/i.test(code);
        }
        dateXf.push(isD);
      }
    }

    const sheet = await parse(sheetPath);
    if (!sheet) throw new Error('Không tìm thấy sheet dữ liệu trong file Excel.');
    const grid = [];
    let maxCol = 0;
    for (const rowEl of byTag(sheet, 'row')) {
      const rIdx = (+rowEl.getAttribute('r') || grid.length + 1) - 1;
      const row = grid[rIdx] || (grid[rIdx] = []);
      let autoCol = 0;
      for (const c of Array.from(rowEl.children).filter(e => e.localName === 'c')) {
        const ref = c.getAttribute('r');
        const ci = ref ? colToIndex(ref.replace(/\d+/g, '')) : autoCol;
        autoCol = ci + 1;
        const t = c.getAttribute('t');
        const vEl = Array.from(c.children).find(e => e.localName === 'v');
        const v = vEl ? vEl.textContent : '';
        let out = '';
        if (t === 's') out = sst[+v] || '';
        else if (t === 'inlineStr') out = Array.from(c.getElementsByTagNameNS('*', 't')).map(x => x.textContent).join('');
        else if (t === 'b') out = v === '1' ? 'True' : 'False';
        else if (t === 'str' || t === 'e') out = v;
        else if (v !== '') {
          const num = Number(v);
          const s = +c.getAttribute('s') || 0;
          if (dateXf[s] && isFinite(num)) {
            const base = date1904 ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, 30);
            const dt = new Date(base + Math.round(num * 86400000));
            out = `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
          } else out = isFinite(num) ? String(num) : v;
        }
        row[ci] = out;
        if (ci + 1 > maxCol) maxCol = ci + 1;
      }
    }
    const rows = [];
    for (let i = 0; i < grid.length; i++) {
      const r = grid[i] || [];
      const full = [];
      for (let c = 0; c < maxCol; c++) full.push(r[c] == null ? '' : r[c]);
      rows.push(full);
    }
    return rows;
  }

  async function parseTableFile(fileName, bytes, JSZipLib) {
    const ext = (fileName.split('.').pop() || '').toLowerCase();
    if (ext === 'xls') throw new Error('Định dạng .xls (Excel 97-2003) không được hỗ trợ. Vui lòng lưu lại dạng .xlsx hoặc .csv.');
    if (ext === 'xlsx') return parseTableRows(await readXlsxRows(bytes, JSZipLib));
    return parseDelimitedFile(bytes);
  }

  // ══════════════════════════════════════════════
  // image_processor.py — phân trang ảnh dài khổ A4
  // ══════════════════════════════════════════════
  /**
   * Tính điểm cắt cân bằng, căn vào dải pixel trắng (không cắt ngang chữ).
   * @param {Float32Array} rowWhite tỷ lệ pixel trắng của từng dòng
   * @param {number} height chiều cao ảnh (px)
   * @param {number} maxPage chiều cao tối đa mỗi trang (px)
   * @param {number} scale px vật lý / px CSS
   */
  function computeWhitespaceCuts(rowWhite, height, maxPage, scale) {
    if (height <= maxPage) return [0, height];
    const cuts = [0];
    let yStart = 0;
    let guard = 0;
    while (height - yStart > maxPage && guard++ < 1000) {
      const remaining = height - yStart;
      const pagesLeft = Math.ceil(remaining / maxPage);
      const step = Math.min(Math.ceil(remaining / pagesLeft), maxPage);
      const target = yStart + step;
      const searchStart = Math.max(yStart + Math.floor(step * 0.65), target - Math.round(350 * scale));
      let searchEnd = Math.min(yStart + maxPage, target + Math.round(200 * scale));
      searchEnd = Math.min(searchEnd, height - 50);
      let bestY = target, bestScore = -1;
      for (let y = searchEnd; y > searchStart; y--) {
        const y0 = Math.max(0, y - 2), y1 = Math.min(height, y + 3);
        let sum = 0;
        for (let k = y0; k < y1; k++) sum += rowWhite[k];
        const band = sum / (y1 - y0);
        if (band >= 0.97) { bestY = y; bestScore = band; break; }
        if (band > bestScore) { bestScore = band; bestY = y; }
      }
      if (bestY <= yStart) bestY = Math.min(yStart + maxPage, height);
      cuts.push(bestY);
      yStart = bestY;
    }
    if (cuts[cuts.length - 1] !== height) cuts.push(height);
    return cuts;
  }

  const api = {
    CONFIG, HIDE_ADS_CSS,
    removeVietnameseDiacritics, sanitizeFilename, parseDMY, todayDMY, generateOutputFilename, ensureUniqueFilename,
    normalizeText, mapColumnName, formatDateString, detectArticleType, extractHeaderMetadata,
    parseRowsData, parseRowsWithoutHeaders, parseCSV, parseTableRows, parseClipboardText,
    parseDelimitedFile, decodeTextFile, readXlsxRows, parseTableFile, isUrl,
    computeWhitespaceCuts,
  };
  root.CNPSCore = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
