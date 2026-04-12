"""
نظام تسجيل الحضور المدرسي المطور - Streamlit + SQLite
============================================================
المتطلبات:
    pip install streamlit pandas openpyxl reportlab arabic-reshaper python-bidi bcrypt

تشغيل:
    streamlit run attendance_streamlit.py
"""

import streamlit as st
import sqlite3
import pandas as pd
import bcrypt
import json
import io
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
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            class_id   INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS attendance (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            class_id   INTEGER NOT NULL REFERENCES classes(id)  ON DELETE CASCADE,
            date       TEXT NOT NULL,
            status     TEXT NOT NULL CHECK(status IN ('h','g','m')),
            UNIQUE(student_id, date)
        );
        
        -- إضافة الفهارس (Indexes) لتسريع الأداء
        CREATE INDEX IF NOT EXISTS idx_attendance_date_class ON attendance(date, class_id);
        CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);
        """)

        # إنشاء المشرف الافتراضي إذا لم يوجد
        exists = conn.execute("SELECT 1 FROM users WHERE username='admin'").fetchone()
        if not exists:
            hashed = bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
                ("admin", hashed, "المشرف الإداري", "admin")
            )
            # معلم تجريبي
            t_hash = bcrypt.hashpw(b"teacher123", bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT INTO users(username,password,name,role) VALUES(?,?,?,?)",
                ("teacher", t_hash, "المعلم", "teacher")
            )

# ════════════════════════════════════════════════════════════════════
# دوال قاعدة البيانات
# ════════════════════════════════════════════════════════════════════

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

def get_students(class_id: int):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM students WHERE class_id=? ORDER BY name", (class_id,)
        ).fetchall()]

def get_all_students():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT s.id, s.name, s.class_id, c.name AS class_name
               FROM students s JOIN classes c ON s.class_id=c.id
               ORDER BY c.name, s.name"""
        ).fetchall()]

def add_student(name: str, class_id: int):
    with get_conn() as conn:
        conn.execute("INSERT INTO students(name,class_id) VALUES(?,?)", (name, class_id))

