"""
Aplikasi Streamlit: VABCA Converter & Dashboard Laporan.
Mode: LOKAL (SQLite aman, tidak ephemeral).
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

import db
from parser import parse_txt_content, nama_bulan_tp
from excel_helper import to_excel, pivot_to_excel

st.set_page_config(
    page_title="VABCA Dashboard",
    page_icon="🏦",
    layout="wide",
)

db.init_db()

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

st.title("🏦 VABCA Dashboard & Converter")
st.markdown("👩‍💻 Created by **Tri**©2025")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def enrich_df(df: pd.DataFrame) -> pd.DataFrame:
    """Tambah kolom nama sekolah, nama bayar, kategori dari master."""
    if df.empty:
        return df
    m_sekolah = db.load_master("master_sekolah").set_index("kode")["nama"].to_dict() \
        if not db.load_master("master_sekolah").empty else {}
    m_bayar = db.load_master("master_bayar").set_index("kode")["nama"].to_dict() \
        if not db.load_master("master_bayar").empty else {}
    m_kat = db.load_master("master_kategori").set_index("prefix_va")["kategori"].to_dict() \
        if not db.load_master("master_kategori").empty else {}

    df = df.copy()
    df["nama_sekolah"] = df["kode_sekolah"].map(m_sekolah).fillna("(?)")
    df["nama_bayar"] = df["kode_bayar"].map(m_bayar).fillna("(?)")
    df["kategori"] = df["prefix_va"].map(m_kat).fillna("(?)")
    df["bulan_nama"] = df["bulan_tp"].apply(nama_bulan_tp)
    return df


def apply_filters(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """Tampilkan filter di sidebar-like dan kembalikan df terfilter."""
    if df.empty:
        return df

    st.markdown("#### 🔎 Filter")
    c1, c2, c3 = st.columns(3)

    tp_opts = sorted(df["tahun_bayar"].dropna().unique())
    f_tp = c1.multiselect("TP (Tahun Bayar)", tp_opts, default=tp_opts,
                          key=f"{key_prefix}_tp")

    comp_opts = sorted(df["company_code"].dropna().unique())
    f_comp = c2.multiselect("Company Code", comp_opts, default=comp_opts,
                            key=f"{key_prefix}_comp")

    kat_opts = sorted(df["kategori"].dropna().unique())
    f_kat = c3.multiselect("Kategori", kat_opts, default=kat_opts,
                           key=f"{key_prefix}_kat")

    c4, c5 = st.columns(2)
    sek_opts = sorted(df["nama_sekolah"].dropna().unique())
    f_sek = c4.multiselect("Sekolah", sek_opts, default=sek_opts,
                           key=f"{key_prefix}_sek")

    bayar_opts = sorted(df["nama_bayar"].dropna().unique())
    f_bayar = c5.multiselect("Jenis Bayar", bayar_opts, default=bayar_opts,
                             key=f"{key_prefix}_bayar")

    return df[
        df["tahun_bayar"].isin(f_tp)
        & df["company_code"].isin(f_comp)
        & df["kategori"].isin(f_kat)
        & df["nama_sekolah"].isin(f_sek)
        & df["nama_bayar"].isin(f_bayar)
    ]
    # ============================================================
# TAB 1: UPLOAD
# ============================================================

tab_upload, tab_dashboard, tab_laporan, tab_master = st.tabs(
    ["📤 Upload", "📊 Dashboard", "📈 Laporan", "⚙️ Master Data"]
)

with tab_upload:
    st.subheader("📤 Upload File TXT Rekening Koran")

    uploaded_files = st.file_uploader(
        "Pilih file TXT (bisa banyak sekaligus)",
        type="txt",
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}",
    )

    if uploaded_files:
        existing = db.get_existing_files()
        new_files = [f for f in uploaded_files if f.name not in existing]
        dup_files = [f for f in uploaded_files if f.name in existing]

        col1, col2, col3 = st.columns(3)
        col1.metric("📄 Total file", len(uploaded_files))
        col2.metric("🆕 File baru", len(new_files))
        col3.metric("♻️ Duplikat", len(dup_files))

        mode_duplikat = "skip"
        if dup_files:
            st.warning(
                f"⚠️ {len(dup_files)} file sudah ada di database: "
                + ", ".join(f.name for f in dup_files[:5])
                + (" ..." if len(dup_files) > 5 else "")
            )
            mode_duplikat = st.radio(
                "Apa yang dilakukan dengan file duplikat?",
                options=["skip", "replace", "tolak"],
                format_func=lambda x: {
                    "skip": "⏭️ Skip (abaikan file duplikat)",
                    "replace": "🔄 Replace (hapus lama, masukkan baru)",
                    "tolak": "❌ Tolak (batalkan semua upload)",
                }[x],
                horizontal=True,
                key=f"mode_dup_{st.session_state.uploader_key}",
            )

        st.markdown("### 👀 Preview")
        preview_rows = []
        preview_skipped = 0
        for f in uploaded_files:
            content = f.getvalue()
            df, skipped = parse_txt_content(content, f.name)
            preview_rows.append(df.head(3))
            preview_skipped += skipped

        if preview_rows:
            preview_df = pd.concat(preview_rows, ignore_index=True)
            preview_df = enrich_df(preview_df)
            st.dataframe(
                preview_df[[
                    "date", "company_code", "no_va", "remark",
                    "tahun_bayar", "bulan_nama", "kategori", "credit",
                ]],
                column_config={
                    "credit": st.column_config.NumberColumn(format="Rp %,.0f"),
                },
                use_container_width=True,
                hide_index=True,
            )
            if preview_skipped:
                st.info(f"ℹ️ {preview_skipped} baris tidak cocok pola (akan dilewati).")

        if st.button("💾 Simpan ke Database", type="primary", key="btn_simpan"):
            if mode_duplikat == "tolak" and dup_files:
                st.error("❌ Upload dibatalkan karena ada file duplikat.")
            else:
                saved = replaced = total_rows = 0
                progress = st.progress(0.0, text="Memproses...")

                for i, f in enumerate(uploaded_files, 1):
                    is_dup = f.name in existing
                    if is_dup and mode_duplikat == "skip":
                        progress.progress(i / len(uploaded_files))
                        continue

                    content = f.getvalue()
                    df, _ = parse_txt_content(content, f.name)
                    if df.empty:
                        progress.progress(i / len(uploaded_files))
                        continue

                    db.insert_transaksi(df, f.name, content)
                    total_rows += len(df)
                    if is_dup:
                        replaced += 1
                    else:
                        saved += 1
                    progress.progress(i / len(uploaded_files),
                                      text=f"{i}/{len(uploaded_files)}")

                progress.empty()
                st.success(
                    f"✅ Selesai! {saved} file baru, {replaced} file diganti. "
                    f"Total {total_rows} transaksi tersimpan."
                )
                st.session_state.uploader_key += 1
                st.rerun()

    # ===== Backup & Restore =====
    st.divider()
    st.subheader("💾 Backup & Restore Database")
    st.caption(
        "Backup rutin disarankan. Simpan file `.db` ke flashdisk / Google Drive."
    )

    col_a, col_b = st.columns(2)
    with col_a:
        backup = db.backup_db_bytes()
        if backup:
            st.download_button(
                "⬇️ Download Backup (.db)",
                data=backup,
                file_name=f"laporan_{datetime.now():%Y%m%d_%H%M}.db",
                mime="application/octet-stream",
                use_container_width=True,
            )
    with col_b:
        restore_file = st.file_uploader(
            "Upload file .db untuk restore",
            type="db",
            key="restore_uploader",
        )
        if restore_file and st.button("♻️ Restore (timpa database)"):
            db.restore_db(restore_file.getvalue())
            st.success("✅ Database berhasil di-restore!")
            st.rerun()

# ============================================================
# TAB 2: DASHBOARD
# ============================================================

with tab_dashboard:
    st.subheader("📊 Dashboard Ringkasan")

    df = db.load_all_transaksi()

    if df.empty:
        st.info("📭 Belum ada data. Silakan upload di tab **Upload**.")
    else:
        df = enrich_df(df)

        # KPI
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("💰 Total Nominal", f"Rp {df['credit'].sum():,.0f}")
        k2.metric("🧾 Total Transaksi", f"{len(df):,}")
        k3.metric("🆔 VA Unik", f"{df['no_va'].nunique():,}")
        k4.metric("📅 Jumlah TP", df["tahun_bayar"].nunique())

        st.divider()

        # Tren per bulan transaksi
        st.markdown("### 📈 Tren Nominal per Bulan Transaksi")
        tren = (
            df.groupby("bulan")
            .agg(Nominal=("credit", "sum"), Jumlah=("no_va", "count"))
            .reset_index()
            .sort_values("bulan")
        )
        fig = px.bar(
            tren, x="bulan", y="Nominal",
            text="Jumlah",
            labels={"bulan": "Bulan Transaksi", "Nominal": "Nominal (Rp)"},
        )
        fig.update_traces(texttemplate="%{text:,}", textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # Top sekolah & distribusi kategori
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("### 🏫 Top 10 Sekolah (Nominal)")
            top_sek = (
                df.groupby("nama_sekolah")["credit"].sum()
                .sort_values(ascending=False).head(10).reset_index()
            )
            if not top_sek.empty:
                fig = px.bar(
                    top_sek, x="credit", y="nama_sekolah", orientation="h",
                    labels={"credit": "Nominal", "nama_sekolah": ""},
                )
                st.plotly_chart(fig, use_container_width=True)

        with c2:
            st.markdown("### 🥧 Distribusi Kategori")
            dist = df.groupby("kategori")["credit"].sum().reset_index()
            if not dist.empty:
                fig = px.pie(dist, names="kategori", values="credit", hole=0.5)
                st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # Tren per TP
        st.markdown("### 📈 Nominal per TP (Tahun Bayar)")
        tren_tp = (
            df.groupby("tahun_bayar")
            .agg(Nominal=("credit", "sum"), Jumlah=("no_va", "count"))
            .reset_index()
            .sort_values("tahun_bayar")
        )
        fig = px.bar(
            tren_tp, x="tahun_bayar", y="Nominal", text="Jumlah",
            labels={"tahun_bayar": "TP", "Nominal": "Nominal (Rp)"},
        )
        fig.update_traces(texttemplate="%{text:,}", textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TAB 4: MASTER DATA
# ============================================================

with tab_master:
    st.subheader("⚙️ Master Data")
    st.caption(
        "Isi mapping kode → nama agar dashboard menampilkan nama yang jelas. "
        "Bisa upload CSV/Excel atau isi manual."
    )

    # --- Master Sekolah ---
    st.markdown("#### 🏫 Master Sekolah")
    st.caption("Kode sekolah = 2 digit sebelum 2 digit terakhir NO.VA.")

    df_sekolah = db.load_master("master_sekolah")
    col_upload, col_edit = st.columns([1, 3])
    with col_upload:
        up_sek = st.file_uploader(
            "Upload CSV/Excel (kolom: kode, nama)",
            type=["csv", "xlsx"],
            key="up_sekolah",
        )
        if up_sek:
            if up_sek.name.endswith(".csv"):
                df_up = pd.read_csv(up_sek)
            else:
                df_up = pd.read_excel(up_sek)
            if {"kode", "nama"}.issubset(df_up.columns):
                db.upsert_master("master_sekolah", df_up[["kode", "nama"]].dropna())
                st.success("✅ Terupload.")
                st.rerun()
            else:
                st.error("❌ Kolom harus: kode, nama")

    edited_sek = st.data_editor(
        df_sekolah, num_rows="dynamic", use_container_width=True,
        key="edit_sekolah",
        column_config={
            "kode": st.column_config.TextColumn("Kode", width="small"),
            "nama": st.column_config.TextColumn("Nama Sekolah", width="large"),
        },
    )
    if st.button("💾 Simpan Master Sekolah", key="btn_sek"):
        db.upsert_master("master_sekolah", edited_sek.dropna())
        st.success("✅ Tersimpan.")
        st.rerun()

    st.divider()

    # --- Master Jenis Bayar ---
    st.markdown("#### 💳 Master Jenis Bayar")
    st.caption("Kode bayar = 2 digit terakhir NO.VA.")

    df_bayar = db.load_master("master_bayar")
    col_upload, col_edit = st.columns([1, 3])
    with col_upload:
        up_bayar = st.file_uploader(
            "Upload CSV/Excel (kolom: kode, nama)",
            type=["csv", "xlsx"],
            key="up_bayar",
        )
        if up_bayar:
            if up_bayar.name.endswith(".csv"):
                df_up = pd.read_csv(up_bayar)
            else:
                df_up = pd.read_excel(up_bayar)
            if {"kode", "nama"}.issubset(df_up.columns):
                db.upsert_master("master_bayar", df_up[["kode", "nama"]].dropna())
                st.success("✅ Terupload.")
                st.rerun()
            else:
                st.error("❌ Kolom harus: kode, nama")

    edited_bayar = st.data_editor(
        df_bayar, num_rows="dynamic", use_container_width=True,
        key="edit_bayar",
        column_config={
            "kode": st.column_config.TextColumn("Kode", width="small"),
            "nama": st.column_config.TextColumn("Nama Jenis Bayar", width="large"),
        },
    )
    if st.button("💾 Simpan Master Jenis Bayar", key="btn_bayar"):
        db.upsert_master("master_bayar", edited_bayar.dropna())
        st.success("✅ Tersimpan.")
        st.rerun()

    st.divider()

    # --- Master Kategori ---
    st.markdown("#### 🗂️ Master Kategori (per Prefix NO.VA)")
    st.caption(
        "Override kategori default. `00` = Uang Sekolah TP Berjalan, "
        "`25` = SPMB TP 2025-2026, dst."
    )

    df_kat = db.load_master("master_kategori")
    edited_kat = st.data_editor(
        df_kat, num_rows="dynamic", use_container_width=True,
        key="edit_kat",
        column_config={
            "prefix_va": st.column_config.TextColumn("Prefix", width="small"),
            "kategori": st.column_config.TextColumn("Kategori", width="large"),
        },
    )
    if st.button("💾 Simpan Master Kategori", key="btn_kat"):
        db.upsert_master("master_kategori", edited_kat.dropna())
        st.success("✅ Tersimpan.")
        st.rerun()

# ============================================================
# TAB 3: LAPORAN
# ============================================================

with tab_laporan:
    st.subheader("📈 Laporan")

    df = db.load_all_transaksi()

    if df.empty:
        st.info("📭 Belum ada data. Silakan upload di tab **Upload**.")
    else:
        df = enrich_df(df)

        sub_bank, sub_tp, sub_sek_bayar, sub_sek_tp, sub_siswa, sub_detail = st.tabs([
            "📥 Konsolidasi Bank",
            "📤 Konsolidasi per TP",
            "🏫 Sekolah × Jenis Bayar",
            "🏫 Sekolah × TP",
            "🏆 Top Siswa",
            "📋 Detail per Sekolah",
        ])

        # ====================================================
        # SUB 1: KONSOLIDASI BANK
        # ====================================================
        with sub_bank:
            st.markdown("### 📥 Konsolidasi Bank")
            st.caption(
                "Berapa uang yang **masuk ke rekening bank** per bulan transaksi. "
                "Semua prefix (00 / 25 / 26 / ...) digabung."
            )

            df_bank = apply_filters(df, key_prefix="bank")

            if df_bank.empty:
                st.warning("Tidak ada data setelah filter.")
            else:
                # --- Total per bulan trx ---
                st.markdown("#### 💰 Total per Bulan Transaksi")
                tbl_bulan = (
                    df_bank.groupby("bulan")
                    .agg(
                        Nominal=("credit", "sum"),
                        Transaksi=("no_va", "count"),
                        VA_Unik=("no_va", "nunique"),
                    )
                    .reset_index()
                    .sort_values("bulan")
                )
                tbl_bulan.columns = ["Bulan", "Nominal", "Transaksi", "VA Unik"]

                st.dataframe(
                    tbl_bulan,
                    column_config={
                        "Nominal": st.column_config.NumberColumn(format="Rp %,.0f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "⬇️ Download Excel (Total per Bulan)",
                    data=to_excel(
                        tbl_bulan, sheet_name="Bank per Bulan",
                        total_row=True, rp_columns=["Nominal"],
                    ),
                    file_name=f"bank_per_bulan_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_bank_bulan",
                )

                st.divider()

                # --- Breakdown per bulan × TP ---
                st.markdown("#### 💰 Breakdown per Bulan × TP")
                st.caption("Uang yang masuk di bulan tertentu, dialokasikan ke TP mana saja.")

                pivot_bank = df_bank.pivot_table(
                    index="bulan", columns="tahun_bayar",
                    values="credit", aggfunc="sum", fill_value=0,
                ).sort_index()
                pivot_bank["TOTAL"] = pivot_bank.sum(axis=1)
                pivot_bank.loc["TOTAL"] = pivot_bank.sum()

                st.dataframe(
                    pivot_bank.style.format("Rp {:,.0f}"),
                    use_container_width=True,
                )

                st.download_button(
                    "⬇️ Download Excel (Breakdown Bank)",
                    data=pivot_to_excel(
                        pivot_bank.drop(index="TOTAL", errors="ignore")
                        .drop(columns="TOTAL", errors="ignore"),
                        sheet_name="Bank x TP",
                        add_total=True,
                    ),
                    file_name=f"bank_x_tp_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_bank_tp",
                )

        # ====================================================
        # SUB 2: KONSOLIDASI PER TP
        # ====================================================
        with sub_tp:
            st.markdown("### 📤 Konsolidasi per TP")
            st.caption(
                "Berapa total yang terkumpul **untuk TP tertentu**. "
                "Transaksi prefix ≠ 00 selalu masuk B1 (Juli, awal TP)."
            )

            df_tp = apply_filters(df, key_prefix="tp")

            if df_tp.empty:
                st.warning("Tidak ada data setelah filter.")
            else:
                # --- Total per TP ---
                st.markdown("#### 💰 Total per TP")
                tbl_tp = (
                    df_tp.groupby("tahun_bayar")
                    .agg(
                        Nominal=("credit", "sum"),
                        Transaksi=("no_va", "count"),
                        VA_Unik=("no_va", "nunique"),
                    )
                    .reset_index()
                    .sort_values("tahun_bayar")
                )
                tbl_tp.columns = ["TP", "Nominal", "Transaksi", "VA Unik"]

                st.dataframe(
                    tbl_tp,
                    column_config={
                        "Nominal": st.column_config.NumberColumn(format="Rp %,.0f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "⬇️ Download Excel (Total per TP)",
                    data=to_excel(
                        tbl_tp, sheet_name="Total per TP",
                        total_row=True, rp_columns=["Nominal"],
                    ),
                    file_name=f"total_per_tp_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_tp_total",
                )

                st.divider()

                # --- Breakdown per TP × Bulan TP ---
                st.markdown("#### 💰 Breakdown per TP × Bulan TP (B1–B12)")
                st.caption(
                    "B1 = Juli, B2 = Agustus, ..., B12 = Juni. "
                    "Prefix ≠ 00 selalu masuk B1."
                )

                pivot_tp = df_tp.pivot_table(
                    index="tahun_bayar", columns="bulan_tp",
                    values="credit", aggfunc="sum", fill_value=0,
                ).sort_index()

                # Rename kolom 1–12 jadi B1–B12
                pivot_tp.columns = [f"B{int(c)}" for c in pivot_tp.columns]
                # Pastikan semua B1–B12 ada
                for i in range(1, 13):
                    col = f"B{i}"
                    if col not in pivot_tp.columns:
                        pivot_tp[col] = 0
                pivot_tp = pivot_tp[[f"B{i}" for i in range(1, 13)]]
                pivot_tp["TOTAL"] = pivot_tp.sum(axis=1)

                st.dataframe(
                    pivot_tp.style.format("Rp {:,.0f}"),
                    use_container_width=True,
                )

                st.download_button(
                    "⬇️ Download Excel (TP × Bulan TP)",
                    data=pivot_to_excel(
                        pivot_tp.drop(columns="TOTAL", errors="ignore"),
                        sheet_name="TP x Bulan",
                        add_total=True,
                    ),
                    file_name=f"tp_x_bulan_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_tp_bulan",
                )

        # ====================================================
        # SUB 3: SEKOLAH × JENIS BAYAR
        # ====================================================
        with sub_sek_bayar:
            st.markdown("### 🏫 Sekolah × Jenis Bayar")
            st.caption("Pilih TP untuk melihat breakdown per sekolah dan jenis bayar.")

            df_sb = apply_filters(df, key_prefix="sekbayar")

            if df_sb.empty:
                st.warning("Tidak ada data setelah filter.")
            else:
                tp_pilih = st.selectbox(
                    "Pilih TP",
                    options=["(Semua TP)"] + sorted(df_sb["tahun_bayar"].unique()),
                    key="sb_tp_pilih",
                )
                df_pivot = df_sb if tp_pilih == "(Semua TP)" else df_sb[df_sb["tahun_bayar"] == tp_pilih]

                pivot_sb = df_pivot.pivot_table(
                    index="nama_sekolah", columns="nama_bayar",
                    values="credit", aggfunc="sum", fill_value=0,
                )
                pivot_sb["TOTAL"] = pivot_sb.sum(axis=1)
                pivot_sb = pivot_sb.sort_values("TOTAL", ascending=False)
                pivot_sb.loc["TOTAL"] = pivot_sb.sum()

                st.dataframe(
                    pivot_sb.style.format("Rp {:,.0f}"),
                    use_container_width=True,
                )

                st.download_button(
                    "⬇️ Download Excel",
                    data=pivot_to_excel(
                        pivot_sb.drop(index="TOTAL", errors="ignore")
                        .drop(columns="TOTAL", errors="ignore"),
                        sheet_name="Sekolah x Bayar",
                        add_total=True,
                    ),
                    file_name=f"sekolah_x_bayar_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_sek_bayar",
                )

        # ====================================================
        # SUB 4: SEKOLAH × TP
        # ====================================================
        with sub_sek_tp:
            st.markdown("### 🏫 Sekolah × TP")
            st.caption("Nominal per sekolah di tiap TP.")

            df_st = apply_filters(df, key_prefix="sektp")

            if df_st.empty:
                st.warning("Tidak ada data setelah filter.")
            else:
                pivot_st = df_st.pivot_table(
                    index="nama_sekolah", columns="tahun_bayar",
                    values="credit", aggfunc="sum", fill_value=0,
                )
                pivot_st["TOTAL"] = pivot_st.sum(axis=1)
                pivot_st = pivot_st.sort_values("TOTAL", ascending=False)
                pivot_st.loc["TOTAL"] = pivot_st.sum()

                st.dataframe(
                    pivot_st.style.format("Rp {:,.0f}"),
                    use_container_width=True,
                )

                st.download_button(
                    "⬇️ Download Excel",
                    data=pivot_to_excel(
                        pivot_st.drop(index="TOTAL", errors="ignore")
                        .drop(columns="TOTAL", errors="ignore"),
                        sheet_name="Sekolah x TP",
                        add_total=True,
                    ),
                    file_name=f"sekolah_x_tp_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_sek_tp",
                )

        # ====================================================
        # SUB 5: TOP SISWA
        # ====================================================
        with sub_siswa:
            st.markdown("### 🏆 Top Siswa")
            st.caption("Siswa dengan nominal pembayaran tertinggi (nama unik per sekolah).")

            df_sw = apply_filters(df, key_prefix="siswa")

            if df_sw.empty:
                st.warning("Tidak ada data setelah filter.")
            else:
                top_n = st.slider("Tampilkan top N", 10, 200, 50, step=10,
                                  key="top_n_siswa")

                # Extract nama siswa dari remark (sudah dibersihkan dari angka)
                tbl_siswa = (
                    df_sw.groupby(["nama_sekolah", "remark"])
                    .agg(
                        Nominal=("credit", "sum"),
                        Transaksi=("no_va", "count"),
                        TP_Dibayar=("tahun_bayar", lambda x: ", ".join(sorted(set(x)))),
                    )
                    .reset_index()
                    .sort_values("Nominal", ascending=False)
                    .head(top_n)
                )
                tbl_siswa.columns = ["Sekolah", "Siswa", "Nominal", "Transaksi", "TP Dibayar"]

                st.dataframe(
                    tbl_siswa,
                    column_config={
                        "Nominal": st.column_config.NumberColumn(format="Rp %,.0f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "⬇️ Download Excel (Top Siswa)",
                    data=to_excel(
                        tbl_siswa, sheet_name="Top Siswa",
                        total_row=False, rp_columns=["Nominal"],
                    ),
                    file_name=f"top_siswa_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_top_siswa",
                )

        # ====================================================
        # SUB 6: DETAIL PER SEKOLAH
        # ====================================================
        with sub_detail:
            st.markdown("### 📋 Detail per Sekolah")
            st.caption("Drill-down: pilih sekolah → lihat detail transaksi.")

            df_dt = apply_filters(df, key_prefix="detail")

            if df_dt.empty:
                st.warning("Tidak ada data setelah filter.")
            else:
                sek_pilih = st.selectbox(
                    "Pilih Sekolah",
                    options=["(Semua)"] + sorted(df_dt["nama_sekolah"].unique()),
                    key="detail_sek_pilih",
                )
                df_show = df_dt if sek_pilih == "(Semua)" else df_dt[df_dt["nama_sekolah"] == sek_pilih]

                # Ringkasan per sekolah
                if sek_pilih == "(Semua)":
                    st.markdown("#### 📊 Ringkasan per Sekolah")
                    ringkasan = (
                        df_show.groupby("nama_sekolah")
                        .agg(
                            Nominal=("credit", "sum"),
                            Transaksi=("no_va", "count"),
                            Siswa=("remark", "nunique"),
                        )
                        .reset_index()
                        .sort_values("Nominal", ascending=False)
                    )
                    ringkasan.columns = ["Sekolah", "Nominal", "Transaksi", "Siswa"]
                    st.dataframe(
                        ringkasan,
                        column_config={
                            "Nominal": st.column_config.NumberColumn(format="Rp %,.0f"),
                        },
                        use_container_width=True,
                        hide_index=True,
                    )

                # Detail transaksi
                st.markdown(f"#### 📋 Detail Transaksi: {sek_pilih}")
                st.dataframe(
                    df_show[[
                        "date", "time", "company_code", "subcompany",
                        "no_va", "remark", "tahun_bayar", "bulan_nama",
                        "kategori", "nama_bayar", "credit",
                    ]].sort_values("date", ascending=False),
                    column_config={
                        "credit": st.column_config.NumberColumn(format="Rp %,.0f"),
                    },
                    use_container_width=True,
                    hide_index=True,
                )

                st.download_button(
                    "⬇️ Download Excel (Detail)",
                    data=to_excel(
                        df_show, sheet_name="Detail",
                        total_row=False, rp_columns=["credit"],
                    ),
                    file_name=f"detail_{sek_pilih[:20]}_{datetime.now():%Y%m%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_detail",
            )
