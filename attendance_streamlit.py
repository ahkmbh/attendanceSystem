"""
نظام تسجيل الحضور المدرسي المطور - Streamlit + SQLite
============================================================
المتطلبات:
    pip install streamlit pandas openpyxl reportlab arabic-reshaper python-bidi bcrypt

تشغيل:
    streamlit run attendance_streamlit.py
"""

from genericpath import exists

import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
import time
import json
import io
import base64
from datetime import datetime, timedelta
from contextlib import contextmanager

# ── PDF ──────────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors as rl_colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Arabic ───────────────────────────────────────────────────────────
import arabic_reshaper
from bidi.algorithm import get_display

# ════════════════════════════════════════════════════════════════════
# إعدادات الصفحة
# ════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="نظام الحضور ",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS مخصص للدعم العربي والألوان وتحسينات الهاتف ──────────────────


st.markdown("""
    <style>
    /* جعل الحاويات مرنة عند التصغير */
    [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 calc(50% - 1rem) !important;
        min-width: 300px !important;
    }
    
    /* منع النصوص من التداخل أو الخروج عن الإطار */
    .stMarkdown, div[data-testid="stVerticalBlock"] {
        overflow-wrap: break-word;
    }

    /* تحسين شكل الأزرار في المساحات الضيقة */
    .stButton button {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)

st.markdown("""
    <style>
            /* تنسيق القائمة الجانبية الجديدة */
div[data-testid="stSidebar"] {
    background-color: #f4f6f9; 
}

/* تنسيق الأزرار داخل القائمة الجانبية */
div[data-testid="stSidebar"] button {
    background-color: #ffffff !important;
    color: #1a237e !important;
    border: 1px solid #dce1e7 !important;
    border-radius: 8px !important;
    font-weight: bold !important;
    transition: all 0.2s ease-in-out !important;
    padding: 0.5rem !important;
}

div[data-testid="stSidebar"] button:hover {
    border-color: #1a237e !important;
    background-color: #e8eaf6 !important;
    transform: translateY(-1px);
}
    /* إخفاء التلميح الصغير الذي يظهر أسفل الحقل */
    div[data-testid="stTextInput"] div[data-testid="InputInstructions"] {
        display: none;
    }
    
    /* تغيير لون إطار الحقل عند التركيز */
    div[data-testid="stTextInput"] input:focus {
        border-color: #27ae60;
        box-shadow: 0 0 0 0.2rem rgba(39, 174, 96, 0.25);
    }
    </style>
    """, unsafe_allow_html=True)

st.markdown("""
<style>
    body, .stApp { direction: rtl; }
    .stButton > button { border-radius: 10px; font-weight: bold; }
    .metric-card {
        background: white; border-radius: 14px; padding: 18px 20px;
        border: 2px solid; text-align: center; margin: 4px;
    }
    .metric-val { font-size: 2.2rem; font-weight: 800; }
    .metric-lbl { font-size: 0.85rem; color: #666; margin-top: 4px; }
    .alert-row {
        background: #fff3e0; border-radius: 10px;
        padding: 10px 16px; margin: 6px 0;
        border-right: 4px solid #f57f17;
    }
    div[data-testid="stSidebar"] { background: #1a237e; }
    div[data-testid="stSidebar"] * { color: white !important; }
    .sidebar-title { font-size: 1.2rem; font-weight: bold; text-align: center;
                     padding: 10px; background: #283593; border-radius: 10px; }
                     
    /* تحسينات الموبايل (Media Queries) */
    @media (max-width: 768px) {
        .stButton > button { padding: 0.75rem 1rem !important; } /* تكبير الأزرار لتناسب اللمس */
        .metric-val { font-size: 1.5rem !important; } /* تصغير أرقام الإحصائيات */
        .metric-card { padding: 12px 10px !important; }
        div[data-testid="stSidebar"] { min-width: 250px !important; }
    }
</style>
""", unsafe_allow_html=True)

DB_FILE = "school_attendance.db"

# ════════════════════════════════════════════════════════════════════
# قاعدة البيانات SQLite
# ════════════════════════════════════════════════════════════════════
@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name     TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'teacher'
        );

        CREATE TABLE IF NOT EXISTS classes (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );

        CREATE TABLE IF NOT EXISTS students (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            personal_id  TEXT UNIQUE NOT NULL,
            name         TEXT NOT NULL,
            class_id     INTEGER REFERENCES classes(id) ON DELETE SET NULL,
            mobile       TEXT,
            phone        TEXT,
            house        TEXT,
            road         TEXT,
            block        TEXT,
            area         TEXT,
            school_name  TEXT,  -- تمت الإضافة هنا
            group_name   TEXT,   -- تمت الإضافة هنا (اسم الفرقة)
            birth_date   TEXT,
            photo        BLOB,
            notes        TEXT,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            class_id   INTEGER NOT NULL REFERENCES classes(id)  ON DELETE CASCADE,
            date       TEXT NOT NULL,
            status     TEXT NOT NULL CHECK(status IN ('h','g','m')),
            UNIQUE(student_id, date)
        );
        """)

        # إنشاء المستخدمين الافتراضيين إذا لم يكونوا موجودين
        exists = conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone()
        if not exists:
            hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
            conn.execute("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)", 
                         ("admin", hashed, "المشرف الإداري", "admin"))
            
            t_hash = bcrypt.hashpw(b"teacher123", bcrypt.gensalt()).decode()
            conn.execute("INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)", 
                         ("teacher", t_hash, "المعلم", "teacher"))
# ════════════════════════════════════════════════════════════════════
# دوال قاعدة البيانات
# ════════════════════════════════════════════════════════════════════

def convert_numbers_to_en(text):
    """تحويل الأرقام العربية (٠١٢٣٤٥٦٧٨٩) إلى إنجليزية (0123456789)"""
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    translation_table = str.maketrans(arabic_digits, english_digits)
    return str(text).translate(translation_table)

def verify_user(username: str, password: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
    if row and bcrypt.checkpw(password.encode(), row["password"].encode()):
        return dict(row)
    return None

def get_all_users():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT id,username,name,role FROM users").fetchall()]

def add_user(username, password, name, role):
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
            (username, hashed, name, role)
        )

def delete_user(user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))

def change_password(username, new_password):
    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    with get_conn() as conn:
        conn.execute("UPDATE users SET password=? WHERE username=?", (hashed, username))

def get_classes():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM classes ORDER BY name").fetchall()]

def add_class(name: str):
    with get_conn() as conn:
        conn.execute("INSERT INTO classes(name) VALUES(?)", (name,))

def delete_class(class_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM classes WHERE id=?", (class_id,))


def get_all_students():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT s.*, c.name AS class_name
               FROM students s LEFT JOIN classes c ON s.class_id = c.id
               ORDER BY CAST(s.personal_id AS INTEGER) ASC"""
        ).fetchall()]

def get_students(class_id: int):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM students WHERE class_id=? ORDER BY CAST(personal_id AS INTEGER) ASC", 
            (class_id,)
        ).fetchall()]
    
# دالة للتحقق مما إذا كان الرقم الشخصي موجوداً مسبقاً في النظام
def check_personal_id_exists(personal_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT c.name as class_name, s.name as student_name FROM students s JOIN classes c ON s.class_id=c.id WHERE s.personal_id=?", 
            (personal_id,)
        ).fetchone()
        return dict(row) if row else None
# تم تحديث الدالة لتستقبل الرقم الشخصي
# ضع هذه الدالة الجديدة مكانها

def add_student_full(pid, name, cid, mobile, phone, house, road, block, area, school, group, birth_date, photo, notes):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO students (
                personal_id, name, class_id, mobile, phone, 
                house, road, block, area, school_name, 
                group_name, birth_date, photo, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, name, cid, mobile, phone, house, road, block, area, school, group, birth_date, photo, notes))

def update_student_full(std_id, pid, name, cid, mobile, phone, house, road, block, area, school, group, birth_date, photo, notes):
    with get_conn() as conn:
        conn.execute("""
            UPDATE students SET 
                personal_id=?, name=?, class_id=?, mobile=?, phone=?, 
                house=?, road=?, block=?, area=?, school_name=?, 
                group_name=?, birth_date=?, photo=?, notes=?
            WHERE id=?
        """, (pid, name, cid, mobile, phone, house, road, block, area, school, group, birth_date, photo, notes, std_id))
def delete_student(student_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM students WHERE id=?", (student_id,))

def move_student(student_id: int, new_class_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE students SET class_id=? WHERE id=?", (new_class_id, student_id))

# تحديث الاستيراد ليشمل عمود الرقم الشخصي
def import_students_from_df(df: pd.DataFrame):
    added = 0
    with get_conn() as conn:
        for _, row in df.iterrows():
            cls_name = str(row.get("الصف", "")).strip()
            pid      = str(row.get("الرقم الشخصي", "")).strip()
            std_name = str(row.get("الطالب", "")).strip()
            
            if not cls_name or not std_name or not pid or cls_name == "nan" or std_name == "nan" or pid == "nan":
                continue
                
            cls = conn.execute("SELECT id FROM classes WHERE name=?", (cls_name,)).fetchone()
            if not cls:
                conn.execute("INSERT INTO classes(name) VALUES(?)", (cls_name,))
                cls = conn.execute("SELECT id FROM classes WHERE name=?", (cls_name,)).fetchone()
                
            exists = conn.execute("SELECT 1 FROM students WHERE personal_id=?", (pid,)).fetchone()
            if not exists:
                conn.execute("INSERT INTO students(personal_id, name, class_id) VALUES(?,?,?)", (pid, std_name, cls["id"]))
                added += 1
    return added

def get_attendance(class_id: int, date: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT student_id, status FROM attendance WHERE class_id=? AND date=?",
            (class_id, date)
        ).fetchall()
    return {r["student_id"]: r["status"] for r in rows}

def set_attendance(student_id: int, class_id: int, date: str, status: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO attendance(student_id,class_id,date,status)
               VALUES(?,?,?,?)
               ON CONFLICT(student_id,date) DO UPDATE SET status=excluded.status""",
            (student_id, class_id, date, status)
        )

def get_today_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                SUM(CASE WHEN status='h' THEN 1 ELSE 0 END) AS h,
                SUM(CASE WHEN status='g' THEN 1 ELSE 0 END) AS g,
                SUM(CASE WHEN status='m' THEN 1 ELSE 0 END) AS m
            FROM attendance WHERE date=?
        """, (today,)).fetchone()
    return (row["h"] or 0, row["g"] or 0, row["m"] or 0)

def get_absent_streak():
    results = []
    with get_conn() as conn:
        students = conn.execute(
            "SELECT s.id, s.name, c.name AS cls FROM students s JOIN classes c ON s.class_id=c.id"
        ).fetchall()
        for std in students:
            streak = 0
            day = datetime.now()
            for _ in range(30):
                date_str = day.strftime("%Y-%m-%d")
                rec = conn.execute(
                    "SELECT status FROM attendance WHERE student_id=? AND date=?",
                    (std["id"], date_str)
                ).fetchone()
                if rec and rec["status"] == "g":
                    streak += 1
                else:
                    break
                day -= timedelta(days=1)
            if streak >= 3:
                results.append({"name": std["name"], "class": std["cls"], "streak": streak})
    return results

def get_report_data(class_id: int, start: str, end: str, filter_name: str = ""):
    with get_conn() as conn:
        students = conn.execute(
            "SELECT * FROM students WHERE class_id=? ORDER BY name", (class_id,)
        ).fetchall()
        rows = []
        for std in students:
            if filter_name and filter_name not in std["name"]:
                continue
            rec = conn.execute("""
                SELECT
                    SUM(CASE WHEN status='h' THEN 1 ELSE 0 END) AS h,
                    SUM(CASE WHEN status='g' THEN 1 ELSE 0 END) AS g,
                    SUM(CASE WHEN status='m' THEN 1 ELSE 0 END) AS m
                FROM attendance
                WHERE student_id=? AND date BETWEEN ? AND ?
            """, (std["id"], start, end)).fetchone()
            rows.append({
                "اسم الطالب": std["name"],
                "حاضر": rec["h"] or 0,
                "غائب": rec["g"] or 0,
                "متأخر": rec["m"] or 0,
            })
    return rows

def get_class_today_pct(class_id: int, date: str, total: int):
    if total == 0:
        return 0
    with get_conn() as conn:
        h = conn.execute(
            "SELECT COUNT(*) AS c FROM attendance WHERE class_id=? AND date=? AND status='h'",
            (class_id, date)
        ).fetchone()["c"]
    return int((h / total) * 100)


# ============================================================
#  دالة: بطاقة عرض الطالب
# ============================================================
def render_student_card(std):
    initials = "".join([w[0] for w in std["name"].split()[:2]])
 
    if std.get("photo"):
        photo_html = (
            f"<img src='data:image/png;base64,{base64.b64encode(std['photo']).decode()}' "
            f"style='width:76px;height:76px;border-radius:12px;object-fit:cover;"
            f"margin-left:16px;flex-shrink:0;border:2px solid #e8eaf6;'>"
        )
    else:
        photo_html = (
            f"<div style='width:76px;height:76px;border-radius:12px;background:#e8eaf6;"
            f"display:flex;align-items:center;justify-content:center;"
            f"font-size:24px;font-weight:700;color:#1a237e;"
            f"margin-left:16px;flex-shrink:0;letter-spacing:1px;'>"
            f"{initials}</div>"
        )
 
    class_name  = std.get("class_name") or "غير محدد"
    mobile      = std.get("mobile") or "-"
    school      = std.get("school_name") or ""
    school_part = f"🏫 {school} &nbsp;|&nbsp;" if school else ""
 
    st.markdown(
        f"""
        <div style='background:white;border-radius:15px;padding:14px 18px;
                    border-right:5px solid #1a237e;
                    box-shadow:0 3px 10px rgba(26,35,126,0.09);
                    margin-bottom:10px;display:flex;align-items:center;'>
            {photo_html}
            <div style='flex:1;min-width:0;'>
                <div style='font-family:monospace;font-size:12px;
                            color:#ef6c00;font-weight:700;letter-spacing:.5px;'>
                    {std['personal_id']}
                </div>
                <div style='font-size:17px;font-weight:700;color:#1a237e;
                            margin:3px 0 4px;white-space:nowrap;
                            overflow:hidden;text-overflow:ellipsis;'>
                    {std['name']}
                </div>
                <div style='font-size:12px;color:#546e7a;'>
                    {school_part}📂 {class_name} &nbsp;|&nbsp; 📞 {mobile}
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
 

# ════════════════════════════════════════════════════════════════════
# مساعد PDF
# ════════════════════════════════════════════════════════════════════
def fix_arabic(text: str) -> str:
    return get_display(arabic_reshaper.reshape(str(text)))

def build_pdf_bytes(class_name: str, rows_data: list, start: str, end: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    font_name = "Helvetica"
    try:
        pdfmetrics.registerFont(TTFont("ArabicFont", "arial.ttf"))
        font_name = "ArabicFont"
    except Exception:
        pass

    def ar(t):
        return fix_arabic(t) if font_name == "ArabicFont" else str(t)

    s_title = ParagraphStyle("t", fontName=font_name, fontSize=18,
                              alignment=TA_CENTER,
                              textColor=rl_colors.HexColor("#1a237e"), spaceAfter=4)
    s_sub   = ParagraphStyle("s", fontName=font_name, fontSize=11,
                              alignment=TA_CENTER,
                              textColor=rl_colors.HexColor("#3949ab"), spaceAfter=3)
    s_cell  = ParagraphStyle("c", fontName=font_name, fontSize=10, alignment=TA_CENTER)
    s_stat  = ParagraphStyle("st", fontName=font_name, fontSize=11,
                              alignment=TA_CENTER,
                              textColor=rl_colors.HexColor("#2e7d32"))

    elements = []
    elements.append(Paragraph(ar(f"تقرير حضور الطلاب  —  {class_name}"), s_title))
    elements.append(Paragraph(ar(f"الفترة من {start} إلى {end}"), s_sub))
    elements.append(Paragraph(ar(f"تاريخ الطباعة: {datetime.now().strftime('%Y-%m-%d')}"), s_sub))
    elements.append(Spacer(1, 0.3*cm))
    elements.append(HRFlowable(width="100%", thickness=2, color=rl_colors.HexColor("#1a237e")))
    elements.append(Spacer(1, 0.4*cm))

    total_h = sum(r["حاضر"] for r in rows_data)
    total_g = sum(r["غائب"] for r in rows_data)
    total_m = sum(r["متأخر"] for r in rows_data)

    summary = [[
        Paragraph(ar(f"متأخر: {total_m}"), s_stat),
        Paragraph(ar(f"غائب: {total_g}"), s_stat),
        Paragraph(ar(f"حاضر: {total_h}"), s_stat),
        Paragraph(ar(f"الطلاب: {len(rows_data)}"), s_stat),
    ]]
    st_tbl = Table(summary, colWidths=[4*cm]*4)
    st_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), rl_colors.HexColor("#e8eaf6")),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("GRID",       (0,0), (-1,-1), 0.5, rl_colors.HexColor("#c5cae9")),
        ("ROWHEIGHT",  (0,0), (-1,-1), 30),
    ]))
    elements.append(st_tbl)
    elements.append(Spacer(1, 0.5*cm))

    header = [
        Paragraph(ar("م"), s_cell),
        Paragraph(ar("اسم الطالب"), s_cell),
        Paragraph(ar("حاضر"), s_cell),
        Paragraph(ar("غائب"), s_cell),
        Paragraph(ar("متأخر"), s_cell),
    ]
    table_data = [header]
    for i, row in enumerate(rows_data, 1):
        table_data.append([
            Paragraph(str(i), s_cell),
            Paragraph(ar(row["اسم الطالب"]), s_cell),
            Paragraph(str(row["حاضر"]), s_cell),
            Paragraph(str(row["غائب"]), s_cell),
            Paragraph(str(row["متأخر"]), s_cell),
        ])

    t = Table(table_data, colWidths=[1.5*cm, 7*cm, 2.5*cm, 2.5*cm, 2.5*cm], repeatRows=1)
    ts_style = [
        ("BACKGROUND", (0,0), (-1,0), rl_colors.HexColor("#1a237e")),
        ("TEXTCOLOR",  (0,0), (-1,0), rl_colors.white),
        ("FONTNAME",   (0,0), (-1,-1), font_name),
        ("FONTSIZE",   (0,0), (-1,0), 11),
        ("FONTSIZE",   (0,1), (-1,-1), 10),
        ("ALIGN",      (0,0), (-1,-1), "CENTER"),
        ("GRID",       (0,0), (-1,-1), 0.5, rl_colors.HexColor("#c5cae9")),
        ("ROWHEIGHT",  (0,0), (-1,-1), 26),
    ]
    for idx, row in enumerate(rows_data, 1):
        if row["غائب"] >= 5:
            ts_style.append(("BACKGROUND", (3, idx), (3, idx), rl_colors.HexColor("#ffcdd2")))
        elif idx % 2 == 0:
            ts_style.append(("BACKGROUND", (0, idx), (-1, idx), rl_colors.HexColor("#e8eaf6")))
    t.setStyle(TableStyle(ts_style))
    elements.append(t)

    doc.build(elements)
    buf.seek(0)
    return buf.read()

