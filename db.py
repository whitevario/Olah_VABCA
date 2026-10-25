"""
Modul database SQLite untuk aplikasi VABCA.
Menyimpan transaksi, log upload, dan master data.
"""
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path
import pandas as pd

DB_PATH = Path("laporan.db")


def get_conn() -> sqlite3.Connection:
    """Koneksi SQLite dengan WAL mode (aman untuk multi-tab)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Buat tabel kalau belum ada + seed kategori default."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS transaksi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_code TEXT,
            subcompany TEXT,
            no_va TEXT,
            remark TEXT,
            mata_uang TEXT,
            credit REAL,
            date TEXT,
            time TEXT,
            asal_file TEXT,
            prefix_va TEXT,
            tahun_bayar TEXT,
            bulan_tp INTEGER,
            kode_sekolah TEXT,
            kode_bayar TEXT,
            bulan TEXT,
            uploaded_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_bulan ON transaksi(bulan);
        CREATE INDEX IF NOT EXISTS idx_tahun_bayar ON transaksi(tahun_bayar);
        CREATE INDEX IF NOT EXISTS idx_bulan_tp ON transaksi(bulan_tp);
        CREATE INDEX IF NOT EXISTS idx_date ON transaksi(date);
        CREATE INDEX IF NOT EXISTS idx_subcomp ON transaksi(subcompany);
        CREATE INDEX IF NOT EXISTS idx_sekolah ON transaksi(kode_sekolah);
        CREATE INDEX IF NOT EXISTS idx_prefix ON transaksi(prefix_va);
        CREATE INDEX IF NOT EXISTS idx_no_va ON transaksi(no_va);

        CREATE TABLE IF NOT EXISTS upload_log (
            file_name TEXT PRIMARY KEY,
            file_hash TEXT,
            total_baris INTEGER,
            uploaded_at TEXT
        );

        CREATE TABLE IF NOT EXISTS master_sekolah (
            kode TEXT PRIMARY KEY,
            nama TEXT
        );

        CREATE TABLE IF NOT EXISTS master_bayar (
            kode TEXT PRIMARY KEY,
            nama TEXT
        );

        CREATE TABLE IF NOT EXISTS master_kategori (
            prefix_va TEXT PRIMARY KEY,
            kategori TEXT
        );
        """)

        # Seed kategori default
        default_kat = {
            "00": "Uang Sekolah TP Berjalan",
            "25": "SPMB TP 2025-2026",
            "26": "SPMB TP 2026-2027",
            "27": "SPMB TP 2027-2028",
        }
        for prefix, kat in default_kat.items():
            conn.execute(
                "INSERT OR IGNORE INTO master_kategori (prefix_va, kategori) "
                "VALUES (?, ?)",
                (prefix, kat),
            )


def file_hash(content: bytes) -> str:
    """Hash MD5 dari isi file — untuk deteksi file berubah."""
    return hashlib.md5(content).hexdigest()


def get_existing_files() -> set[str]:
    """Set nama file yang sudah ada di database."""
    with get_conn() as conn:
        rows = conn.execute("SELECT file_name FROM upload_log").fetchall()
        return {r["file_name"] for r in rows}


def delete_file(file_name: str):
    """Hapus semua transaksi + log dari file tertentu."""
    with get_conn() as conn:
        conn.execute("DELETE FROM transaksi WHERE asal_file = ?", (file_name,))
        conn.execute("DELETE FROM upload_log WHERE file_name = ?", (file_name,))


def insert_transaksi(df: pd.DataFrame, file_name: str, content: bytes):
    """Insert transaksi + catat log. Kalau file sudah ada, hapus dulu (idempotent)."""
    delete_file(file_name)

    now = datetime.now().isoformat(timespec="seconds")
    df = df.copy()
    df["uploaded_at"] = now

    # Bulan transaksi (format YYYY-MM) untuk grouping cepat
    df["bulan"] = pd.to_datetime(
        df["date"], format="%d/%m/%Y", errors="coerce"
    ).dt.strftime("%Y-%m")

    with get_conn() as conn:
        df.to_sql("transaksi", conn, if_exists="append", index=False)
        conn.execute(
            "INSERT INTO upload_log (file_name, file_hash, total_baris, uploaded_at) "
            "VALUES (?, ?, ?, ?)",
            (file_name, file_hash(content), len(df), now),
        )


def load_all_transaksi() -> pd.DataFrame:
    """Ambil semua transaksi sebagai DataFrame."""
    with get_conn() as conn:
        return pd.read_sql_query("SELECT * FROM transaksi", conn)


def load_master(table: str) -> pd.DataFrame:
    """Ambil isi master data."""
    if table not in ("master_sekolah", "master_bayar", "master_kategori"):
        raise ValueError(f"Tabel tidak dikenal: {table}")
    with get_conn() as conn:
        return pd.read_sql_query(f"SELECT * FROM {table}", conn)


def upsert_master(table: str, df: pd.DataFrame):
    """Ganti seluruh isi master data (delete + insert)."""
    if table not in ("master_sekolah", "master_bayar", "master_kategori"):
        raise ValueError(f"Tabel tidak dikenal: {table}")
    with get_conn() as conn:
        conn.execute(f"DELETE FROM {table}")
        if not df.empty:
            df.to_sql(table, conn, if_exists="append", index=False)


def backup_db_bytes() -> bytes:
    """Ambil isi file database sebagai bytes (untuk download)."""
    if not DB_PATH.exists():
        return b""
    # Force checkpoint WAL dulu biar semua data masuk ke file utama
    with get_conn() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return DB_PATH.read_bytes()


def restore_db(content: bytes):
    """Timpa database lokal dengan backup dari user."""
    # Hapus file WAL & SHM dulu (kalau ada) supaya bersih
    for suffix in ("-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()

    with open(DB_PATH, "wb") as f:
        f.write(content)

    init_db()  # pastikan skema lengkap


def db_stats() -> dict:
    """Statistik ringkas database — untuk ditampilkan di UI."""
    if not DB_PATH.exists():
        return {"files": 0, "rows": 0, "size_kb": 0}
    with get_conn() as conn:
        n_files = conn.execute("SELECT COUNT(*) FROM upload_log").fetchone()[0]
        n_rows = conn.execute("SELECT COUNT(*) FROM transaksi").fetchone()[0]
    size_kb = DB_PATH.stat().st_size // 1024
    return {"files": n_files, "rows": n_rows, "size_kb": size_kb}
