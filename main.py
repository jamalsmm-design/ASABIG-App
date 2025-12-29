import streamlit as st
import pandas as pd
from pathlib import Path
import sqlite3
import hashlib
import datetime
import json
import re
import os

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="ASABIG Talent Platform – Pilot Demo", layout="wide")

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "asabig.db"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

DATA_FILES = {
    "generic_talent_data": "generic_talent_data.csv",
    "field_tests": "field_tests.csv",
    "medical_data": "medical_data.csv",
    "sport_specific_kpis": "sport_specific_kpis.csv",
    "athletes": "athletes.csv",
    "athlete_tests": "athlete_tests.csv",
}

ROLES = ["Player", "Parent", "Scout", "Academy", "Admin"]

# =========================
# HELPERS
# =========================
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("_")
    return name[:120] if name else "file"

def safe_df(df: pd.DataFrame) -> pd.DataFrame:
    """Make dataframe safe for st.dataframe (avoid Arrow conversion errors)"""
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        df = pd.DataFrame(df)
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == "object":
            out[c] = out[c].apply(lambda x: "" if pd.isna(x) else (x if isinstance(x, (str,int,float,bool)) else json.dumps(x, ensure_ascii=False)))
    return out

@st.cache_data
def load_csv(key: str) -> pd.DataFrame:
    fn = DATA_FILES.get(key)
    if not fn:
        return pd.DataFrame()
    p = BASE_DIR / fn
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS athlete_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_user_id INTEGER NOT NULL,
        full_name TEXT NOT NULL,
        gender TEXT NOT NULL, -- M / F
        birth_year INTEGER,
        sport TEXT,
        city TEXT,
        club TEXT,
        dominant_side TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(owner_user_id) REFERENCES users(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS athlete_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        athlete_id INTEGER NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL,
        unit TEXT,
        measured_at TEXT NOT NULL,
        note TEXT,
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        athlete_id INTEGER NOT NULL,
        uploader_user_id INTEGER NOT NULL,
        file_type TEXT NOT NULL, -- medical_pdf, photo, video, other
        file_path TEXT NOT NULL,
        original_name TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(id),
        FOREIGN KEY(uploader_user_id) REFERENCES users(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS parent_links (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_user_id INTEGER NOT NULL,
        athlete_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(parent_user_id, athlete_id),
        FOREIGN KEY(parent_user_id) REFERENCES users(id),
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS scout_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id INTEGER NOT NULL,
        athlete_id INTEGER NOT NULL,
        note TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(scout_user_id) REFERENCES users(id),
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(id)
    )
    """)

    con.commit()
    con.close()

def get_user_by_email(email: str):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT id, full_name, email, password_hash, role FROM users WHERE email = ?", (email.lower().strip(),))
    row = cur.fetchone()
    con.close()
    return row

def create_user(full_name: str, email: str, password: str, role: str):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO users(full_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)",
        (full_name.strip(), email.lower().strip(), sha256(password), role, now_iso())
    )
    con.commit()
    con.close()

def login(email: str, password: str) -> bool:
    row = get_user_by_email(email)
    if not row:
        return False
    user_id, full_name, email, pw_hash, role = row
    if sha256(password) != pw_hash:
        return False
    st.session_state["auth"] = {
        "user_id": user_id,
        "full_name": full_name,
        "email": email,
        "role": role
    }
    return True

def logout():
    st.session_state["auth"] = None

def auth():
    return st.session_state.get("auth")

def require_login():
    if not auth():
        st.warning("Please login first.")
        st.stop()

def my_athletes_for_user(user_id: int, role: str) -> pd.DataFrame:
    con = db()
    cur = con.cursor()

    if role == "Player":
        cur.execute("""
            SELECT * FROM athlete_profiles
            WHERE owner_user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
    elif role == "Parent":
        cur.execute("""
            SELECT ap.* FROM athlete_profiles ap
            JOIN parent_links pl ON pl.athlete_id = ap.id
            WHERE pl.parent_user_id = ?
            ORDER BY ap.created_at DESC
        """, (user_id,))
    elif role == "Academy":
        # Academy owner sees athletes they created (same as Player owner in this MVP)
        cur.execute("""
            SELECT * FROM athlete_profiles
            WHERE owner_user_id = ?
            ORDER BY created_at DESC
        """, (user_id,))
    elif role == "Scout":
        # Scout can browse all (read-only) in this MVP
        cur.execute("SELECT * FROM athlete_profiles ORDER BY created_at DESC")
    else:  # Admin
        cur.execute("SELECT * FROM athlete_profiles ORDER BY created_at DESC")

    rows = cur.fetchall()
    cols = [d[0] for d in cur.description] if cur.description else []
    con.close()
    return pd.DataFrame(rows, columns=cols)

def insert_athlete(owner_user_id: int, full_name: str, gender: str, birth_year, sport, city, club, dominant_side):
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO athlete_profiles(owner_user_id, full_name, gender, birth_year, sport, city, club, dominant_side, created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        owner_user_id, full_name.strip(), gender, birth_year, sport, city, club, dominant_side, now_iso()
    ))
    con.commit()
    con.close()

def add_metric(athlete_id: int, metric_name: str, metric_value, unit: str, measured_at: str, note: str):
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO athlete_metrics(athlete_id, metric_name, metric_value, unit, measured_at, note)
        VALUES(?,?,?,?,?,?)
    """, (athlete_id, metric_name.strip(), metric_value, unit.strip(), measured_at, note.strip()))
    con.commit()
    con.close()

def get_metrics(athlete_id: int) -> pd.DataFrame:
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT metric_name, metric_value, unit, measured_at, note
        FROM athlete_metrics
        WHERE athlete_id = ?
        ORDER BY measured_at DESC
    """, (athlete_id,))
    rows = cur.fetchall()
    con.close()
    return pd.DataFrame(rows, columns=["metric_name","metric_value","unit","measured_at","note"])

