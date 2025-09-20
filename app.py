import datetime
import io
import os
import uuid

import pandas as pd
import pymysql
import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from werkzeug.security import check_password_hash, generate_password_hash

# ==================== CONFIG ====================
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "poverty_db",
    "port": 3306,
}
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ==================== DB INIT ====================
def get_connection(database=None):
    cfg = DB_CONFIG.copy()
    return pymysql.connect(
        host=cfg["host"],
        user=cfg["user"],
        password=cfg["password"],
        database=database if database else None,
        port=cfg.get("port", 3306),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def init_db():
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{DB_CONFIG['database']}` CHARACTER SET utf8mb4;"
        )
    conn.close()
    conn = get_connection(DB_CONFIG["database"])
    with conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS users(
               id INT AUTO_INCREMENT PRIMARY KEY,
               username VARCHAR(100) UNIQUE,
               password_hash VARCHAR(255),
               role VARCHAR(20) DEFAULT 'admin',
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        cur.execute(
            """CREATE TABLE IF NOT EXISTS households(
               id INT AUTO_INCREMENT PRIMARY KEY,
               name VARCHAR(255), address TEXT,
               education VARCHAR(100), num_children INT,
               monthly_income DOUBLE, occupation VARCHAR(100),
               classification VARCHAR(50), image_path VARCHAR(255),
               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        if not cur.execute("SELECT * FROM users WHERE username='admin'"):
            cur.execute(
                "INSERT INTO users(username,password_hash,role) VALUES(%s,%s,%s)",
                ("admin", generate_password_hash("admin123"), "admin"),
            )
    conn.close()


# ==================== CLASSIFY ====================
def classify_household(income, edu, kids, job):
    score = 0
    inc = float(income or 0)
    if inc < 2_000_000:
        score += 0
    elif inc < 4_000_000:
        score += 30
    elif inc < 7_000_000:
        score += 60
    else:
        score += 100
    edu_map = {
        "Tidak Sekolah": 0,
        "SD": 10,
        "SMP": 20,
        "SMA/SMK": 30,
        "Diploma": 40,
        "S1 ke atas": 50,
    }
    score += edu_map.get(edu, 20)
    kids = int(kids or 0)
    score += 10 if kids < 2 else (-10 if kids < 4 else -20)
    occ_map = {
        "Pengangguran": 0,
        "Buruh / Tani / Pekerja kasar": 10,
        "Wiraswasta kecil": 20,
        "Pegawai swasta": 30,
        "PNS / Profesional": 40,
    }
    score += occ_map.get(job, 10)
    return "Miskin" if score < 50 else "Menengah" if score < 110 else "Kaya"


# ==================== CRUD ====================
def insert_household(rec):
    sql = """INSERT INTO households
             (name,address,education,num_children,monthly_income,occupation,classification,image_path)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"""
    conn = get_connection(DB_CONFIG["database"])
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                rec["name"],
                rec["address"],
                rec["education"],
                rec["num_children"],
                rec["monthly_income"],
                rec["occupation"],
                rec["classification"],
                rec.get("image_path"),
            ),
        )
    conn.close()


def fetch_all():
    conn = get_connection(DB_CONFIG["database"])
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM households ORDER BY created_at DESC")
        rows = cur.fetchall()
    conn.close()
    return rows


def delete_household_by_name(nama: str):
    conn = get_connection(DB_CONFIG["database"])
    with conn.cursor() as cur:
        cur.execute("DELETE FROM households WHERE name=%s", (nama,))
    conn.close()


def verify_user(u, p):
    conn = get_connection(DB_CONFIG["database"])
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE username=%s", (u,))
        row = cur.fetchone()
    conn.close()
    return (
        row and check_password_hash(row["password_hash"], p),
        row["role"] if row else None,
    )


# ==================== EXPORT ====================
def df_to_excel_bytes(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        df.to_excel(w, index=False, sheet_name="households")
    return buf.getvalue()


def df_to_pdf_bytes(df):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    elems = [Paragraph("Laporan Data Kemiskinan", styles["Title"]), Spacer(1, 12)]
    cols = [
        "id",
        "name",
        "education",
        "num_children",
        "monthly_income",
        "occupation",
        "classification",
        "created_at",
    ]
    data = [cols] + [[str(r[c]) for c in cols] for _, r in df[cols].iterrows()]
    t = Table(data, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.black),
                ("BOX", (0, 0), (-1, -1), 0.25, colors.black),
            ]
        )
    )
    elems.append(t)
    doc.build(elems)
    return buf.getvalue()


# ==================== UI ====================
st.set_page_config(page_title="Aplikasi Data Masyarakat", layout="wide")
init_db()

# ----- Custom CSS -----
st.markdown(
    """
<style>
/* ====== Full Background Image ====== */
    .stApp {
        background: url("https://images.unsplash.com/photo-1503264116251-35a269479413") no-repeat center center fixed;
        background-size: cover;
    }

    /* ===== Sidebar: warna solid berbeda ===== */
    [data-testid="stSidebar"] {
        background-color: rgba(15, 23, 45, 0.6);  /* contoh: navy gelap semi transparan */
        color: #ffffff;
    }

    /* Konten utama transparan agar gambar terlihat */
    [data-testid="stAppViewContainer"] > .main {
        background: rgba(255,255,255,0.0);
    }
.export-card {
    max-width: 600px;
    margin: 30px auto;
    background: #ffffffcc;
    padding: 25px;
    border-radius: 12px;
    box-shadow: 0 8px 20px rgba(0,0,0,0.25);
    text-align: center;
}
.export-title {
    font-size: 1.4rem;
    font-weight: bold;
    margin-bottom: 15px;
    color: #ffffff;
}
body {
    background: linear-gradient(135deg, #74ABE2 25%, #5563DE 100%);
    background-attachment: fixed;
    background-size: cover;
}
.header, .footer {
    max-width: 600px;
    margin: 0 auto 20px auto;
    background: linear-gradient(90deg,#0f172a,#0ea5a9);
    padding: 18px;
    border-radius: 8px;
    color: white;
    text-align: center;
    box-shadow: 0 4px 10px rgba(0,0,0,0.25);
}
.stForm {
    max-width: 600px;
    margin: 0 auto;
    background: #ffffffcc;
    padding: 25px;
    border-radius: 12px;
    box-shadow: 0 8px 20px rgba(0,0,0,0.25);
}
.login-title {
    text-align:center;
    font-weight:bold;
    font-size:1.3rem;
    margin-bottom:15px;
    text-shadow: 0 2px 4px rgba(0,0,0,0.3);
}
.sidebar-user {
    display:flex;
    align-items:center;
    justify-content:center;
    margin-bottom:15px;
    font-size:1rem;
}
.sidebar-icon {
    margin-right:8px;
    font-size:1.3rem;
}
.table-container {
    max-width:600px;
    margin:0 auto;
}
.export-card {
    max-width:600px;
    margin:30px auto;
    background:#ffffffcc;
    padding:25px;
    text-align: center;
    border-radius:12px;
    box-shadow:0 8px 20px rgba(0,0,0,0.25);
    text-align:center;
}
.export-title {
    font-size:1.4rem;
    font-weight:bold;
    margin-bottom:15px;
    color:#0f172a;
}
</style>
""",
    unsafe_allow_html=True,
)

# Header
st.markdown(
    '<div class="header"><h2>Aplikasi Data Masyarakat</h2></div>',
    unsafe_allow_html=True,
)

# Session
if "logged_in" not in st.session_state:
    st.session_state.update({"logged_in": False, "username": None, "role": None})

# -------- LOGIN --------
if not st.session_state.logged_in:
    st.markdown('<div class="login-title">Login</div>', unsafe_allow_html=True)
    with st.form("login_form"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Masuk"):
            ok, role = verify_user(u.strip(), p.strip())
            if ok:
                st.session_state.update(
                    {"logged_in": True, "username": u, "role": role}
                )
                st.success("Login berhasil.")
                st.rerun()
            else:
                st.error("Login gagal — cek username/password.")
    st.markdown(
        '<div class="footer">&copy; 2025 - All Reserved</div>', unsafe_allow_html=True
    )
    st.stop()

# -------- AFTER LOGIN --------
with st.sidebar:
    st.markdown(
        f"""
        <div class="sidebar-user">
            <span class="sidebar-icon">👤</span>
            <b>{st.session_state.username}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

menu = st.sidebar.selectbox(
    "Menu",
    [
        "Dashboard",
        "Tambah Data",
        "Import Excel",
        "Export Excel",
        "Export PDF",
        "Kelola Users",
        "Logout",
    ],
)

if menu == "Logout":
    st.session_state.logged_in = False
    st.rerun()

elif menu == "Dashboard":
    rows = fetch_all()
    if not rows:
        st.info("Belum ada data.")
    else:
        df = pd.DataFrame(rows)
        search = st.text_input("Cari nama:")
        if search:
            df = df[df["name"].str.contains(search, case=False, na=False)]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total", len(df))
        c2.metric("Miskin", (df["classification"] == "Miskin").sum())
        c3.metric("Menengah", (df["classification"] == "Menengah").sum())
        c4.metric("Kaya", (df["classification"] == "Kaya").sum())

        st.markdown('<div class="table-container">', unsafe_allow_html=True)
        st.dataframe(df, height=250, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.subheader("Hapus Data Berdasarkan Nama")
        if not df.empty:
            del_name = st.selectbox(
                "Pilih Nama untuk dihapus", df["name"].unique().tolist()
            )
            if st.button("Hapus"):
                delete_household_by_name(del_name)
                st.success(f"Data dengan nama '{del_name}' berhasil dihapus.")
                st.rerun()

elif menu == "Tambah Data":
    with st.form("add_form"):
        name = st.text_input("Nama")
        addr = st.text_area("Alamat")
        edu = st.selectbox(
            "Pendidikan",
            ["Tidak Sekolah", "SD", "SMP", "SMA/SMK", "Diploma", "S1 ke atas"],
        )
        kids = st.number_input("Jumlah Anak", min_value=0, step=1)
        inc = st.number_input("Pendapatan per bulan", min_value=0.0, format="%.2f")
        job = st.selectbox(
            "Pekerjaan",
            [
                "Pengangguran",
                "Buruh / Tani / Pekerja kasar",
                "Wiraswasta kecil",
                "Pegawai swasta",
                "PNS / Profesional",
            ],
        )
        foto = st.file_uploader("Upload Foto (opsional)", type=["png", "jpg", "jpeg"])
        if st.form_submit_button("Simpan"):
            path = None
            if foto:
                ext = os.path.splitext(foto.name)[1]
                fname = f"{uuid.uuid4().hex}{ext}"
                path = os.path.join(UPLOAD_DIR, fname)
                with open(path, "wb") as f:
                    f.write(foto.getbuffer())
            cls = classify_household(inc, edu, kids, job)
            insert_household(
                {
                    "name": name,
                    "address": addr,
                    "education": edu,
                    "num_children": int(kids),
                    "monthly_income": float(inc),
                    "occupation": job,
                    "classification": cls,
                    "image_path": path,
                }
            )
            st.success(f"Data tersimpan. Klasifikasi: **{cls}**")

elif menu == "Import Excel":
    # ===== Card Wrapper =====
    st.markdown(
        """
        <div class="export-card">
            <div class="export-title">Import Data dari Excel</div>
        """,
        unsafe_allow_html=True,
    )

    # ===== Form Upload di dalam Card =====
    with st.form("import_excel_form"):
        st.info(
            "Kolom minimal: name, address, education, num_children, monthly_income, occupation"
        )
        file_xlsx = st.file_uploader("Pilih file Excel (.xlsx)", type=["xlsx"])
        submit_import = st.form_submit_button("⬆️ Import ke Database")

    # ===== Proses Import saat Tombol ditekan =====
    if submit_import:
        if not file_xlsx:
            st.error("Silakan pilih file Excel terlebih dahulu.")
        else:
            try:
                df = pd.read_excel(file_xlsx)
                st.markdown("**Preview Data (5 baris pertama):**")
                st.dataframe(df.head(), use_container_width=True)

                inserted = 0
                for _, r in df.iterrows():
                    try:
                        insert_household(
                            {
                                "name": r.get("name", ""),
                                "address": r.get("address", ""),
                                "education": r.get("education", "SMA/SMK"),
                                "num_children": int(r.get("num_children", 0) or 0),
                                "monthly_income": float(
                                    r.get("monthly_income", 0) or 0
                                ),
                                "occupation": r.get("occupation", "Wiraswasta kecil"),
                                "classification": classify_household(
                                    r.get("monthly_income", 0),
                                    r.get("education", "SMA/SMK"),
                                    r.get("num_children", 0),
                                    r.get("occupation", "Wiraswasta kecil"),
                                ),
                                "image_path": None,
                            }
                        )
                        inserted += 1
                    except Exception as e_row:
                        st.warning(f"Gagal import baris: {e_row}")

                st.success(f"Import selesai. {inserted} baris berhasil disimpan.")
            except Exception as e:
                st.error(f"Gagal membaca file Excel: {e}")

    # ===== Penutup div card =====
    st.markdown("</div>", unsafe_allow_html=True)

elif menu == "Export Excel":
    df = pd.DataFrame(fetch_all())
    if df.empty:
        st.info("Belum ada data.")
    else:
        # ===== Card + Form Export Excel =====
        with st.form("excel_export_form"):
            st.markdown(
                """
                <div class="export-card">
                    <div class="export-title">Export Data ke Excel</div>
                """,
                unsafe_allow_html=True,
            )

            catatan = st.text_input(
                "Catatan Laporan (opsional):",
                placeholder="Misal: Data kemiskinan Q4 2025",
            )

            submit_xlsx = st.form_submit_button("⬇️ Download Excel")
            st.markdown("</div>", unsafe_allow_html=True)

        # ==== Aksi ketika tombol ditekan ====
        if submit_xlsx:
            if catatan:
                st.toast(f"Laporan Excel siap diunduh. Catatan: {catatan}")
            st.download_button(
                label="Klik di sini untuk mengunduh Excel",
                data=df_to_excel_bytes(df),
                file_name=f"laporan_kemiskinan_{datetime.date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

elif menu == "Export PDF":
    df = pd.DataFrame(fetch_all())
    if df.empty:
        st.info("Belum ada data.")
    else:
        # ==== Card + Form Export PDF ====
        with st.form("pdf_export_form"):
            st.markdown(
                """
                <div class="export-card">
                    <div class="export-title">Export Data ke PDF</div>
                """,
                unsafe_allow_html=True,
            )

            # ---- (Opsional) Field Keterangan ----
            catatan = st.text_input(
                "Catatan Laporan (opsional):",
                placeholder="Misal: Data kemiskinan Q4 2025",
            )

            # ---- Tombol submit form ----
            submit = st.form_submit_button("⬇️ Download PDF")

            st.markdown("</div>", unsafe_allow_html=True)

        # ==== Aksi ketika tombol ditekan ====
        if submit:
            if catatan:
                # bisa tambahkan catatan ke PDF bila perlu
                st.toast(f"Laporan akan diunduh. Catatan: {catatan}")
            st.download_button(
                label="Klik di sini untuk mengunduh PDF",
                data=df_to_pdf_bytes(df),
                file_name=f"laporan_kemiskinan_{datetime.date.today()}.pdf",
                mime="application/pdf",
            )


elif menu == "Kelola Users":
    if st.session_state.role != "admin":
        st.warning("Hanya admin yang bisa mengelola users.")
    else:
        conn = get_connection(DB_CONFIG["database"])
        with conn.cursor() as cur:
            cur.execute("SELECT id,username,role,created_at FROM users")
            users = cur.fetchall()
        conn.close()
        st.dataframe(pd.DataFrame(users))
        with st.form("add_user"):
            u = st.text_input("Username baru")
            p = st.text_input("Password", type="password")
            r = st.selectbox("Role", ["admin", "user"])
            if st.form_submit_button("Tambah"):
                if u and p:
                    conn = get_connection(DB_CONFIG["database"])
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO users(username,password_hash,role) VALUES(%s,%s,%s)",
                            (u, generate_password_hash(p), r),
                        )
                    conn.close()
                    st.success("User dibuat.")
                else:
                    st.error("Isi username & password.")

# Footer
st.markdown(
    '<div class="footer">&copy; 2025 - All Reserved</div>', unsafe_allow_html=True
)