def delete_student(student_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM students WHERE id=?", (student_id,))

def move_student(student_id: int, new_class_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE students SET class_id=? WHERE id=?", (new_class_id, student_id))

def import_students_from_df(df: pd.DataFrame):
    added = 0
    with get_conn() as conn:
        for _, row in df.iterrows():
            cls_name = str(row.get("الصف", "")).strip()
            std_name = str(row.get("الطالب", "")).strip()
            if not cls_name or not std_name or cls_name == "nan" or std_name == "nan":
                continue
            cls = conn.execute("SELECT id FROM classes WHERE name=?", (cls_name,)).fetchone()
            if not cls:
                conn.execute("INSERT INTO classes(name) VALUES(?)", (cls_name,))
                cls = conn.execute("SELECT id FROM classes WHERE name=?", (cls_name,)).fetchone()
            exists = conn.execute(
                "SELECT 1 FROM students WHERE name=? AND class_id=?",
                (std_name, cls["id"])
            ).fetchone()
            if not exists:
                conn.execute("INSERT INTO students(name,class_id) VALUES(?,?)", (std_name, cls["id"]))
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

# ════════════════════════════════════════════════════════════════════
# صفحة تسجيل الدخول
# ════════════════════════════════════════════════════════════════════
def page_login():
    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        st.markdown("""
        <div style='text-align:center; padding: 40px 0 20px'>
            <div style='font-size:5rem'>🎓</div>
            <h1 style='color:#1a237e; margin:0'>نظام الحضور المدرسي</h1>
            <p style='color:#7986cb'>إدارة الحضور والغياب بشكل احترافي</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("اسم المستخدم", placeholder="أدخل اسم المستخدم")
            password = st.text_input("كلمة المرور", type="password", placeholder="أدخل كلمة المرور")
            submitted = st.form_submit_button("دخول ←", use_container_width=True, type="primary")

        if submitted:
            user = verify_user(username, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user      = user
                st.session_state.role      = user["role"]
                st.session_state.page      = "home"
                st.rerun()
            else:
                st.error("❌ اسم المستخدم أو كلمة المرور غير صحيحة")

        st.caption("المشرف: admin / admin123   •   المعلم: teacher / teacher123")

# ════════════════════════════════════════════════════════════════════
# الشريط الجانبي
# ════════════════════════════════════════════════════════════════════
def render_sidebar():
    with st.sidebar:
        st.markdown(f"""
        <div class='sidebar-title'>🎓 نظام الحضور</div>
        <div style='text-align:center; margin:12px 0 20px;
                    background:#3949ab; border-radius:10px; padding:10px'>
            <b>👤 {st.session_state.user['name']}</b><br>
            <small>{'مشرف إداري' if st.session_state.role=='admin' else 'معلم'}</small>
        </div>
        """, unsafe_allow_html=True)

        if st.button("🏠  الرئيسية",       use_container_width=True): st.session_state.page = "home";       st.rerun()
        if st.button("📝  تسجيل الحضور",   use_container_width=True): st.session_state.page = "attendance"; st.rerun()

        if st.session_state.role == "admin":
            st.divider()
            st.markdown("<small style='color:#9fa8da'>─── إدارة ───</small>", unsafe_allow_html=True)
            if st.button("🏫  إدارة الصفوف",      use_container_width=True): st.session_state.page = "classes";  st.rerun()
            if st.button("👨‍🎓  إدارة الطلاب",     use_container_width=True): st.session_state.page = "students"; st.rerun()
            if st.button("📊  الأرشيف والتقارير", use_container_width=True): st.session_state.page = "reports";  st.rerun()
            if st.button("🔑  إدارة المستخدمين",  use_container_width=True): st.session_state.page = "users";    st.rerun()

        st.divider()
        if st.button("🚪  خروج", use_container_width=True, type="primary"):
            for k in ["logged_in", "user", "role", "page"]:
                st.session_state.pop(k, None)
            st.rerun()

# ════════════════════════════════════════════════════════════════════
# الصفحة الرئيسية — لوحة الإحصائيات
# ════════════════════════════════════════════════════════════════════
def page_home():
    st.title("🏠 لوحة الإحصائيات")
    st.caption(datetime.now().strftime("%A  %Y-%m-%d"))

    h, g, m = get_today_stats()
    classes  = get_classes()
    total_students = sum(len(get_students(c["id"])) for c in classes)

    c1, c2, c3, c4, c5 = st.columns(5)
    cols_data = [
        (c1, len(classes), "إجمالي الصفوف",  "#3949ab", "🏫"),
        (c2, total_students, "إجمالي الطلاب","#00897b", "👨‍🎓"),
        (c3, h,  "حضور اليوم",   "#2e7d32", "✅"),
        (c4, g,  "غياب اليوم",   "#c62828", "❌"),
        (c5, m,  "متأخرون اليوم","#e65100", "⏰"),
    ]
    for col, val, label, color, icon in cols_data:
        with col:
            st.markdown(f"""
            <div class='metric-card' style='border-color:{color}'>
                <div style='font-size:2rem'>{icon}</div>
                <div class='metric-val' style='color:{color}'>{val}</div>
                <div class='metric-lbl'>{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")

    col_chart, col_alerts = st.columns([1.6, 1])

    with col_chart:
        st.subheader("📈 نسب الحضور اليوم لكل صف")
        today = datetime.now().strftime("%Y-%m-%d")
        if not classes:
            st.info("لا توجد صفوف مضافة بعد")
        else:
            chart_data = []
            for cls in classes:
                students = get_students(cls["id"])
                if not students:
                    continue
                pct = get_class_today_pct(cls["id"], today, len(students))
                chart_data.append({"الصف": cls["name"], "نسبة الحضور %": pct})
            if chart_data:
                df_chart = pd.DataFrame(chart_data).set_index("الصف")
                st.bar_chart(df_chart)

    with col_alerts:
        st.subheader("⚠️ تنبيهات الغياب المتكرر")
        absent_list = get_absent_streak()
        if not absent_list:
            st.success("✅ لا يوجد طلاب غائبون بشكل متكرر")
        else:
            for item in absent_list:
                st.markdown(f"""
                <div class='alert-row'>
                    <b>{item['name']}</b><br>
                    <small>{item['class']} — غائب {item['streak']} أيام متتالية</small>
                </div>
                """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📋 تفاصيل الصفوف")
    if classes:
        df_cls = pd.DataFrame([
            {"اسم الصف": c["name"], "عدد الطلاب": len(get_students(c["id"]))}
            for c in classes
        ])
        st.dataframe(df_cls, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد صفوف مضافة بعد")

# ════════════════════════════════════════════════════════════════════
# تسجيل الحضور (تم التحديث لدعم الموبايل والتحضير المجمع)
# ════════════════════════════════════════════════════════════════════
def page_attendance():
    st.title("📝 تسجيل الحضور اليومي")

    classes = get_classes()
    if not classes:
        st.warning("لا توجد صفوف. يرجى إضافة صفوف أولاً من إدارة الصفوف.")
        return

    # استخدام Expander لتوفير المساحة في الهواتف
    with st.expander("⚙️ تحديد الصف والتاريخ", expanded=True):
        col_cls, col_date = st.columns([1, 1])
        with col_cls:
            cls_names = [c["name"] for c in classes]
            selected_cls_name = st.selectbox("الصف", cls_names)
        with col_date:
            selected_date = st.date_input("التاريخ", value=datetime.now().date())

    selected_cls = next((c for c in classes if c["name"] == selected_cls_name), None)
    if not selected_cls:
        return

    date_str  = selected_date.strftime("%Y-%m-%d")
    students  = get_students(selected_cls["id"])
    att_data  = get_attendance(selected_cls["id"], date_str)

    if not students:
        st.info("هذا الصف لا يحتوي على طلاب بعد.")
        return

    h_c = sum(1 for s in students if att_data.get(s["id"]) == "h")
    g_c = sum(1 for s in students if att_data.get(s["id"]) == "g")
    m_c = sum(1 for s in students if att_data.get(s["id"]) == "m")

    st.info(f"حاضر: **{h_c}** |  غائب: **{g_c}** |  متأخر: **{m_c}** |  المجموع: **{len(students)}**")

    # أزرار جماعية
    col_all1, col_all2, col_all3, _ = st.columns([1, 1, 1, 3])
    with col_all1:
        if st.button("✅ تحضير الجميع", use_container_width=True):
            for s in students:
                set_attendance(s["id"], selected_cls["id"], date_str, "h")
            st.rerun()
    with col_all2:
        if st.button("❌ تغييب الجميع", use_container_width=True):
            for s in students:
                set_attendance(s["id"], selected_cls["id"], date_str, "g")
            st.rerun()
    with col_all3:
        if st.button("🔄 إعادة الضبط", use_container_width=True):
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM attendance WHERE class_id=? AND date=?",
                    (selected_cls["id"], date_str)
                )
            st.rerun()

    st.markdown("---")

    # تجهيز الجدول التفاعلي بدلاً من الأزرار الفردية
    status_options = ["—", "✅ حاضر", "❌ غائب", "⏰ متأخر"]
    status_map = {"none": "—", "h": "✅ حاضر", "g": "❌ غائب", "m": "⏰ متأخر"}
    reverse_map = {"—": "none", "✅ حاضر": "h", "❌ غائب": "g", "⏰ متأخر": "m"}

    df_data = []
    for student in students:
        current = att_data.get(student["id"], "none")
        df_data.append({
            "student_id": student["id"],
            "اسم الطالب": student["name"],
            "الحالة": status_map[current]
        })

    df = pd.DataFrame(df_data)

    edited_df = st.data_editor(
        df,
        column_config={
            "student_id": None, # إخفاء رقم المعرف
            "اسم الطالب": st.column_config.TextColumn("اسم الطالب", disabled=True),
            "الحالة": st.column_config.SelectboxColumn("الحالة", options=status_options, required=True)
        },
        hide_index=True,
        use_container_width=True,
        key=f"editor_{selected_cls['id']}_{date_str}"
    )

    if st.button("💾 حفظ التحضير", type="primary", use_container_width=True):
        for _, row in edited_df.iterrows():
            new_status = reverse_map[row["الحالة"]]
            if new_status != "none":
                set_attendance(row["student_id"], selected_cls["id"], date_str, new_status)
        st.success("✅ تم حفظ الحضور بنجاح!")
        st.rerun()

# ════════════════════════════════════════════════════════════════════
# إدارة الصفوف
# ════════════════════════════════════════════════════════════════════
def page_classes():
    st.title("🏫 إدارة الصفوف الدراسية")

    col_add, col_list = st.columns([1, 1.5])

    with col_add:
        st.subheader("إضافة صف جديد")
        with st.form("add_class_form"):
            new_cls = st.text_input("اسم الصف الدراسي", placeholder="مثال: الصف الأول أ")
            if st.form_submit_button("✚ حفظ الصف", type="primary", use_container_width=True):
                name = new_cls.strip()
                if not name:
                    st.error("يرجى كتابة اسم الصف")
                else:
                    try:
                        add_class(name)
                        st.success(f"✅ تم إضافة الصف: {name}")
                        st.rerun()
                    except Exception:
                        st.error("الصف موجود مسبقاً")

    with col_list:
        st.subheader("الصفوف الحالية")
        classes = get_classes()
        if not classes:
            st.info("لا توجد صفوف بعد")
        else:
            for cls in classes:
                count = len(get_students(cls["id"]))
                c1, c2, c3 = st.columns([2.5, 1, 1])
                with c1:
                    st.markdown(f"**{cls['name']}**")
                with c2:
                    st.caption(f"{count} طالب")
                with c3:
                    if st.button("🗑 حذف", key=f"del_cls_{cls['id']}"):
                        delete_class(cls["id"])
                        st.rerun()
                st.divider()

# ════════════════════════════════════════════════════════════════════
# إدارة الطلاب
# ════════════════════════════════════════════════════════════════════
def page_students():
    st.title("👨‍🎓 إدارة شؤون الطلاب")

    classes = get_classes()
    if not classes:
        st.warning("أضف صفوفاً أولاً")
        return

    cls_map = {c["name"]: c["id"] for c in classes}

    tab_list, tab_add, tab_import, tab_move = st.tabs(
        ["📋 قائمة الطلاب", "✚ إضافة طالب", "📥 استيراد Excel", "↔ نقل طالب"]
    )

    with tab_list:
        col_filter, col_search = st.columns([1, 1])
        with col_filter:
            filter_cls = st.selectbox("عرض صف", ["الكل"] + list(cls_map.keys()), key="filter_cls")
        with col_search:
            search = st.text_input("🔍 بحث باسم الطالب", key="search_std")

        all_students = get_all_students()
        if filter_cls != "الكل":
            all_students = [s for s in all_students if s["class_name"] == filter_cls]
        if search:
            all_students = [s for s in all_students if search in s["name"]]

        st.caption(f"عدد الطلاب: {len(all_students)}")

        if not all_students:
            st.info("لا يوجد طلاب مطابقون")
        else:
            for i, std in enumerate(all_students, 1):
                c1, c2, c3, c4 = st.columns([0.5, 2.5, 1.2, 0.8])
                with c1: st.text(str(i))
                with c2: st.markdown(f"**{std['name']}**")
                with c3: st.caption(std["class_name"])
                with c4:
                    if st.button("🗑", key=f"del_std_{std['id']}"):
                        delete_student(std["id"])
                        st.rerun()

    with tab_add:
        with st.form("add_student_form"):
            sel_cls = st.selectbox("الصف", list(cls_map.keys()))
            std_name = st.text_input("اسم الطالب الكامل")
            if st.form_submit_button("✚ إضافة للصف", type="primary", use_container_width=True):
                name = std_name.strip()
                if not name or sel_cls not in cls_map:
                    st.error("تأكد من اختيار الصف وكتابة الاسم")
                else:
                    exists = any(s["name"] == name for s in get_students(cls_map[sel_cls]))
                    if exists:
                        st.error(f"الطالب '{name}' موجود مسبقاً في هذا الصف")
                    else:
                        add_student(name, cls_map[sel_cls])
                        st.success(f"✅ تم إضافة: {name}")
                        st.rerun()

    with tab_import:
        st.markdown("ارفع ملف Excel أو CSV يحتوي على عمودين: **الصف** و **الطالب**")
        uploaded = st.file_uploader("اختر ملف Excel / CSV", type=["xlsx", "xls", "csv"])
        if uploaded:
            try:
                df = pd.read_csv(uploaded) if uploaded.name.endswith(".csv") else pd.read_excel(uploaded)
                st.dataframe(df.head(10), use_container_width=True)
                if st.button("📥 استيراد البيانات", type="primary"):
                    added = import_students_from_df(df)
                    st.success(f"✅ تم استيراد {added} طالب")
                    st.rerun()
            except Exception as e:
                st.error(f"خطأ في قراءة الملف: {e}")

    with tab_move:
        all_for_move = get_all_students()
        if not all_for_move:
            st.info("لا يوجد طلاب")
        else:
            std_options = {f"{s['name']} ({s['class_name']})": s for s in all_for_move}
            selected_label = st.selectbox("اختر الطالب", list(std_options.keys()))
            selected_std   = std_options[selected_label]
            other_classes  = [c for c in list(cls_map.keys()) if c != selected_std["class_name"]]
            if not other_classes:
                st.warning("لا يوجد صفوف أخرى للنقل")
            else:
                new_cls_name = st.selectbox("الصف الجديد", other_classes)
                if st.button("↔ تأكيد النقل", type="primary"):
                    move_student(selected_std["id"], cls_map[new_cls_name])
                    st.success(f"✅ تم نقل {selected_std['name']} إلى {new_cls_name}")
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