def save_upload(athlete_id: int, uploader_user_id: int, file_type: str, file_bytes: bytes, original_name: str):
    athlete_dir = UPLOADS_DIR / f"athlete_{athlete_id}"
    athlete_dir.mkdir(exist_ok=True)

    safe_name = sanitize_filename(original_name)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = athlete_dir / f"{stamp}_{safe_name}"

    with open(out_path, "wb") as f:
        f.write(file_bytes)

    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO uploads(athlete_id, uploader_user_id, file_type, file_path, original_name, uploaded_at)
        VALUES(?,?,?,?,?,?)
    """, (athlete_id, uploader_user_id, file_type, str(out_path), original_name, now_iso()))
    con.commit()
    con.close()

def get_uploads(athlete_id: int) -> pd.DataFrame:
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT file_type, original_name, file_path, uploaded_at
        FROM uploads
        WHERE athlete_id = ?
        ORDER BY uploaded_at DESC
    """, (athlete_id,))
    rows = cur.fetchall()
    con.close()
    return pd.DataFrame(rows, columns=["file_type","original_name","file_path","uploaded_at"])

def link_parent_to_athlete(parent_user_id: int, athlete_id: int):
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO parent_links(parent_user_id, athlete_id, created_at)
        VALUES(?,?,?)
    """, (parent_user_id, athlete_id, now_iso()))
    con.commit()
    con.close()

def add_scout_note(scout_user_id: int, athlete_id: int, note: str):
    con = db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO scout_notes(scout_user_id, athlete_id, note, created_at)
        VALUES(?,?,?,?)
    """, (scout_user_id, athlete_id, note.strip(), now_iso()))
    con.commit()
    con.close()

def get_scout_notes(athlete_id: int) -> pd.DataFrame:
    con = db()
    cur = con.cursor()
    cur.execute("""
        SELECT sn.note, sn.created_at, u.full_name AS scout_name
        FROM scout_notes sn
        JOIN users u ON u.id = sn.scout_user_id
        WHERE sn.athlete_id = ?
        ORDER BY sn.created_at DESC
    """, (athlete_id,))
    rows = cur.fetchall()
    con.close()
    return pd.DataFrame(rows, columns=["note","created_at","scout_name"])

# Gender filter logic you requested:
def gender_passes(row_gender: str, selected: str) -> bool:
    # row_gender expected: "M", "F", or "M/F"
    if selected == "All":
        return True
    if selected == "M":
        return row_gender in ["M", "M/F"]
    if selected == "F":
        return row_gender in ["F", "M/F"]
    return True

# =========================
# INIT
# =========================
init_db()
if "auth" not in st.session_state:
    st.session_state["auth"] = None

# =========================
# SIDEBAR
# =========================
st.sidebar.title("ASABIG – Navigation")
u = auth()

if u:
    st.sidebar.success(f"Logged in: {u['full_name']} ({u['role']})")
    if st.sidebar.button("Logout"):
        logout()
        st.rerun()
else:
    st.sidebar.info("Not logged in")

