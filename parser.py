"""
Parser TXT rekening koran VABCA + parsing NO.VA + hitung TP & bulan.
"""
import re
import pandas as pd


def parse_amount(raw: str) -> float:
    """Format Indonesia (1.234,56) atau US (1,234.56)."""
    raw = raw.strip()
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            return float(raw.replace(".", "").replace(",", "."))
        return float(raw.replace(",", ""))
    if "," in raw:
        tail = raw.split(",")[-1]
        if len(tail) == 2:
            return float(raw.replace(",", "."))
        return float(raw.replace(",", ""))
    return float(raw.replace(".", ""))


def parse_no_va(no_va: str) -> dict:
    """Urai NO.VA dari belakang: prefix + kode sekolah + kode bayar."""
    no_va = (no_va or "").strip()
    result = {"prefix_va": "", "kode_sekolah": "", "kode_bayar": ""}
    if len(no_va) < 6:
        return result
    result["kode_bayar"] = no_va[-2:]
    result["kode_sekolah"] = no_va[-4:-2]
    result["prefix_va"] = no_va[:2]
    return result


def hitung_tahun_bayar(prefix: str, date_str: str) -> str:
    """
    Hitung TP:
      - Prefix selain '00' → dari prefix ('25' → '2025-2026')
      - Prefix '00' → dari tanggal (aturan Juli–Juni)
    """
    if prefix and prefix != "00" and prefix.isdigit():
        th = int("20" + prefix)
        return f"{th}-{th + 1}"
    try:
        d = pd.to_datetime(date_str, format="%d/%m/%Y")
    except (ValueError, TypeError):
        return ""
    tahun_awal = d.year if d.month >= 7 else d.year - 1
    return f"{tahun_awal}-{tahun_awal + 1}"


def hitung_bulan_tp(prefix: str, date_str: str) -> int:
    """
    Nomor bulan dalam TP (1=Juli, 12=Juni).
      - Prefix selain '00' → selalu 1 (Juli, awal TP)
      - Prefix '00' → sesuai bulan transaksi asli
    """
    if prefix and prefix != "00":
        return 1
    try:
        d = pd.to_datetime(date_str, format="%d/%m/%Y")
    except (ValueError, TypeError):
        return 0
    return d.month - 6 if d.month >= 7 else d.month + 6


def nama_bulan_tp(bulan_ke: int) -> str:
    """Konversi 1–12 ke nama bulan ('Jul', 'Ags', ..., 'Jun')."""
    names = ["Jul", "Ags", "Sep", "Okt", "Nov", "Des",
             "Jan", "Feb", "Mar", "Apr", "Mei", "Jun"]
    if 1 <= bulan_ke <= 12:
        return names[bulan_ke - 1]
    return ""


def parse_txt_content(content: bytes, file_name: str) -> tuple[pd.DataFrame, int]:
    """Parse file TXT → DataFrame + jumlah baris terlewat."""
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()

    rows = []
    sub_comp = ""
    skipped = 0

    match = re.search(r"R-5401_(\d{5})_", file_name)
    comp_code = match.group(1) if match else ""

    for line in lines:
        m_sc = re.search(r"SUB-COMP\s+(\d+)", line)
        if m_sc:
            sub_comp = m_sc.group(1)
            continue

        m = re.match(
            r"^\s*\d+\s+(\d{8,})\s+(.{1,24}?)\s+IDR\s+([\d\.,]+)\s+"
            r"(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+\S+\s+(.*\S)?\s*$",
            line,
        )
        if not m:
            if line.strip():
                skipped += 1
            continue

        no_va = m.group(1).strip()
        nama = m.group(2).rstrip()
        amount = parse_amount(m.group(3))
        date = pd.to_datetime(m.group(4), format="%d/%m/%y").strftime("%d/%m/%Y")
        time = m.group(5)
        tail = (m.group(6) or "")
        tail = re.sub(r"\d+", " ", tail).replace("-", " ")
        tail = re.sub(r"\s+", " ", tail).strip()
        remark = f"{nama} {tail}".strip()

        va = parse_no_va(no_va)
        tahun_bayar = hitung_tahun_bayar(va["prefix_va"], date)
        bulan_tp = hitung_bulan_tp(va["prefix_va"], date)

        rows.append([
            comp_code, sub_comp, no_va, remark, "IDR", amount, date, time,
            file_name,
            va["prefix_va"], tahun_bayar, bulan_tp,
            va["kode_sekolah"], va["kode_bayar"],
        ])

    df = pd.DataFrame(rows, columns=[
        "company_code", "subcompany", "no_va", "remark", "mata_uang", "credit",
        "date", "time", "asal_file",
        "prefix_va", "tahun_bayar", "bulan_tp", "kode_sekolah", "kode_bayar",
    ])
    return df, skipped
