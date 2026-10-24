import streamlit as st
import pandas as pd
import re
import os
import random
from io import BytesIO

st.set_page_config(page_title="VABCA Converter", layout="wide")

def parse_txt_to_df(path: str, file_name: str) -> pd.DataFrame:
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    rows = []
    sub_comp = None

    # Ambil 5 digit dari nama file
    match = re.search(r"R-5401_(\d{5})_", file_name)
    comp_code = match.group(1) if match else ""

    for line in lines:
        # Cek SUB-COMP
        m_sc = re.search(r"SUB-COMP\s+(\d+)", line)
        if m_sc:
            sub_comp = m_sc.group(1)
            continue

        # Cek baris transaksi
        m = re.match(
            r"^\s*\d+\s+(\d{8,})\s+(.{1,24}?)\s+IDR\s+([\d\.,]+)\s+"
            r"(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+\S+\s+(.*\S)?\s*$",
            line
        )
        if not m:
            continue

        no_va = m.group(1).strip()
        nama = m.group(2).rstrip()
        amount = float(m.group(3).replace(",", ""))
        date_raw = m.group(4)
        time = m.group(5)
        # ubah jadi tahun 4 digit
        date = pd.to_datetime(date_raw, format="%d/%m/%y").strftime("%d/%m/%Y")
        tail = (m.group(6) or "")

        # Bersihkan tail
        tail = re.sub(r"\d+", " ", tail).replace("-", " ")
        tail = re.sub(r"\s+", " ", tail).strip()

        remark = f"{nama} {tail}".strip()

        rows.append([comp_code, sub_comp, no_va, remark, "IDR", amount, date, time, file_name])

    return pd.DataFrame(
        rows,
        columns=[ "COMPANY CODE", "SUBCOMPANY", "NO.VA", "REMARK", "MATA UANG", "CREDIT", "DATE", "TIME", "ASAL_FILE"]
    )

# ========================= STREAMLIT APP =========================

st.title("🏦 Pemisah Transaksi VABCA")
# tampilkan nama Anda di layar
st.markdown("👩‍💻 Created by **Tri**©2025")

# init state
if "data_ready" not in st.session_state:
    st.session_state.data_ready = False
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = random.randint(0, 1_000_000)

uploaded_files = st.file_uploader(
    "Upload file TXT rekening koran",
    type="txt",
    accept_multiple_files=True,
    key=st.session_state.uploader_key
)

if uploaded_files and not st.session_state.data_ready:
    all_data = []
    for uploaded in uploaded_files:
        tmp_path = os.path.join("/tmp", uploaded.name)
        with open(tmp_path, "wb") as f:
            f.write(uploaded.read())
        df = parse_txt_to_df(tmp_path, uploaded.name)
        all_data.append(df)

    if all_data:
        final_df = pd.concat(all_data, ignore_index=True)
        st.session_state.final_df = final_df
        st.session_state.data_ready = True

if st.session_state.data_ready:
    final_df = st.session_state.final_df

    st.success(f"✅ Berhasil memproses {len(uploaded_files)} file. Total {len(final_df)} transaksi.")
    st.dataframe(final_df.head(20))

    # Save ke Excel in-memory
    buffer = BytesIO()
    final_df.to_excel(buffer, index=False)
    buffer.seek(0)

    st.download_button(
        label="⬇️ Download Excel",
        data=buffer,
        file_name="rekening_koran_all.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Tombol reset
    if st.button("🔄 Reset"):
        st.session_state.clear()
        st.session_state.uploader_key = random.randint(0, 1_000_000)
        st.rerun()

# ---------- Kredit tetap di kiri bawah ----------
st.markdown(
    """
    <style>
    .kredit-fixed {
        position: fixed;
        left: 12px;
        bottom: 12px;
        z-index: 9999;
        color: rgba(100,100,100,0.9);
        font-size: 13px;
        background: rgba(255,255,255,0.6);
        padding: 4px 8px;
        border-radius: 6px;
        backdrop-filter: blur(4px);
        pointer-events: none;
    }
    </style>
    <div class="kredit-fixed">© 2025 Created by Tri 👩‍💻
    💖 Pay Now‼️👉 shopeepay BRI: 112-08175229969
    Terima kasih banyak atas dukunganmu! 🙏</div>
    """,
    unsafe_allow_html=True
)