PAGES = [
    "Home",
    "Login / Register",
    "Dashboard",
    "Player Data Entry",
    "Uploads (Medical / Photos / Videos)",
    "Benchmarks & Data",
    "Model",
    "Athletes (Demo List)",
    "Athlete Profile",
    "Athlete Comparison",
    "About / Governance",
]

page = st.sidebar.radio("Choose page:", PAGES)

st.sidebar.markdown("---")
st.sidebar.subheader("Data files status:")
for k, v in DATA_FILES.items():
    p = BASE_DIR / v
    st.sidebar.write(f"✅ {v}" if p.exists() else f"❌ {v} (missing)")

# =========================
# PAGE: HOME
# =========================
if page == "Home":
    st.title("ASABIG – Talent Identification Platform (Pilot Demo)")
    st.write("ASABIG is a data-driven talent identification platform for youth (7–23 years), serving federations, clubs, schools, and academies.")
    st.markdown("""
**What this demo includes**
- Registration / Login with roles (Player / Parent / Scout / Academy)
- Role dashboards
- Player data entry (metrics)
- Uploads (medical PDF, photos, videos)
- CSV demo pages (Benchmarks, demo athletes, comparison)

> This is an MVP prototype. For production, we’d normally move auth/storage to a backend (Firebase/Postgres) + proper API.
""")

# =========================
# PAGE: LOGIN / REGISTER
# =========================
elif page == "Login / Register":
    st.title("Login / Register")

    tabs = st.tabs(["Login", "Register"])

    with tabs[0]:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login"):
            ok = login(email, password)
            if ok:
                st.success("Logged in successfully.")
                st.rerun()
            else:
                st.error("Invalid email or password.")

    with tabs[1]:
        full_name = st.text_input("Full name", key="reg_name")
        email2 = st.text_input("Email", key="reg_email")
        pw1 = st.text_input("Password", type="password", key="reg_pw1")
        pw2 = st.text_input("Confirm password", type="password", key="reg_pw2")
        role = st.selectbox("Role", ROLES, index=0)
        if st.button("Create account"):
            if not full_name.strip():
                st.error("Full name required.")
            elif not email2.strip():
                st.error("Email required.")
            elif pw1 != pw2:
                st.error("Passwords do not match.")
            elif len(pw1) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                try:
                    create_user(full_name, email2, pw1, role)
                    st.success("Account created. Please login.")
                except Exception as e:
                    st.error(f"Could not create account (maybe email already used). Details: {e}")

# =========================
# PAGE: DASHBOARD
# =========================
elif page == "Dashboard":
    require_login()
    role = u["role"]
    st.title(f"Dashboard – {role}")

    athletes_df = my_athletes_for_user(u["user_id"], role)
    st.subheader("My athletes")
    st.dataframe(safe_df(athletes_df), use_container_width=True)

    if role in ["Player", "Academy"]:
        st.markdown("---")
        st.subheader("Create athlete profile")
        c1, c2, c3 = st.columns(3)
        with c1:
            full_name = st.text_input("Athlete full name")
            gender = st.selectbox("Gender", ["M","F"])
        with c2:
            birth_year = st.number_input("Birth year", min_value=1980, max_value=2030, value=2008)
            sport = st.text_input("Sport")
        with c3:
            city = st.text_input("City")
            club = st.text_input("Club / Academy")
            dominant_side = st.selectbox("Dominant side", ["Right","Left","Both"], index=0)

        if st.button("Create athlete"):
            insert_athlete(u["user_id"], full_name, gender, int(birth_year), sport, city, club, dominant_side)
            st.success("Athlete created.")
            st.rerun()

    if role == "Parent":
        st.markdown("---")
        st.subheader("Link an athlete to your account")
        st.caption("In this MVP, parent links by selecting athlete ID from the list.")
        all_athletes = my_athletes_for_user(u["user_id"], "Admin")
        if not all_athletes.empty:
            athlete_id = st.selectbox("Select athlete ID to link", all_athletes["id"].tolist())
            if st.button("Link athlete"):
                link_parent_to_athlete(u["user_id"], int(athlete_id))
                st.success("Linked.")
                st.rerun()
        else:
            st.info("No athletes exist yet.")

