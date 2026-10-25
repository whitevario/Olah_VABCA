install dependencies
pip install -r requirements.txt

:: cek dependencies di 3.13
py -3.13 -m pip show pandas plotly openpyxl

:: kalau ada yang belum ada:
py -3.13 -m pip install pandas plotly openpyxl

:: hapus database lama (kalau ada)
del laporan.db
del laporan.db-wal
del laporan.db-shm

:: jalankan
py -3.13 -m streamlit run app.py