# ════════════════════════════════════════════════════════════════════
# Session State
# ════════════════════════════════════════════════════════════════════
def init_session():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in   = False
        st.session_state.user        = None
        st.session_state.role        = None
        st.session_state.page        = "home"

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except Exception as e:
        return "" # في حال عدم العثور على الصورة
# ════════════════════════════════════════════════════════════════════
# صفحة تسجيل الدخول
# ════════════════════════════════════════════════════════════════════
def page_login():
    # ... (احتفظ بكود الـ CSS الموجود سابقاً هنا) ...
    st.markdown("""
    <style>
        /* كود الـ CSS الخاص بالبطاقة والأزرار كما هو */
        [data-testid="stForm"] { background-color: #ffffff; border-radius: 15px; padding: 30px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08); border: 1px solid #e8eaf6; }
        .stTextInput input:focus { border-color: #1a237e !important; box-shadow: 0 0 0 1px #1a237e !important; }
        button[kind="primary"] { background-color: #1a237e !important; border: none !important; border-radius: 8px !important; padding: 0.6rem 1rem !important; font-size: 1.1rem !important; font-weight: bold !important; transition: all 0.3s ease !important; }
        button[kind="primary"]:hover { background-color: #283593 !important; box-shadow: 0 4px 12px rgba(26, 35, 126, 0.3) !important; transform: translateY(-2px); }
    </style>
    """, unsafe_allow_html=True)

    # قراءة الصورة المحلية من جهازك (ضع اسم صورتك هنا)
    img_base64 = get_base64_image("logo.png") 
    
    # بناء مسار الصورة بصيغة Base64
    img_src = f"data:image/png;base64,{img_base64}" if img_base64 else ""

    col1, col2, col3 = st.columns([1, 1.5, 1]) 
    
    with col2:
        # استخدام الصورة المحولة داخل الـ HTML
        st.markdown(f"""
        <div style='text-align:center; padding: 20px 0 30px;'>
            <img src='{img_src}' width='120' style='margin-bottom: 20px; filter: drop-shadow(0px 4px 8px rgba(0,0,0,0.1));'>
            <h1 style='color:#1a237e; margin:0; font-weight: 800; font-size: 2.4rem;'>نظام تسجيل الحضور</h1>
            <p style='color:#5c6bc0; font-size: 1.1rem; margin-top: 8px; font-weight: 500;'>إدارة الحضور والغياب لمشاريع التعليم الديني</p>
        </div>
        """, unsafe_allow_html=True)

        # ... (باقي كود نموذج تسجيل الدخول st.form يبقى كما هو تماماً) ...
        with st.form("login_form"):
            st.markdown("<h4 style='color: #3949ab; margin-bottom: 20px; font-size: 1.1rem;'>تسجيل الدخول للمنصة</h4>", unsafe_allow_html=True)
            username = st.text_input("اسم المستخدم", placeholder="أدخل اسم المستخدم هنا...")
            password = st.text_input("كلمة المرور", type="password", placeholder="أدخل كلمة المرور هنا...")
            st.write("") 
            submitted = st.form_submit_button("دخول إلى النظام ←", use_container_width=True, type="primary")

        if submitted:
            user = verify_user(username, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user      = user
                st.session_state.role      = user["role"]
                st.session_state.page      = "home"
                st.rerun()
            else:
                st.error("❌ عذراً، اسم المستخدم أو كلمة المرور غير صحيحة.")

        st.markdown("""
        <div style='text-align:center; margin-top: 25px; color: #7986cb; font-size: 0.85rem; background-color: #f8f9fa; padding: 12px; border-radius: 8px; border: 1px dashed #c5cae9;'>
            <b>بيانات الدخول التجريبية:</b><br>
            المشرف: <code style='color:#1a237e;'>admin / admin123</code> &nbsp;|&nbsp; المعلم: <code style='color:#1a237e;'>teacher / teacher123</code>
        </div>
        """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# الشريط الجانبي (المطور)
# ════════════════════════════════════════════════════════════════════
def render_sidebar():
    with st.sidebar:
        # الصندوق العلوي الأول: عنوان النظام
        st.markdown("""
        <div style='background-color: #283593; color: #ffffff; text-align: center; 
                    padding: 14px; border-radius: 10px; margin-bottom: 12px; 
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-size: 1.2rem; font-weight: bold;'>
            🎓 نظام الحضور
        </div>
        """, unsafe_allow_html=True)

        # الصندوق العلوي الثاني: بيانات المستخدم
        role_text = 'مشرف إداري' if st.session_state.role == 'admin' else 'معلم'
        st.markdown(f"""
        <div style='background-color: #3949ab; color: #ffffff; text-align: center; 
                    padding: 15px; border-radius: 10px; margin-bottom: 30px;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);'>
            <div style='font-size: 1.1rem; font-weight: bold; margin-bottom: 6px;'>
                👤 {st.session_state.user['name']}
            </div>
            <div style='font-size: 0.95rem; opacity: 0.9;'>
                {role_text}
            </div>
        </div>
        """, unsafe_allow_html=True)

        # أزرار القسم العام
        if st.button("🏠 الرئيسية", use_container_width=True): st.session_state.page = "home"; st.rerun()
        if st.button("📝 تسجيل الحضور", use_container_width=True): st.session_state.page = "attendance"; st.rerun()

        # قسم الإدارة (يظهر للمشرف فقط)
        if st.session_state.role == "admin":
            
            # الفاصل المخصص لكلمة "إدارة"
            st.markdown("""
            <div style='display: flex; align-items: center; text-align: center; margin: 25px 0 15px 0;'>
                <div style='flex: 1; border-bottom: 1px solid #c5cae9;'></div>
                <span style='padding: 0 15px; color: #7986cb; font-size: 0.95rem; font-weight: bold;'>إدارة</span>
                <div style='flex: 1; border-bottom: 1px solid #c5cae9;'></div>
            </div>
            """, unsafe_allow_html=True)

            # أزرار المشرف
            if st.button("🏫 إدارة الصفوف", use_container_width=True): st.session_state.page = "classes"; st.rerun()
            if st.button("👨‍🎓 إدارة الطلاب", use_container_width=True): st.session_state.page = "students"; st.rerun()
            if st.button("📊 الأرشيف والتقارير", use_container_width=True): st.session_state.page = "reports"; st.rerun()
            if st.button("🔑 إدارة المستخدمين", use_container_width=True): st.session_state.page = "users"; st.rerun()

        st.markdown("<br><br>", unsafe_allow_html=True)
        
        # زر الخروج (بلون أحمر فاتح لتمييزه)
        st.markdown("""
        <style>
            .logout-btn button { background-color: #fff0f0 !important; border-color: #ffcdd2 !important; color: #c62828 !important; }
            .logout-btn button:hover { background-color: #ffebee !important; border-color: #e53935 !important; }
        </style>
        """, unsafe_allow_html=True)
        
        st.markdown('<div class="logout-btn">', unsafe_allow_html=True)
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            for k in ["logged_in", "user", "role", "page"]:
                st.session_state.pop(k, None)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
# ════════════════════════════════════════════════════════════════════
# الصفحة الرئيسية — لوحة الإحصائيات
# ════════════════════════════════════════════════════════════════════
def page_home():
    st.title("🏠 لوحة الإحصائيات العامة")
    st.markdown("<p style='color: #78909c; font-size: 1.1rem; margin-bottom: 5px;'>نظرة عامة على أداء نظام تسجيل الحضور اليوم</p>", unsafe_allow_html=True)
    
    # جلب التاريخ واسم اليوم بالعربية
    days_ar = {0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة", 5: "السبت", 6: "الأحد"}
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    day_name = days_ar[today.weekday()]
    
    st.markdown(f"<p style='color: #1a237e; font-weight: bold;'>📅 {day_name} | {date_str}</p>", unsafe_allow_html=True)
    st.write("") # مسافة بسيطة

    # جلب الإحصائيات من قاعدة البيانات
    h, g, m = get_today_stats()
    classes = get_classes()
    total_students = sum(len(get_students(c["id"])) for c in classes)

    # ── 1. توزيع البطاقات العلوية ──
    c1, c2, c3, c4, c5 = st.columns(5)
    
    metrics = [
        (c1, len(classes), "إجمالي الصفوف", "#1a237e", "🏫"),
        (c2, total_students, "إجمالي الطلاب", "#37474f", "👨‍🎓"),
        (c3, h, "حضور اليوم", "#2e7d32", "✅"),
        (c4, g, "غياب اليوم", "#c62828", "❌"),
        (c5, m, "متأخرون اليوم", "#ef6c00", "⏰")
    ]

    for col, val, label, color, icon in metrics:
        with col:
            # تصميم بطاقة احترافي مع ظلال ناعمة (Card Effect)
            st.markdown(f"""
            <div style='background: #ffffff; border-radius: 16px; padding: 20px; text-align: center; 
                        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05); border: 1px solid #f0f2f6; margin-bottom: 20px;
                        transition: transform 0.3s ease;'>
                <div style='font-size: 2.2rem; margin-bottom: 5px; opacity: 0.9;'>{icon}</div>
                <div style='font-size: 2.3rem; font-weight: 800; margin: 5px 0; color: {color};'>{val}</div>
                <div style='font-size: 0.95rem; color: #546e7a; font-weight: 600;'>{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 2. قسم الرسوم البيانية والتنبيهات ──
    col_chart, col_alerts = st.columns([1.6, 1])

    with col_chart:
        st.subheader("📈 تحليل نسب الحضور اليوم")
        # وضع الرسم البياني في حاوية بيضاء أنيقة
        st.markdown("<div style='background: white; padding: 20px; border-radius: 15px; border: 1px solid #eef2f7; box-shadow: 0 4px 15px rgba(0,0,0,0.02);'>", unsafe_allow_html=True)
        if not classes:
            st.info("لا توجد بيانات صفوف متاحة حالياً.")
        else:
            chart_data = []
            for cls in classes:
                students = get_students(cls["id"])
                if not students: continue
                pct = get_class_today_pct(cls["id"], date_str, len(students))
                chart_data.append({"الصف": cls["name"], "النسبة %": pct})
            
            if chart_data:
                df_chart = pd.DataFrame(chart_data).set_index("الصف")
                st.bar_chart(df_chart, color="#1a237e") # توحيد لون الرسم البياني مع الهوية الزرقاء
            else:
                st.info("لم يتم تسجيل أي حضور اليوم بعد.")
        st.markdown("</div>", unsafe_allow_html=True)

    with col_alerts:
        st.subheader("⚠️ تنبيهات الغياب المتكرر")
        absent_list = get_absent_streak()
        
        if not absent_list:
            # رسالة نجاح بشكل بطاقة أنيقة
            st.markdown("""
            <div style='background: #f1f8e9; border-right: 5px solid #2e7d32; padding: 15px; border-radius: 10px; margin-top: 5px;'>
                <b style='color: #1b5e20;'>جميع الطلاب منتظمون حالياً ✅</b><br>
                <span style='color: #388e3c; font-size: 0.85rem;'>لا يوجد طلاب غائبون لثلاثة أيام متتالية.</span>
            </div>
            """, unsafe_allow_html=True)
        else:
            # بطاقات التنبيه للطلاب الغائبين
            for item in absent_list:
                st.markdown(f"""
                <div style='background: #fff5f5; border-right: 5px solid #e53935; padding: 15px; border-radius: 10px; margin-bottom: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.02);'>
                    <b style='color: #b71c1c; font-size: 1.05rem;'>{item['name']}</b><br>
                    <span style='color: #546e7a; font-size: 0.9rem;'>🏫 {item['class']} | غائب لـ <b>{item['streak']}</b> أيام متتالية</span>
                </div>
                """, unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# تسجيل الحضور (تم التحديث لدعم الموبايل والتحضير المجمع)
# ════════════════════════════════════════════════════════════════════
def page_attendance():
    st.title("📝 تسجيل الحضور اليومي")

    classes = get_classes()
    if not classes:
        st.warning("لا توجد صفوف مضافة. يرجى إضافة صفوف أولاً من قسم الإدارة.")
        return

    # ── 1. إعداد حالة الجلسة للتاريخ ──
    if "att_date" not in st.session_state:
        st.session_state.att_date = datetime.now().date()

    # قاموس أيام الأسبوع بالعربية
    days_ar = {0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس", 4: "الجمعة", 5: "السبت", 6: "الأحد"}

    # ── 2. التحكم بالصف والتاريخ (تصميم احترافي) ──
    with st.container():
        st.markdown("<div style='background: #f8f9fa; padding: 15px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #eef2f7;'>", unsafe_allow_html=True)
        
        cls_names = [c["name"] for c in classes]
        selected_cls_name = st.selectbox("📌 اختر الصف:", cls_names)
        selected_cls = next((c for c in classes if c["name"] == selected_cls_name), None)

        st.markdown("<div style='margin-top: 15px;'></div>", unsafe_allow_html=True)
        
        # أزرار التنقل في التاريخ وإظهار اليوم
        col_prev, col_date, col_next = st.columns([1, 2, 1])
        
        with col_next:
            st.write("") # للمحاذاة
            if st.button("التالي ◀", use_container_width=True):
                st.session_state.att_date += timedelta(days=1)
                st.rerun()
                
        with col_date:
            day_name = days_ar[st.session_state.att_date.weekday()]
            st.markdown(f"<div style='text-align: center; color: #1a237e; font-weight: bold; margin-bottom: 4px; font-size: 1.1rem;'>{day_name}</div>", unsafe_allow_html=True)
            new_date = st.date_input("التاريخ", value=st.session_state.att_date, label_visibility="collapsed")
            if new_date != st.session_state.att_date:
                st.session_state.att_date = new_date
                st.rerun()
                
        with col_prev:
            st.write("") # للمحاذاة
            if st.button("▶ السابق", use_container_width=True):
                st.session_state.att_date -= timedelta(days=1)
                st.rerun()
                
        st.markdown("</div>", unsafe_allow_html=True)

    if not selected_cls: return

    date_str = st.session_state.att_date.strftime("%Y-%m-%d")
    students = get_students(selected_cls["id"])
    att_data = get_attendance(selected_cls["id"], date_str)

    if not students:
        st.info("هذا الصف لا يحتوي على طلاب بعد.")
        return

    # ── 3. شريط الإحصائيات ونسبة الإنجاز ──
    h_c = sum(1 for s in students if att_data.get(s["id"]) == "h")
    g_c = sum(1 for s in students if att_data.get(s["id"]) == "g")
    m_c = sum(1 for s in students if att_data.get(s["id"]) == "m")
    total = len(students)
    recorded = len(att_data)
    progress = int((recorded / total) * 100) if total > 0 else 0

    st.markdown(f"""
    <div style='display: flex; justify-content: space-between; align-items: center; background: #e8eaf6; padding: 12px 20px; border-radius: 8px; margin-bottom: 15px; font-weight: bold;'>
        <div style='color: #2e7d32;'>✅ حاضر: {h_c}</div>
        <div style='color: #c62828;'>❌ غائب: {g_c}</div>
        <div style='color: #ef6c00;'>⏰ متأخر: {m_c}</div>
        <div style='color: #1a237e;'>📊 المجموع: {total}</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.progress(progress / 100, text=f"نسبة الإنجاز: {progress}% ({recorded} من {total} تم تحضيرهم)")

    # ── 4. الإجراءات الجماعية (مع نوافذ تأكيد منبثقة) ──
    col_all1, col_all2, _ = st.columns([1.5, 1.5, 3])
    with col_all1:
        with st.popover("✅ تحضير الجميع", use_container_width=True):
            st.markdown("<b>هل أنت متأكد من تحضير جميع الطلاب؟</b>", unsafe_allow_html=True)
            if st.button("نعم، تأكيد", type="primary", use_container_width=True):
                for s in students:
                    set_attendance(s["id"], selected_cls["id"], date_str, "h")
                st.rerun()
                
    with col_all2:
        with st.popover("🔄 إعادة الضبط", use_container_width=True):
            st.markdown("<b style='color:#c62828;'>تحذير: سيتم مسح بيانات اليوم، هل أنت متأكد؟</b>", unsafe_allow_html=True)
            if st.button("نعم، مسح البيانات", use_container_width=True):
                with get_conn() as conn:
                    conn.execute("DELETE FROM attendance WHERE class_id=? AND date=?", (selected_cls["id"], date_str))
                st.rerun()

    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)

    # ── 5. قائمة الطلاب والأزرار التفاعلية المباشرة ──
    for i, student in enumerate(students, 1):
        current_status = att_data.get(student["id"], "none")
        
        # تغيير لون خلفية الطالب بناءً على حالته
        bg_color, border_color = "#ffffff", "#eef2f7"
        if current_status == "h": bg_color, border_color = "#f1f8e9", "#aed581"
        elif current_status == "g": bg_color, border_color = "#ffebee", "#e57373"
        elif current_status == "m": bg_color, border_color = "#fff8e1", "#ffb74d"

        with st.container():
            st.markdown(f"""
            <div style='background-color: {bg_color}; border: 1px solid {border_color}; border-radius: 12px; padding: 12px 10px 0px 10px; margin-bottom: 8px; transition: 0.3s;'>
            """, unsafe_allow_html=True)
            
            # ترتيب الأعمدة: إعطاء الاسم مساحة كبيرة (3.5) لضمان ثباته باليمين
            c_name, c_h, c_g, c_m = st.columns([3.5, 1.2, 1.2, 1.2])
            
            with c_name:
                # محاذاة النص لليمين مع منع التكسر (nowrap)
                st.markdown(f"<div style='text-align: right; padding-top: 8px; font-weight: bold; color: #1a237e; font-size: 1.1rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'>{i}. {student['name']}</div>", unsafe_allow_html=True)
            
            # زر حاضر
            with c_h:
                if st.button("✅ حاضر", key=f"h_{student['id']}", type="primary" if current_status=="h" else "secondary", use_container_width=True):
                    # التراجع في حال كان الطالب مسجلاً بنفس الحالة
                    if current_status == "h":
                        with get_conn() as conn: conn.execute("DELETE FROM attendance WHERE student_id=? AND class_id=? AND date=?", (student["id"], selected_cls["id"], date_str))
                    else:
                        set_attendance(student["id"], selected_cls["id"], date_str, "h")
                    st.rerun()
            
            # زر غائب
            with c_g:
                if st.button("❌ غائب", key=f"g_{student['id']}", type="primary" if current_status=="g" else "secondary", use_container_width=True):
                    if current_status == "g":
                        with get_conn() as conn: conn.execute("DELETE FROM attendance WHERE student_id=? AND class_id=? AND date=?", (student["id"], selected_cls["id"], date_str))
                    else:
                        set_attendance(student["id"], selected_cls["id"], date_str, "g")
                    st.rerun()
                    
            # زر متأخر
            with c_m:
                if st.button("⏰ متأخر", key=f"m_{student['id']}", type="primary" if current_status=="m" else "secondary", use_container_width=True):
                    if current_status == "m":
                        with get_conn() as conn: conn.execute("DELETE FROM attendance WHERE student_id=? AND class_id=? AND date=?", (student["id"], selected_cls["id"], date_str))
                    else:
                        set_attendance(student["id"], selected_cls["id"], date_str, "m")
                    st.rerun()
            
            st.markdown("</div>", unsafe_allow_html=True)
# ════════════════════════════════════════════════════════════════════
# إدارة الصفوف
# ════════════════════════════════════════════════════════════════════
def page_classes():
    st.title("🏫 إدارة الصفوف الدراسية")
    st.markdown("<p style='color: #78909c;'>إضافة وتعديل وحذف الصفوف والمجموعات الدراسية</p>", unsafe_allow_html=True)

    classes = get_classes()
    total_classes = len(classes)
    total_students = sum(len(get_students(c["id"])) for c in classes)

    # ── 1. إحصائيات سريعة ──
    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        st.markdown(f"""
        <div style='background: #e8eaf6; padding: 15px; border-radius: 12px; text-align: center; border: 1px solid #c5cae9;'>
            <div style='font-size: 0.9rem; color: #1a237e; font-weight: bold;'>إجمالي الصفوف</div>
            <div style='font-size: 1.8rem; font-weight: 800; color: #1a237e;'>{total_classes}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div style='background: #f1f8e9; padding: 15px; border-radius: 12px; text-align: center; border: 1px solid #c5cae9;'>
            <div style='font-size: 0.9rem; color: #2e7d32; font-weight: bold;'>إجمالي الطلاب</div>
            <div style='font-size: 1.8rem; font-weight: 800; color: #2e7d32;'>{total_students}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 2. إضافة صف جديد ──
    with st.container():
        st.markdown("<div style='background: #ffffff; padding: 20px; border-radius: 15px; border: 1px solid #eef2f7; box-shadow: 0 4px 12px rgba(0,0,0,0.03);'>", unsafe_allow_html=True)
        st.subheader("➕ إضافة صف جديد")
        with st.form("add_class_form", clear_on_submit=True):
            new_cls = st.text_input("اسم الصف الدراسي", placeholder="مثال: الصف الأول - المجموعة أ")
            submit_btn = st.form_submit_button("حفظ الصف الجديد 💾", use_container_width=True)
            
            if submit_btn:
                name = new_cls.strip()
                if not name:
                    st.error("⚠️ يرجى كتابة اسم الصف")
                else:
                    try:
                        add_class(name)
                        st.success(f"✅ تم إضافة '{name}' بنجاح")
                        st.rerun()
                    except Exception:
                        st.error("⚠️ هذا الصف موجود مسبقاً")
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── 3. عرض القائمة الحالية ──
    st.subheader("📋 الصفوف الحالية")
    
    if not classes:
        st.info("لا توجد صفوف مضافة حالياً. ابدأ بإضافة أول صف من النموذج أعلاه.")
    else:
        for cls in classes:
            student_count = len(get_students(cls["id"]))
            
            # تصميم بطاقة الصف
            with st.container():
                st.markdown(f"""
                <div style='background: white; border: 1px solid #eef2f7; border-radius: 12px; padding: 15px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.02);'>
                """, unsafe_allow_html=True)
                
                col_info, col_count, col_actions = st.columns([3, 1, 1])
                
                with col_info:
                    st.markdown(f"<div style='font-size: 1.2rem; font-weight: bold; color: #1a237e; padding-top: 5px;'>🏫 {cls['name']}</div>", unsafe_allow_html=True)
                
                with col_count:
                    st.markdown(f"<div style='background: #e3f2fd; color: #1e88e5; padding: 6px 12px; border-radius: 20px; text-align: center; font-weight: bold; margin-top: 5px;'>👤 {student_count} طالب</div>", unsafe_allow_html=True)
                
                with col_actions:
                    # نافذة تأكيد الحذف منبثقة لمنع الخطأ
                    with st.popover("🗑 حذف", use_container_width=True):
                        st.markdown(f"<p style='color: #c62828;'>هل أنت متأكد من حذف <b>{cls['name']}</b>؟<br><small>سيؤدي ذلك لحذف كافة بيانات الطلاب والحضور المرتبطة به!</small></p>", unsafe_allow_html=True)
                        if st.button("نعم، احذف نهائياً", key=f"del_{cls['id']}", type="primary", use_container_width=True):
                            delete_class(cls["id"])
                            st.rerun()
                
                st.markdown("</div>", unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════
# إدارة الطلاب
# ════════════════════════════════════════════════════════════════════
def page_students():
    # ── جلب البيانات ──────────────────────────────────────────
    all_students     = get_all_students()        # ← دالتك الأصلية
    available_classes = get_classes()             # ← دالتك الأصلية
    class_names      = [c["name"] for c in available_classes]
    total_count      = len(all_students)
 
    # ── حالة نموذج الإضافة ────────────────────────────────────
    if "add_temp" not in st.session_state:
        st.session_state.add_temp = {
            "pid": "", "name": "", "mob": "", "other": "",
            "sch": "", "h": "", "r": "", "b": "", "a": "",
            "notes": "", "cls_idx": 0,
        }
 
    # ── العنوان ───────────────────────────────────────────────
    st.markdown(
        f"### 👨‍🎓 نظام إدارة الطلاب "
        f"<span style='background:#1a237e;color:white;padding:3px 12px;"
        f"border-radius:12px;font-size:.9rem;'>العدد الإجمالي: {total_count}</span>",
        unsafe_allow_html=True,
    )
 
    # ── شريط البحث والفلتر ────────────────────────────────────
    c_search, c_filter = st.columns([3, 1])
    with c_search:
        search_query = st.text_input(
            "🔍 ابحث عن طالب:",
            placeholder="الاسم أو الرقم الشخصي...",
            label_visibility="collapsed",
        )
    with c_filter:
        filter_option = st.selectbox(
            "الفرقة",
            options=["الكل", "غير محددة"] + class_names,
            label_visibility="collapsed",
        )
 
    # ══════════════════════════════════════════════════════════
    #  نافذة إضافة طالب جديد
    # ══════════════════════════════════════════════════════════
    with st.popover("➕ إضافة طالب جديد", use_container_width=True):
        st.subheader("📝 تسجيل بيانات الطالب")
 
        col_img, col_main = st.columns([1, 2.5])
 
        with col_img:
            st.markdown("**الصورة الشخصية**")
            photo_in = st.file_uploader(
                "اختر صورة",
                type=["jpg", "jpeg", "png"],
                label_visibility="collapsed",
                key="add_photo",
            )
            if photo_in:
                st.image(photo_in, use_container_width=True)
            else:
                st.markdown(
                    """
                    <div style='width:100%;height:160px;border:2px dashed #1a237e;
                                border-radius:14px;display:flex;flex-direction:column;
                                align-items:center;justify-content:center;
                                color:#1a237e;background:#f3f4fb;gap:6px;'>
                        <span style='font-size:2.2rem;'>🖼️</span>
                        <span style='font-size:.8rem;'>اسحب الصورة هنا</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
 
        with col_main:
            p_in   = st.text_input("الرقم الشخصي *",   value=st.session_state.add_temp["pid"],  placeholder="مثال: 050123456")
            n_in   = st.text_input("الاسم الرباعي *",   value=st.session_state.add_temp["name"], placeholder="الاسم الكامل")
            sch_in = st.text_input("المدرسة",            value=st.session_state.add_temp["sch"])
            cls_in = st.selectbox(
                "الفرقة",
                options=["غير محدد"] + class_names,
                index=st.session_state.add_temp["cls_idx"],
            )
 
        with st.container(border=True):
            st.write("📞 التواصل والعنوان")
            cc1, cc2 = st.columns(2)
            m_in = cc1.text_input("الموبايل",   value=st.session_state.add_temp["mob"])
            o_in = cc2.text_input("هاتف آخر",   value=st.session_state.add_temp["other"])
 
            ca1, ca2, ca3, ca4 = st.columns(4)
            h_in = ca1.text_input("منزل",   value=st.session_state.add_temp["h"])
            r_in = ca2.text_input("طريق",   value=st.session_state.add_temp["r"])
            b_in = ca3.text_input("مجمع",   value=st.session_state.add_temp["b"])
            a_in = ca4.text_input("منطقة",  value=st.session_state.add_temp["a"])
            not_in = st.text_area("ملاحظات إضافية", value=st.session_state.add_temp["notes"])
 
        if st.button("حفظ الطالب في النظام ✅", type="primary", use_container_width=True):
            clean_p = convert_numbers_to_en(p_in.strip())
 
            # احتفظ بالبيانات المؤقتة
            st.session_state.add_temp.update({
                "pid": clean_p, "name": n_in,
                "mob": convert_numbers_to_en(m_in),
                "other": convert_numbers_to_en(o_in),
                "sch": sch_in, "h": h_in, "r": r_in,
                "b": b_in, "a": a_in, "notes": not_in,
                "cls_idx": (["غير محدد"] + class_names).index(cls_in),
            })
 
            if check_personal_id_exists(clean_p):          # ← دالتك الأصلية
                st.error(f"⚠️ الرقم الشخصي ({clean_p}) مسجل مسبقاً.")
            elif len(clean_p) != 9 or not n_in.strip():
                st.error("⚠️ أدخل الاسم و 9 أرقام للرقم الشخصي.")
            else:
                photo_bytes = photo_in.read() if photo_in else None
                target_id   = next((c["id"] for c in available_classes if c["name"] == cls_in), None)
 
                add_student_full(                            # ← دالتك الأصلية
                    clean_p, n_in, target_id,
                    convert_numbers_to_en(m_in),
                    convert_numbers_to_en(o_in),
                    h_in, r_in, b_in, a_in,
                    sch_in, cls_in, None, photo_bytes, not_in,
                )
 
                st.success(f"✅ تم حفظ الطالب {n_in} بنجاح!")
                # تصفير النموذج
                st.session_state.add_temp = {
                    k: (0 if k == "cls_idx" else "")
                    for k in st.session_state.add_temp
                }
                time.sleep(0.8)
                st.rerun()
 
    st.divider()
 
    # ══════════════════════════════════════════════════════════
    #  فلترة وعرض الطلاب
    # ══════════════════════════════════════════════════════════
    filtered_students = []
    for std in all_students:
        matches_search = not search_query or (
            search_query.lower() in std["name"].lower()
            or search_query in std["personal_id"]
        )
        matches_filter = (
            filter_option == "الكل"
            or (filter_option == "غير محددة" and std.get("class_name") in [None, "غير محدد", ""])
            or std.get("class_name") == filter_option
        )
        if matches_search and matches_filter:
            filtered_students.append(std)
 
    filtered_students.sort(key=lambda x: x["personal_id"])
 
    if search_query and not filtered_students:
        st.warning(f"🔍 لا يوجد طالب مطابق لـ: «{search_query}»")
        return
 
    # ── عرض كل طالب ──────────────────────────────────────────
    for std in filtered_students:
 
        # بطاقة العرض الجميلة
        render_student_card(std)
 
       # ══════════════════════════════════════════════════════════
        #  نافذة التعديل والحذف  — استبدل الكود القديم بهذا كاملاً
        # ══════════════════════════════════════════════════════════
        with st.popover(f"⚙️ إدارة بيانات {std['name']}", use_container_width=True):

            st.subheader("📝 تعديل البيانات")

            # ── الصورة ────────────────────────────────────────────
            col_ep, col_ef = st.columns([1, 2.5])

            with col_ep:
                st.markdown("**الصورة الشخصية**")
                if std.get("photo"):
                    st.image(std["photo"], use_container_width=True)
                else:
                    initials = "".join([w[0] for w in std["name"].split()[:2]])
                    st.markdown(
                        f"<div style='width:100%;aspect-ratio:1;border-radius:12px;"
                        f"background:#e8eaf6;display:flex;align-items:center;"
                        f"justify-content:center;font-size:2rem;font-weight:700;"
                        f"color:#1a237e;'>{initials}</div>",
                        unsafe_allow_html=True,
                    )
                e_photo_up = st.file_uploader(
                    "تغيير الصورة",
                    type=["jpg", "jpeg", "png"],
                    key=f"photo_{std['id']}",
                )

            # ── نموذج التعديل (بدون أزرار الحذف) ─────────────────
            with col_ef:
                with st.form(f"edit_form_{std['id']}"):
                    fe1, fe2 = st.columns(2)
                    fe1.text_input("الرقم الشخصي", value=std["personal_id"], disabled=True)
                    e_name = fe2.text_input("الاسم الرباعي", value=std["name"])

                    fec1, fec2 = st.columns(2)
                    e_sch = fec1.text_input("المدرسة", value=std.get("school_name", ""))

                    cls_options = ["غير محدد"] + class_names
                    current_cls = std.get("class_name", "")
                    cls_index   = cls_options.index(current_cls) if current_cls in cls_options else 0
                    e_cls = fec2.selectbox("الفرقة", options=cls_options, index=cls_index)

                    st.write("📍 العنوان والاتصال")
                    ea1, ea2, ea3, ea4 = st.columns(4)
                    e_h = ea1.text_input("منزل",  value=std.get("house", ""))
                    e_r = ea2.text_input("طريق",  value=std.get("road",  ""))
                    e_b = ea3.text_input("مجمع",  value=std.get("block", ""))
                    e_a = ea4.text_input("منطقة", value=std.get("area",  ""))

                    em1, em2 = st.columns(2)
                    e_mob   = em1.text_input("الموبايل", value=std.get("mobile", ""))
                    e_oth   = em2.text_input("رقم آخر",  value=std.get("phone",  ""))
                    e_notes = st.text_area("الملاحظات",  value=std.get("notes",  ""))

                    # زر التحديث فقط داخل الـ form
                    if st.form_submit_button("تحديث ✅", type="primary", use_container_width=True):
                        new_photo  = e_photo_up.read() if e_photo_up else std.get("photo")
                        new_cls_id = next(
                            (c["id"] for c in available_classes if c["name"] == e_cls),
                            None,
                        )
                        update_student_full(                 # ← دالتك الأصلية
                            std["id"], std["personal_id"],
                            e_name, new_cls_id,
                            convert_numbers_to_en(e_mob),
                            convert_numbers_to_en(e_oth),
                            e_h, e_r, e_b, e_a,
                            e_sch, e_cls, None, new_photo, e_notes,
                        )
                        st.success("✅ تم التحديث بنجاح!")
                        time.sleep(0.6)
                        st.rerun()

            # ── الحذف خارج الـ form تماماً ────────────────────────
            st.divider()

            # مفتاح session_state لإظهار تأكيد الحذف
            del_key = f"show_del_{std['id']}"
            if del_key not in st.session_state:
                st.session_state[del_key] = False

            if st.button(
                "🗑️ حذف الطالب",
                key=f"del_btn_{std['id']}",
                use_container_width=True,
            ):
                st.session_state[del_key] = True

            # تأكيد الحذف يظهر فقط بعد الضغط على الزر
            if st.session_state[del_key]:
                st.warning(f"⚠️ هل أنت متأكد من حذف الطالب **{std['name']}**؟ لا يمكن التراجع عن هذا الإجراء.")
                c_confirm, c_cancel = st.columns(2)

                if c_confirm.button(
                    "نعم، احذف نهائياً 🗑️",
                    key=f"del_confirm_{std['id']}",
                    type="primary",
                    use_container_width=True,
                ):
                    delete_student(std["id"])            # ← دالتك الأصلية
                    st.session_state[del_key] = False
                    st.rerun()

                if c_cancel.button(
                    "إلغاء",
                    key=f"del_cancel_{std['id']}",
                    use_container_width=True,
                ):
                    st.session_state[del_key] = False
                    st.rerun()
 
# ════════════════════════════════════════════════════════════════════
# الأرشيف والتقارير
# ════════════════════════════════════════════════════════════════════
def page_reports():
    st.title("📊 الأرشيف والتقارير")

    classes = get_classes()
    if not classes:
        st.warning("لا توجد صفوف")
        return

    cls_map = {c["name"]: c["id"] for c in classes}

    with st.expander("⚙️ إعدادات التقرير", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            rep_cls = st.selectbox("الصف", list(cls_map.keys()))
        with col2:
            start_d = st.date_input("من تاريخ", value=datetime.now().replace(day=1).date())
        with col3:
            end_d   = st.date_input("إلى تاريخ", value=datetime.now().date())

        filter_std = st.text_input("فلترة بطالب محدد (اختياري)", placeholder="اتركه فارغاً لعرض الكل")

    start_str = start_d.strftime("%Y-%m-%d")
    end_str   = end_d.strftime("%Y-%m-%d")

    rows_data = get_report_data(cls_map[rep_cls], start_str, end_str, filter_std)

    if not rows_data:
        st.info("لا توجد بيانات لهذا الاختيار")
        return

    total_h = sum(r["حاضر"] for r in rows_data)
    total_g = sum(r["غائب"] for r in rows_data)
    total_m = sum(r["متأخر"] for r in rows_data)

    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("عدد الطلاب",   len(rows_data))
    col_b.metric("إجمالي الحضور", total_h)
    col_c.metric("إجمالي الغياب", total_g)
    col_d.metric("إجمالي التأخر", total_m)

    st.markdown("---")
    df_report = pd.DataFrame(rows_data)
    df_report.index = range(1, len(df_report) + 1)
    df_report.index.name = "م"

    def color_absent(val):
        if isinstance(val, int) and val >= 5:
            return "background-color: #ffcdd2"
        return ""

    st.dataframe(
        df_report.style.map(color_absent, subset=["غائب"]),
        use_container_width=True
    )

    st.markdown("---")
    st.subheader("⚠️ طلاب الغياب المتكرر")
    absent_list = get_absent_streak()
    if absent_list:
        df_absent = pd.DataFrame(absent_list)
        df_absent.columns = ["الطالب", "الصف", "أيام الغياب المتتالية"]
        st.dataframe(df_absent, use_container_width=True, hide_index=True)
    else:
        st.success("✅ لا يوجد طلاب غائبون بشكل متكرر")

    st.markdown("---")
    col_pdf, col_excel = st.columns(2)

    with col_excel:
        excel_buf = io.BytesIO()
        pd.DataFrame(rows_data).to_excel(excel_buf, index=False)
        st.download_button(
            "📊 تصدير Excel",
            data=excel_buf.getvalue(),
            file_name=f"تقرير_حضور_{rep_cls}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with col_pdf:
        try:
            pdf_bytes = build_pdf_bytes(rep_cls, rows_data, start_str, end_str)
            st.download_button(
                "📄 تصدير PDF احترافي",
                data=pdf_bytes,
                file_name=f"تقرير_حضور_{rep_cls}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary"
            )
        except Exception as e:
            st.error(f"خطأ في توليد PDF: {e}")

# ════════════════════════════════════════════════════════════════════
# إدارة المستخدمين
# ════════════════════════════════════════════════════════════════════
def page_users():
    st.title("🔑 إدارة المستخدمين")

    tab_list, tab_add, tab_pwd = st.tabs(["👥 المستخدمون الحاليون", "✚ إضافة مستخدم", "🔒 تغيير كلمة المرور"])

    with tab_list:
        users = get_all_users()
        for u in users:
            col1, col2, col3, col4 = st.columns([1.5, 1.5, 1, 0.8])
            with col1: st.markdown(f"**{u['name']}**")
            with col2: st.caption(u["username"])
            with col3: st.caption("مشرف" if u["role"] == "admin" else "معلم")
            with col4:
                if u["username"] != "admin":
                    if st.button("🗑 حذف", key=f"del_user_{u['id']}"):
                        delete_user(u["id"])
                        st.rerun()
            st.divider()

    with tab_add:
        with st.form("add_user_form"):
            new_uname = st.text_input("اسم المستخدم")
            new_pwd   = st.text_input("كلمة المرور", type="password")
            new_name  = st.text_input("الاسم الكامل")
            new_role  = st.selectbox("الصلاحية", ["teacher", "admin"])
            if st.form_submit_button("✚ إضافة المستخدم", type="primary", use_container_width=True):
                uname = new_uname.strip()
                pwd   = new_pwd.strip()
                name  = new_name.strip()
                if not uname or not pwd or not name:
                    st.error("يرجى ملء جميع الحقول")
                elif len(pwd) < 6:
                    st.error("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
                else:
                    try:
                        add_user(uname, pwd, name, new_role)
                        st.success(f"✅ تم إضافة المستخدم: {uname}")
                        st.rerun()
                    except Exception:
                        st.error("اسم المستخدم موجود مسبقاً")

    with tab_pwd:
        users = get_all_users()
        usernames = [u["username"] for u in users]
        with st.form("change_pwd_form"):
            sel_user = st.selectbox("اختر المستخدم", usernames)
            new_pass = st.text_input("كلمة المرور الجديدة", type="password")
            if st.form_submit_button("💾 حفظ كلمة المرور", type="primary", use_container_width=True):
                if not new_pass or len(new_pass) < 6:
                    st.error("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
                else:
                    change_password(sel_user, new_pass)
                    st.success("✅ تم تغيير كلمة المرور بنجاح")

# ════════════════════════════════════════════════════════════════════
# نقطة الدخول
# ════════════════════════════════════════════════════════════════════
def main():
    init_db()
    init_session()

    if not st.session_state.logged_in:
        page_login()
        return

    render_sidebar()
    page = st.session_state.get("page", "home")
    if   page == "home":       page_home()
    elif page == "attendance": page_attendance()
    elif page == "classes":    page_classes()
    elif page == "students":   page_students()
    elif page == "reports":    page_reports()
    elif page == "users":      page_users()

if __name__ == "__main__":
    main()