# =========================
# PAGE: PLAYER DATA ENTRY
# =========================
elif page == "Player Data Entry":
    require_login()
    st.title("Player Data Entry (Metrics)")

    athletes_df = my_athletes_for_user(u["user_id"], u["role"])
    if athletes_df.empty:
        st.info("No athlete profiles available. Create one from Dashboard.")
        st.stop()

    athlete_id = st.selectbox("Choose athlete", athletes_df["id"].tolist())
    athlete_row = athletes_df[athletes_df["id"] == athlete_id].iloc[0]
    st.write(f"**Athlete:** {athlete_row['full_name']} | **Gender:** {athlete_row['gender']} | **Sport:** {athlete_row.get('sport','')}")

    st.markdown("---")
    st.subheader("Add metric")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        metric_name = st.text_input("Metric name (e.g., VO2max, 30m Sprint)")
    with m2:
        metric_value = st.number_input("Value", value=0.0)
    with m3:
        unit = st.text_input("Unit (e.g., ml/kg/min, sec, cm)")
    with m4:
        measured_at = st.date_input("Measured date", value=datetime.date.today()).isoformat()

    note = st.text_input("Note (optional)")
    if st.button("Save metric"):
        if not metric_name.strip():
            st.error("Metric name required.")
        else:
            add_metric(int(athlete_id), metric_name, float(metric_value), unit, measured_at, note)
            st.success("Saved.")

    st.markdown("---")
    st.subheader("Metrics history")
    st.dataframe(safe_df(get_metrics(int(athlete_id))), use_container_width=True)

# =========================
# PAGE: UPLOADS
# =========================
elif page == "Uploads (Medical / Photos / Videos)":
    require_login()
    st.title("Uploads – Medical / Photos / Videos")

    athletes_df = my_athletes_for_user(u["user_id"], u["role"])
    if athletes_df.empty:
        st.info("No athlete profiles available.")
        st.stop()

    athlete_id = st.selectbox("Choose athlete", athletes_df["id"].tolist())
    athlete_row = athletes_df[athletes_df["id"] == athlete_id].iloc[0]
    st.write(f"**Athlete:** {athlete_row['full_name']}")

    st.markdown("---")
    st.subheader("Upload files")

    colA, colB = st.columns(2)
    with colA:
        medical_pdf = st.file_uploader("Medical test (PDF)", type=["pdf"], key="medical_pdf")
        if medical_pdf and st.button("Upload medical PDF"):
            save_upload(int(athlete_id), u["user_id"], "medical_pdf", medical_pdf.getvalue(), medical_pdf.name)
            st.success("Uploaded medical PDF.")

    with colB:
        photo = st.file_uploader("Photo (jpg/png)", type=["jpg","jpeg","png"], key="photo")
        video = st.file_uploader("Video (mp4/mov)", type=["mp4","mov"], key="video")

        if photo and st.button("Upload photo"):
            save_upload(int(athlete_id), u["user_id"], "photo", photo.getvalue(), photo.name)
            st.success("Uploaded photo.")

        if video and st.button("Upload video"):
            save_upload(int(athlete_id), u["user_id"], "video", video.getvalue(), video.name)
            st.success("Uploaded video.")

    st.markdown("---")
    st.subheader("Uploaded files")
    up = get_uploads(int(athlete_id))
    if up.empty:
        st.info("No uploads yet.")
    else:
        st.dataframe(safe_df(up), use_container_width=True)
        st.caption("Files are saved in the /uploads folder inside the app directory.")

# =========================
# PAGE: BENCHMARKS & DATA (CSV)
# =========================
elif page == "Benchmarks & Data":
    st.title("Benchmarks & Data – ASABIG Pilot Demo")

    dataset_key = st.selectbox("Choose dataset", list(DATA_FILES.keys()), index=0)
    df = load_csv(dataset_key)
    if df.empty:
        st.warning("Dataset file missing or empty.")
        st.stop()

    st.write(f"Rows: **{len(df)}** | Columns: **{len(df.columns)}**")
    st.caption(f"File: {DATA_FILES[dataset_key]}")

    # Age group filter (if exists)
    age_filter = "All"
    if "Age Group(s)" in df.columns:
        age_filter = st.selectbox("Age group filter", ["All"] + sorted(df["Age Group(s)"].dropna().astype(str).unique().tolist()))
        if age_filter != "All":
            df = df[df["Age Group(s)"].astype(str) == age_filter]

    # Gender filter with your exact logic (M => M+M/F, F => F+M/F)
    gender_col = None
    for gc in ["Gender", "gender"]:
        if gc in df.columns:
            gender_col = gc
            break

    if gender_col:
        gender_sel = st.selectbox("Gender filter", ["All", "M", "F"], index=0)
        df = df[df[gender_col].astype(str).apply(lambda g: gender_passes(g, gender_sel))]

    st.dataframe(safe_df(df), use_container_width=True)

