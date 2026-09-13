import base64
from datetime import datetime, timedelta
import pytz  # Tambahkan baris ini
import sqlite3
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


# ==========================================
# 1. SETUP DATABASE SQLITE
# ==========================================
def init_db():
    conn = sqlite3.connect('data_absensi.db')
    c = conn.cursor()

    # Tabel Karyawan
    c.execute('''
    CREATE TABLE IF NOT EXISTS karyawan (
        uid_rfid TEXT PRIMARY KEY,
        nama TEXT,
        divisi TEXT
    )
    ''')

    # Tabel Log Absensi
    c.execute('''
    CREATE TABLE IF NOT EXISTS log_absensi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        uid_rfid TEXT,
        nama TEXT,
        tanggal TEXT,
        jam_masuk TEXT,
        jam_pulang TEXT,
        status TEXT
    )
    ''')

    conn.commit()
    conn.close()


# Inisialisasi DB saat aplikasi pertama kali dijalankan
init_db()


# ==========================================
# 2. FUNGSI-FUNGSI DATABASE
# ==========================================
def tambah_karyawan(uid, nama, divisi):
    conn = sqlite3.connect('data_absensi.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO karyawan (uid_rfid, nama, divisi) VALUES (?, ?, ?)", (uid, nama, divisi))
        conn.commit()
        sukses = True
    except sqlite3.IntegrityError:
        sukses = False  # UID sudah ada
    conn.close()
    return sukses


def cek_karyawan(uid):
    conn = sqlite3.connect('data_absensi.db')
    c = conn.cursor()
    c.execute("SELECT nama FROM karyawan WHERE uid_rfid = ?", (uid,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None


def catat_absen(uid, nama):
    tz = pytz.timezone('Asia/Jakarta')
    sekarang = datetime.now(tz)
    
    waktu_sekarang_str = sekarang.strftime("%Y-%m-%d %H:%M:%S")
    jam_sekarang_str = sekarang.strftime("%H:%M:%S")
    tanggal_hari_ini = sekarang.strftime("%Y-%m-%d")
    

    conn = sqlite3.connect('data_absensi.db')
    c = conn.cursor()

    # Cek apakah karyawan ini sedang memiliki sesi aktif (jam_pulang masih '-') dalam 24 jam terakhir
    ambang_batas_cek = (sekarang - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    c.execute('''
    SELECT id, jam_masuk, jam_pulang, tanggal FROM log_absensi
    WHERE uid_rfid = ? AND jam_pulang = '-' AND jam_masuk >= ?
    ORDER BY jam_masuk DESC LIMIT 1
    ''', (uid, ambang_batas_cek))

    data_absen_aktif = c.fetchone()
    pesan = ""

    if data_absen_aktif:
        id_log, jam_masuk_str, jam_pulang_str, tanggal_shift = data_absen_aktif
        waktu_masuk = datetime.strptime(jam_masuk_str, "%Y-%m-%d %H:%M:%S")
        selisih_waktu = sekarang - waktu_masuk

        if selisih_waktu < timedelta(hours=1):
            # --- ATURAN 1: KURANG DARI 1 JAM (KOREKSI JAM MASUK) ---
            c.execute('''
            UPDATE log_absensi
            SET jam_masuk = ?
            WHERE id = ?
            ''', (waktu_sekarang_str, id_log))
            pesan = f"⚠️ Koreksi Jam Masuk! Jam masuk **{nama}** diperbarui ke {jam_sekarang_str}."

        elif selisih_waktu <= timedelta(hours=14):
            # --- ATURAN 2: ANTARA 1 JAM SAMPAI 14 JAM (DIANGGAP JAM PULANG) ---
            c.execute('''
            UPDATE log_absensi
            SET jam_pulang = ?, status = ?
            WHERE id = ?
            ''', (waktu_sekarang_str, "Hadir & Pulang", id_log))
            pesan = f" Berhasil Absen **PULANG**! Hati-hati di jalan, **{nama}**."

        else:
            # --- ATURAN 3: LEBIH DARI 14 JAM TANPA PULANG (ALPHA) ---
            c.execute('''
            UPDATE log_absensi
            SET jam_pulang = 'Tidak Absen Pulang', status = ?
            WHERE id = ?
            ''', ("Alpha / Lupa Pulang", id_log))

            c.execute('''
            INSERT INTO log_absensi (uid_rfid, nama, tanggal, jam_masuk, jam_pulang, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (uid, nama, tanggal_hari_ini, waktu_sekarang_str, "-", "Masuk"))

            pesan = f"⚠️ Sesi sebelumnya ditandai **Lupa Pulang (Alpha)** karena >14 jam. Berhasil buat Absen **MASUK** baru untuk **{nama}**."

    else:
        tanggal_kerja = tanggal_hari_ini

        c.execute('''
        SELECT id FROM log_absensi WHERE uid_rfid = ? AND tanggal = ? AND jam_pulang != '-'
        ''', (uid, tanggal_kerja))
        sudah_selesai_hari_ini = c.fetchone()

        if sudah_selesai_hari_ini:
            pesan = f"⚠️ **{nama}** sudah menyelesaikan seluruh sesi absensi untuk hari ini."
        else:
            c.execute('''
            INSERT INTO log_absensi (uid_rfid, nama, tanggal, jam_masuk, jam_pulang, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (uid, nama, tanggal_kerja, waktu_sekarang_str, "-", "Masuk"))
            pesan = f" Berhasil Absen **MASUK**! Selamat bekerja, **{nama}**."

    conn.commit()
    conn.close()
    return pesan


def get_laporan_satu_tabel(start_date, end_date):
    conn = sqlite3.connect('data_absensi.db')

    query = '''
    SELECT
        uid_rfid AS 'UID RFID',
        nama AS 'Nama Karyawan',
        tanggal AS 'Tanggal Shift',
        jam_masuk AS 'Jam Masuk',
        COALESCE(jam_pulang, '-') AS 'Jam Pulang',
        status AS 'Status'
    FROM log_absensi
    WHERE tanggal >= ? AND tanggal <= ?
    ORDER BY tanggal DESC, jam_masuk DESC
    '''
    df = pd.read_sql_query(query, conn, params=(start_date, end_date))
    conn.close()

    return df


def get_image_base64(path):
    try:
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode()
        return f"data:image/png;base64,{encoded}"
    except:
        return ""


# ==========================================
# 3. ANTARMUKA STREAMLIT (UI)
# ==========================================
# initial_sidebar_state="collapsed" membuat sidebar otomatis tertutup saat pertama kali dibuka
st.set_page_config(page_title="Sistem Absensi RFID", layout="centered", initial_sidebar_state="collapsed")

# --- INJEKSI CSS ---
page_bg_color = """
<style>
[data-testid="stAppViewContainer"] {
    background: linear-gradient(135deg, #1e6b9c 0%, #30c5eb 100%);
}
[data-testid="stHeader"] {
    background-color: rgba(0,0,0,0);
}
h1, h2, h3, p, .stMarkdown {
    color: white !important;
}
[data-testid="stForm"] {
    background-color: white !important;
    border-radius: 15px;
    padding: 25px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.2);
}
[data-testid="stForm"] * {
    color: #333333 !important;
}
[data-testid="stImage"] {
    background-color: white !important;
    border-radius: 15px;
    padding: 15px;
    box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    display: flex;
    justify-content: center;
}

/* --- Mengubah warna font Tombol Download menjadi Hitam --- */
[data-testid="stDownloadButton"] button {
    background-color: #f0f2f6; /* Warna latar tombol */
    color: black !important; /* Teks menjadi hitam */
    border: 1px solid #d6d6d6;
}
[data-testid="stDownloadButton"] button p {
    color: black !important;
}
[data-testid="stDownloadButton"] button:hover {
    background-color: #e2e6ea;
    color: black !important;
}
</style>
"""
st.markdown(page_bg_color, unsafe_allow_html=True)

# --- HTML & JS UNTUK HEADER & JAM ---
logo_base64 = get_image_base64("BGN_LOGO_GOLD.png")

header_clock_html = f"""
<div style="background-color: white; border-radius: 15px; padding: 20px; box-shadow: 0 4px 10px rgba(0,0,0,0.2); display: flex; align-items: center; justify-content: center; gap: 25px; margin-bottom: 20px;">
    <img src="{logo_base64}" style="width: 100px; height: auto; border-radius: 8px;">
    <div style="font-family: sans-serif; text-align: left;">
        <h1 style="color: #DAA520; font-size: 28px; font-weight: 800; margin: 0; padding: 0; line-height: 1.1; text-shadow: 1px 1px 2px rgba(0,0,0,0.1);">SPPG BANGKA BARAT</h1>
        <h2 style="color: #DAA520; font-size: 22px; font-weight: 600; margin: 0; padding: 0; line-height: 1.3; margin-top: 4px; text-shadow: 1px 1px 2px rgba(0,0,0,0.1);">KELAPA KACUNG</h2>
    </div>
</div>

<div style="text-align: center; font-family: sans-serif; color: white; margin-top: 15px; margin-bottom: 15px;">
    <div id="date" style="font-size: 22px; font-weight: 500; margin-bottom: 5px;"></div>
    <div id="time" style="font-size: 75px; font-weight: bold; letter-spacing: 3px;"></div>
</div>

<script>
function updateClock() {{
    var now = new Date();
    var optionsDate = {{ weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' }};
    var dateStr = now.toLocaleDateString('id-ID', optionsDate);
    var timeStr = now.toLocaleTimeString('id-ID', {{ hour12: false }});

    document.getElementById('date').innerText = dateStr;
    document.getElementById('time').innerText = timeStr;
}}
setInterval(updateClock, 1000);
updateClock();
</script>
"""

components.html(header_clock_html, height=270)

# Menu Navigasi di Sidebar (Sidebar kini otomatis tertutup saat aplikasi dibuka)
menu = st.sidebar.selectbox("Pilih Menu", ["Mode Absensi", "Registrasi Karyawan", "Laporan Absensi"])

# --- MENU: MODE ABSENSI ---
if menu == "Mode Absensi":
    with st.form("form_absen", clear_on_submit=True):
        uid_input = st.text_input("UID Kartu RFID:", key="rfid_absen")
        submitted = st.form_submit_button("Submit")

    if submitted and uid_input:
        nama_karyawan = cek_karyawan(uid_input)
        if nama_karyawan:
            pesan_hasil = catat_absen(uid_input, nama_karyawan)
            st.success(pesan_hasil)
        else:
            st.error(" Kartu tidak terdaftar! Silakan registrasi terlebih dahulu.")

# --- MENU: REGISTRASI KARYAWAN ---
elif menu == "Registrasi Karyawan":
    st.subheader("Daftarkan Kartu & Karyawan Baru")

    with st.form("form_registrasi", clear_on_submit=True):
        uid_baru = st.text_input("Tap Kartu untuk mendapatkan UID:")
        nama_baru = st.text_input("Nama Lengkap Karyawan:")
        divisi_baru = st.selectbox(
            "Divisi / Bagian:",
            [
                "Asisten Lapangan",
                "Chef",
                "Persiapan",
                "Pengolahan",
                "Pemorsian",
                "Distribusi",
                "Cuci Ompreng",
                "CS",
                "Satpam",
            ]
        )
        submit_registrasi = st.form_submit_button("Simpan Data")

    if submit_registrasi:
        if not uid_baru or not nama_baru:
            st.warning("⚠️ UID dan Nama tidak boleh kosong!")
        else:
            sukses = tambah_karyawan(uid_baru, nama_baru, divisi_baru)
            if sukses:
                st.success(f" Karyawan **{nama_baru}** berhasil didaftarkan dengan UID {uid_baru}.")
            else:
                st.error(" Gagal! UID Kartu ini sudah terdaftar di sistem.")

# --- MENU: LAPORAN ABSENSI ---
elif menu == "Laporan Absensi":
    st.subheader("Data Laporan Absensi")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Dari Tanggal", datetime.now().date())
    with col2:
        end_date = st.date_input("Sampai Tanggal", datetime.now().date())

    if start_date > end_date:
        st.error(" Error: 'Dari Tanggal' tidak boleh melebihi 'Sampai Tanggal'.")
    else:
        str_start_date = start_date.strftime("%Y-%m-%d")
        str_end_date = end_date.strftime("%Y-%m-%d")

        df_laporan = get_laporan_satu_tabel(str_start_date, str_end_date)

        if not df_laporan.empty:
            st.dataframe(df_laporan, use_container_width=True)

            csv = df_laporan.to_csv(index=False).encode('utf-8')
            st.download_button(
                label=" Download Laporan (CSV)",
                data=csv,
                file_name=f'laporan_absensi_{str_start_date}_sd_{str_end_date}.csv',
                mime='text/csv'
            )
        else:
            st.info("Belum ada data absensi pada rentang tanggal tersebut.")