# =========================
# PAGE: MODEL (placeholder)
# =========================
elif page == "Model":
    st.title("Model (Pilot Placeholder)")
    st.write("Here you can connect your AI scoring / talent model later.")
    st.markdown("""
**Next steps ideas**
- Talent Score per sport
- Compare athlete vs benchmarks
- Flag outliers / high potential
- Scout recommendation engine
""")

# =========================
# PAGE: ATHLETES (DEMO LIST from CSV)
# =========================
elif page == "Athletes (Demo List)":
    st.title("Athletes (Demo List) – from athletes.csv")
    athletes_df = load_csv("athletes")
    if athletes_df.empty:
        st.warning("athletes.csv missing.")
        st.stop()

    # optional gender filter if column exists
    gender_col = "gender" if "gender" in athletes_df.columns else ("Gender" if "Gender" in athletes_df.columns else None)
    if gender_col:
        gender_sel = st.selectbox("Gender filter", ["All", "M", "F"], index=0)
        athletes_df = athletes_df[athletes_df[gender_col].astype(str).apply(lambda g: gender_passes(g, gender_sel))]

    st.dataframe(safe_df(athletes_df), use_container_width=True)

# =========================
# PAGE: ATHLETE PROFILE (DEMO)
# =========================
elif page == "Athlete Profile":
    st.title("Athlete Profile (Demo) – from athletes.csv")
    athletes_df = load_csv("athletes")
    if athletes_df.empty:
        st.warning("athletes.csv missing.")
        st.stop()

    display_col = "full_name" if "full_name" in athletes_df.columns else athletes_df.columns[0]
    athlete_name = st.selectbox("Select athlete (demo)", athletes_df[display_col].astype(str).tolist())
    row = athletes_df[athletes_df[display_col].astype(str) == str(athlete_name)].iloc[0]
    st.json(row.to_dict())

# =========================
# PAGE: ATHLETE COMPARISON (UP TO 6)
# =========================
elif page == "Athlete Comparison":
    st.title("Athlete Comparison – Side by Side (Demo)")

    athletes_df = load_csv("athletes")
    tests_df = load_csv("athlete_tests")
    if athletes_df.empty:
        st.error("athletes.csv not found.")
        st.stop()

    display_col = "full_name" if "full_name" in athletes_df.columns else athletes_df.columns[0]

    MAX_COMPARE = 6
    selected_names = st.multiselect(
        f"Select up to {MAX_COMPARE} athletes to compare:",
        athletes_df[display_col].astype(str).tolist(),
        default=athletes_df[display_col].astype(str).tolist()[:min(4, len(athletes_df))]
    )

    if len(selected_names) > MAX_COMPARE:
        st.warning(f"Showing first {MAX_COMPARE} athletes only.")
        selected_names = selected_names[:MAX_COMPARE]

    if not selected_names:
        st.info("Select athletes to compare.")
        st.stop()

    comp_df = athletes_df[athletes_df[display_col].astype(str).isin([str(x) for x in selected_names])].copy()
    st.dataframe(safe_df(comp_df), use_container_width=True)

    st.markdown("---")
    st.subheader("Simple test comparison (demo)")

    if tests_df.empty:
        st.info("athlete_tests.csv missing — chart will not show.")
        st.stop()

    metric_col = "metric" if "metric" in tests_df.columns else None
    value_col = "value" if "value" in tests_df.columns else None
    name_col = "full_name" if "full_name" in tests_df.columns else display_col

    if not (metric_col and value_col and name_col):
        st.info("athlete_tests.csv should include columns: full_name, metric, value (demo).")
        st.stop()

    metric = st.selectbox("Metric from athlete_tests.csv", sorted(tests_df[metric_col].astype(str).unique().tolist()))
    plot_df = tests_df[
        (tests_df[metric_col].astype(str) == str(metric)) &
        (tests_df[name_col].astype(str).isin([str(x) for x in selected_names]))
    ].copy()

    if plot_df.empty:
        st.info("No test values found for selected athletes and metric.")
    else:
        # bar chart
        chart = plot_df.groupby(name_col)[value_col].mean()
        st.bar_chart(chart)

# =========================
# PAGE: ABOUT / GOVERNANCE
# =========================
elif page == "About / Governance":
    st.title("About / Governance")
    st.write("This is a pilot demo. Governance, privacy, and PDPL compliance will be handled in later stages.")
    st.markdown("""
**MVP Governance notes**
- Data ownership: athlete/guardian
- Role-based access: player/parent/scout/academy
- Audit trail for uploads + edits
- Consent for medical documents
""")
