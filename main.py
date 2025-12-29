import streamlit as st
import pandas as pd
from pathlib import Path
import sqlite3
import hashlib
import datetime as dt
import re
import os
from typing import Optional, Tuple

# ============================================================
# CONFIG
# ============================================================
st.set_page_config(page_title="ASABIG Talent Platform - Pilot Demo", layout="wide")

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

AGE_GROUPS = ["U10", "U14", "U17", "U23"]
GENDERS = ["M", "F"]

APP_TITLE = "ASABIG – Talent Identification Platform (Pilot Demo)"


# ============================================================
# HELPERS (DATA SAFETY + DB)
# ============================================================
def safe_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make dataframe safe for Streamlit display (avoid pyarrow mixed-type issues).
    """
    if df is None:
        return pd.DataFrame()
    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame(df)
    if df.empty:
        return df
    out = df.copy()
    for c in out.columns:
        try:
            if out[c].dtype == "object":
                out[c] = out[c].apply(lambda x: "" if pd.isna(x) else str(x))
        except Exception:
            out[c] = out[c].astype(str)
    return out


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def now_ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def valid_email(email: str) -> bool:
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email.strip(), re.I))


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        linked_athlete_id TEXT,
        academy_name TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS athlete_profiles (
        athlete_id TEXT PRIMARY KEY,
        created_by_user_id INTEGER,
        full_name TEXT NOT NULL,
        gender TEXT,
        birth_year INTEGER,
        age_group TEXT,
        sport TEXT,
        dominant_side TEXT,
        club TEXT,
        city TEXT,
        photo_path TEXT,
        preferences_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS athlete_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        athlete_id TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value REAL,
        unit TEXT,
        measured_at TEXT NOT NULL,
        source_role TEXT,
        created_by_user_id INTEGER,
        notes TEXT,
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(athlete_id) ON DELETE CASCADE,
        FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS uploads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        athlete_id TEXT NOT NULL,
        uploaded_by_user_id INTEGER,
        upload_type TEXT NOT NULL,      -- medical_pdf / photo / video / other
        title TEXT,
        file_path TEXT NOT NULL,
        link_url TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(athlete_id) ON DELETE CASCADE,
        FOREIGN KEY(uploaded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS scout_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scout_user_id INTEGER NOT NULL,
        athlete_id TEXT NOT NULL,
        note TEXT NOT NULL,
        rating INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(scout_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(athlete_id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS academy_roster (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        academy_user_id INTEGER NOT NULL,
        athlete_id TEXT NOT NULL,
        status TEXT DEFAULT 'Active',
        created_at TEXT NOT NULL,
        UNIQUE(academy_user_id, athlete_id),
        FOREIGN KEY(academy_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(athlete_id) REFERENCES athlete_profiles(athlete_id) ON DELETE CASCADE
    )
    """)

    # Create an admin if none exists (demo only)
    cur.execute("SELECT COUNT(*) FROM users WHERE role='Admin'")
    if cur.fetchone()[0] == 0:
        cur.execute("""
        INSERT OR IGNORE INTO users(full_name,email,password_hash,role,created_at)
        VALUES (?,?,?,?,?)
        """, ("Admin", "admin@asabig.local", sha256("admin123"), "Admin", now_ts()))

    conn.commit()
    conn.close()


@st.cache_data
def load_csv(name: str) -> Optional[pd.DataFrame]:
    filename = DATA_FILES.get(name)
    if not filename:
        return None
    path = BASE_DIR / filename
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        # fallback
        return pd.read_csv(path, encoding="utf-8", errors="ignore")


def ensure_demo_profiles_from_csv():
    """
    Take athletes.csv demo and ensure a copy exists in DB so that:
    - Uploads / Metrics / Notes can attach to athletes
    """
    demo = load_csv("athletes")
    if demo is None or demo.empty:
        return

    demo = safe_df(demo)
    conn = db()
    cur = conn.cursor()

    # Normalize expected columns
    # required: athlete_id, full_name, gender, birth_year, sport, dominant_side, club, city
    cols = {c.lower(): c for c in demo.columns}
    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    a_id = col("athlete_id", "id")
    full_name = col("full_name", "name")
    gender = col("gender", "sex")
    birth_year = col("birth_year", "yob", "year_of_birth")
    sport = col("sport")
    dom = col("dominant_side", "dominant")
    club = col("club")
    city = col("city")

    if not a_id or not full_name:
        conn.close()
        return

    for _, r in demo.iterrows():
        athlete_id = str(r.get(a_id, "")).strip()
        if not athlete_id:
            continue

        by = r.get(birth_year, "")
        try:
            by_int = int(str(by).strip()) if str(by).strip() else None
        except Exception:
            by_int = None

        # Age group heuristic (demo only)
        ag = None
        if by_int:
            age = dt.datetime.now().year - by_int
            if age <= 10:
                ag = "U10"
            elif age <= 14:
                ag = "U14"
            elif age <= 17:
                ag = "U17"
            else:
                ag = "U23"

        cur.execute("""
        INSERT OR IGNORE INTO athlete_profiles(
            athlete_id, created_by_user_id, full_name, gender, birth_year, age_group,
            sport, dominant_side, club, city, photo_path, preferences_json, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            athlete_id,
            None,
            str(r.get(full_name, "")).strip() or athlete_id,
            (str(r.get(gender, "")).strip()[:1].upper() if gender else None),
            by_int,
            ag,
            (str(r.get(sport, "")).strip() if sport else None),
            (str(r.get(dom, "")).strip() if dom else None),
            (str(r.get(club, "")).strip() if club else None),
            (str(r.get(city, "")).strip() if city else None),
            None,
            None,
            now_ts(),
            now_ts(),
        ))

    conn.commit()
    conn.close()


def get_user_by_email(email: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, email, password_hash, role, linked_athlete_id, academy_name FROM users WHERE email=?", (email.strip().lower(),))
    row = cur.fetchone()
    conn.close()
    return row


def get_user_by_id(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT id, full_name, email, password_hash, role, linked_athlete_id, academy_name FROM users WHERE id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def create_user(full_name: str, email: str, password: str, role: str, linked_athlete_id: Optional[str], academy_name: Optional[str]):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO users(full_name,email,password_hash,role,linked_athlete_id,academy_name,created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (full_name.strip(), email.strip().lower(), sha256(password), role, linked_athlete_id, academy_name, now_ts()))
    conn.commit()
    conn.close()


def current_user():
    uid = st.session_state.get("user_id")
    if not uid:
        return None
    return get_user_by_id(uid)


def login(email: str, password: str) -> bool:
    u = get_user_by_email(email)
    if not u:
        return False
    if sha256(password) != u[3]:
        return False
    st.session_state["user_id"] = u[0]
    return True


def logout():
    st.session_state.pop("user_id", None)


def list_athletes_db() -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT athlete_id, full_name, gender, birth_year, age_group, sport, dominant_side, club, city
        FROM athlete_profiles
        ORDER BY full_name
    """, conn)
    conn.close()
    return safe_df(df)


def get_athlete(athlete_id: str) -> Optional[dict]:
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    SELECT athlete_id, full_name, gender, birth_year, age_group, sport, dominant_side, club, city, photo_path, preferences_json, created_at, updated_at
    FROM athlete_profiles WHERE athlete_id=?
    """, (athlete_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    keys = ["athlete_id","full_name","gender","birth_year","age_group","sport","dominant_side","club","city","photo_path","preferences_json","created_at","updated_at"]
    return dict(zip(keys, r))


def upsert_athlete_profile(athlete_id: str, data: dict, created_by_user_id: Optional[int]):
    existing = get_athlete(athlete_id)
    conn = db()
    cur = conn.cursor()
    if not existing:
        cur.execute("""
        INSERT INTO athlete_profiles(
            athlete_id, created_by_user_id, full_name, gender, birth_year, age_group,
            sport, dominant_side, club, city, photo_path, preferences_json, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            athlete_id,
            created_by_user_id,
            data.get("full_name"),
            data.get("gender"),
            data.get("birth_year"),
            data.get("age_group"),
            data.get("sport"),
            data.get("dominant_side"),
            data.get("club"),
            data.get("city"),
            data.get("photo_path"),
            data.get("preferences_json"),
            now_ts(),
            now_ts(),
        ))
    else:
        cur.execute("""
        UPDATE athlete_profiles SET
            full_name=?, gender=?, birth_year=?, age_group=?, sport=?, dominant_side=?, club=?, city=?,
            photo_path=?, preferences_json=?, updated_at=?
        WHERE athlete_id=?
        """, (
            data.get("full_name"),
            data.get("gender"),
            data.get("birth_year"),
            data.get("age_group"),
            data.get("sport"),
            data.get("dominant_side"),
            data.get("club"),
            data.get("city"),
            data.get("photo_path"),
            data.get("preferences_json"),
            now_ts(),
            athlete_id
        ))
    conn.commit()
    conn.close()


def add_metric(athlete_id: str, metric_name: str, metric_value: float, unit: str, measured_at: str,
               source_role: str, created_by_user_id: Optional[int], notes: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO athlete_metrics(athlete_id, metric_name, metric_value, unit, measured_at, source_role, created_by_user_id, notes)
    VALUES (?,?,?,?,?,?,?,?)
    """, (athlete_id, metric_name, metric_value, unit, measured_at, source_role, created_by_user_id, notes))
    conn.commit()
    conn.close()


def list_metrics(athlete_id: str) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT measured_at, metric_name, metric_value, unit, source_role, notes
        FROM athlete_metrics
        WHERE athlete_id=?
        ORDER BY measured_at DESC
        LIMIT 200
    """, conn, params=(athlete_id,))
    conn.close()
    return safe_df(df)


def save_upload(athlete_id: str, upload_type: str, title: str, file_bytes: Optional[bytes], filename: Optional[str],
                link_url: Optional[str], uploaded_by_user_id: Optional[int]) -> Optional[str]:
    athlete_folder = UPLOADS_DIR / athlete_id / upload_type
    athlete_folder.mkdir(parents=True, exist_ok=True)

    file_path = ""
    if file_bytes and filename:
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = str(athlete_folder / f"{ts}_{safe_name}")
        with open(file_path, "wb") as f:
            f.write(file_bytes)

    conn = db()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO uploads(athlete_id, uploaded_by_user_id, upload_type, title, file_path, link_url, created_at)
    VALUES (?,?,?,?,?,?,?)
    """, (
        athlete_id,
        uploaded_by_user_id,
        upload_type,
        title,
        file_path if file_path else str(athlete_folder / "LINK_ONLY"),
        link_url,
        now_ts()
    ))
    conn.commit()
    conn.close()
    return file_path if file_path else None


def list_uploads(athlete_id: str) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT created_at, upload_type, title, file_path, link_url
        FROM uploads
        WHERE athlete_id=?
        ORDER BY created_at DESC
        LIMIT 200
    """, conn, params=(athlete_id,))
    conn.close()
    return safe_df(df)


def add_scout_note(scout_user_id: int, athlete_id: str, note: str, rating: Optional[int]):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO scout_notes(scout_user_id, athlete_id, note, rating, created_at)
    VALUES (?,?,?,?,?)
    """, (scout_user_id, athlete_id, note, rating, now_ts()))
    conn.commit()
    conn.close()


def list_scout_notes(athlete_id: str) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT created_at, note, rating
        FROM scout_notes
        WHERE athlete_id=?
        ORDER BY created_at DESC
        LIMIT 200
    """, conn, params=(athlete_id,))
    conn.close()
    return safe_df(df)


def academy_add_roster(academy_user_id: int, athlete_id: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR IGNORE INTO academy_roster(academy_user_id, athlete_id, status, created_at)
    VALUES (?,?,?,?)
    """, (academy_user_id, athlete_id, "Active", now_ts()))
    conn.commit()
    conn.close()


def academy_roster(academy_user_id: int) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT r.created_at, r.status, a.athlete_id, a.full_name, a.sport, a.age_group, a.city
        FROM academy_roster r
        JOIN athlete_profiles a ON a.athlete_id = r.athlete_id
        WHERE r.academy_user_id=?
        ORDER BY a.full_name
    """, conn, params=(academy_user_id,))
    conn.close()
    return safe_df(df)


# ============================================================
# INIT
# ============================================================
init_db()
ensure_demo_profiles_from_csv()

# ============================================================
# HEADER + AUTH BAR
# ============================================================
st.title(APP_TITLE)
st.caption("Pilot demo for youth (7–23). All examples can be synthetic. Add real integrations later (Nafath, ABSHER, federations, etc.).")

u = current_user()

colA, colB = st.columns([3, 1])
with colB:
    if u:
        st.success(f"Logged in: {u[1]}  |  {u[4]}")
        if st.button("Logout"):
            logout()
            st.rerun()
    else:
        st.info("Not logged in")


# ============================================================
# NAV
# ============================================================
nav_items_public = [
    "Home",
    "Benchmarks & Data",
    "Athletes (Demo List)",
    "Athlete Profile",
    "Athlete Comparison",
    "About / Governance",
]

nav_items_auth = [
    "Dashboard",
    "Profile & Data Entry",
    "Uploads (PDF/Photo/Video)",
]

nav_items_admin = [
    "Admin Panel",
]

with st.sidebar:
    st.header("ASABIG – Navigation")
    if not u:
        page = st.radio("Choose page:", nav_items_public + ["Login / Register"])
    else:
        base = nav_items_public + nav_items_auth
        if u[4] == "Admin":
            base += nav_items_admin
        page = st.radio("Choose page:", base)

    st.divider()
    st.subheader("Data files status:")
    for k, f in DATA_FILES.items():
        exists = (BASE_DIR / f).exists()
        st.write(f"✅ {f}" if exists else f"❌ {f}")


# ============================================================
# PAGE: LOGIN / REGISTER
# ============================================================
if page == "Login / Register":
    st.subheader("Login")
    with st.form("login_form"):
        email = st.text_input("Email", placeholder="you@email.com")
        password = st.text_input("Password", type="password")
        ok = st.form_submit_button("Login")
    if ok:
        if login(email, password):
            st.success("Logged in successfully.")
            st.rerun()
        else:
            st.error("Invalid email or password.")

    st.divider()
    st.subheader("Register (Pilot)")
    st.caption("Creates account + role. In real product: Nafath / academy verification / guardian consent workflow.")

    with st.form("register_form"):
        full_name = st.text_input("Full name")
        email2 = st.text_input("Email (unique)")
        role = st.selectbox("Role", ROLES, index=0)
        pwd1 = st.text_input("Password", type="password")
        pwd2 = st.text_input("Confirm password", type="password")

        linked_athlete_id = None
        academy_name = None

        if role in ["Player", "Parent"]:
            st.markdown("**Link to Athlete Profile** (optional now — you can create one after login)")
            linked_athlete_id = st.text_input("Athlete ID (if known, e.g., A001). Leave empty to create later.")
        if role == "Academy":
            academy_name = st.text_input("Academy name")

        submit = st.form_submit_button("Create account")

    if submit:
        if not full_name.strip():
            st.error("Full name is required.")
        elif not valid_email(email2):
            st.error("Enter a valid email.")
        elif len(pwd1) < 6:
            st.error("Password must be at least 6 characters.")
        elif pwd1 != pwd2:
            st.error("Passwords do not match.")
        else:
            try:
                create_user(full_name, email2, pwd1, role, (linked_athlete_id.strip() or None), (academy_name.strip() if academy_name else None))
                st.success("Account created. Please login now.")
            except Exception as e:
                st.error(f"Registration failed: {e}")


# ============================================================
# PAGE: HOME
# ============================================================
elif page == "Home":
    st.markdown("### What does ASABIG cover?")
    st.markdown("""
- 20+ sports (team, individual, combat, racket, eSports)
- M/F athletes from 7–23 years
- Integrated view of:
  - Generic growth & maturation
  - Field performance tests
  - Medical & safety gates
  - Sport-specific KPIs
""")

    st.markdown("### Why it matters (for Saudi Arabia)?")
    st.markdown("""
- Aligns with Saudi Vision 2030 – Sports & Quality of Life
- Reduces random selection and late discovery of talent
- Creates a national standard for tests, thresholds, and reporting
- Supports federations, clubs, schools, and private academies
""")

    st.markdown("### (الهدف بالعربي)")
    st.markdown("""
- مشروع يوحّد بيانات المواهب الرياضية ويخدم الجهات في المملكة.
- يعطي اللاعب/الأسرة/الكشاف/الأكاديمية تجربة موحدة.
- يمكّن مقارنة عادلة حسب العمر والجنس والرياضة.
""")


# ============================================================
# PAGE: BENCHMARKS & DATA
# ============================================================
elif page == "Benchmarks & Data":
    st.subheader("Benchmarks & Data – ASABIG Pilot Demo")

    dataset_label = {
        "Generic Talent Data": "generic_talent_data",
        "Field Tests": "field_tests",
        "Medical Data": "medical_data",
        "Sport Specific KPIs": "sport_specific_kpis",
    }

    ds = st.selectbox("Choose dataset:", list(dataset_label.keys()))
    key = dataset_label[ds]
    df = load_csv(key)
    if df is None:
        st.error(f"File not found: {DATA_FILES.get(key)}")
        st.stop()

    df = safe_df(df)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Rows", len(df))
    with c2:
        st.metric("Columns", len(df.columns))
    with c3:
        st.write("Label")
        st.code(DATA_FILES.get(key, ""))

    # Optional filters if exist
    age_col = None
    gender_col = None
    for c in df.columns:
        if c.lower() in ["age_group", "agegroup", "age group", "age group(s)"]:
            age_col = c
        if c.lower() in ["gender", "sex"]:
            gender_col = c

    f1, f2 = st.columns(2)
    with f1:
        if age_col:
            age_val = st.selectbox("Age group filter", ["All"] + sorted(df[age_col].dropna().astype(str).unique().tolist()))
        else:
            age_val = "All"
    with f2:
        if gender_col:
            gender_val = st.selectbox("Gender filter", ["All"] + sorted(df[gender_col].dropna().astype(str).unique().tolist()))
        else:
            gender_val = "All"

    view = df.copy()
    if age_col and age_val != "All":
        view = view[view[age_col].astype(str) == str(age_val)]
    if gender_col and gender_val != "All":
        view = view[view[gender_col].astype(str) == str(gender_val)]

    st.write("Data preview")
    st.dataframe(safe_df(view), use_container_width=True, height=420)

    with st.expander("Summary (numeric columns)"):
        nums = view.select_dtypes(include=["number"])
        if nums.empty:
            st.info("No numeric columns found in this view.")
        else:
            st.dataframe(nums.describe().T, use_container_width=True)


# ============================================================
# PAGE: ATHLETES LIST
# ============================================================
elif page == "Athletes (Demo List)":
    st.subheader("Athletes (Demo + DB)")
    df = list_athletes_db()
    st.dataframe(df, use_container_width=True, height=520)
    st.caption("This list is coming from DB (seeded from athletes.csv + any new athlete profiles created inside the app).")


# ============================================================
# PAGE: ATHLETE PROFILE
# ============================================================
elif page == "Athlete Profile":
    st.subheader("Athlete Profile (DB)")

    athletes = list_athletes_db()
    if athletes.empty:
        st.warning("No athletes found yet.")
        st.stop()

    # select athlete
    display_col = "full_name" if "full_name" in athletes.columns else athletes.columns[0]
    name_to_id = dict(zip(athletes[display_col].astype(str), athletes["athlete_id"].astype(str)))
    pick_name = st.selectbox("Select athlete:", athletes[display_col].astype(str).tolist())
    athlete_id = name_to_id.get(pick_name)

    a = get_athlete(athlete_id)
    if not a:
        st.error("Athlete not found.")
        st.stop()

    left, right = st.columns([2, 1])
    with left:
        st.markdown(f"### {a['full_name']}  (`{a['athlete_id']}`)")
        st.write({
            "Gender": a.get("gender"),
            "Birth Year": a.get("birth_year"),
            "Age Group": a.get("age_group"),
            "Sport": a.get("sport"),
            "Dominant Side": a.get("dominant_side"),
            "Club": a.get("club"),
            "City": a.get("city"),
        })

        st.markdown("#### Recent Metrics")
        mdf = list_metrics(athlete_id)
        st.dataframe(mdf, use_container_width=True, height=260)

        st.markdown("#### Uploads (PDF/Photo/Video)")
        udf = list_uploads(athlete_id)
        st.dataframe(udf, use_container_width=True, height=260)

    with right:
        st.markdown("#### Photo")
        if a.get("photo_path") and Path(a["photo_path"]).exists():
            st.image(a["photo_path"], use_container_width=True)
        else:
            st.info("No photo uploaded yet.")

        st.markdown("#### Scout Notes")
        sdf = list_scout_notes(athlete_id)
        st.dataframe(sdf, use_container_width=True, height=280)


# ============================================================
# PAGE: ATHLETE COMPARISON (UP TO 6)
# ============================================================
elif page == "Athlete Comparison":
    st.subheader("Athlete Comparison – Side by Side (Demo)")

    athletes = list_athletes_db()
    if athletes.empty:
        st.warning("No athletes available.")
        st.stop()

    MAX_COMPARE = 6

    display_col = "full_name" if "full_name" in athletes.columns else athletes.columns[0]
    selected_names = st.multiselect(
        f"Select up to {MAX_COMPARE} athletes to compare:",
        athletes[display_col].astype(str).tolist(),
        default=athletes[display_col].astype(str).head(4).tolist() if len(athletes) >= 4 else None
    )

    if len(selected_names) > MAX_COMPARE:
        st.warning(f"Only first {MAX_COMPARE} athletes will be shown.")
        selected_names = selected_names[:MAX_COMPARE]

    if not selected_names:
        st.info("Select athletes to compare.")
        st.stop()

    comp = athletes[athletes[display_col].astype(str).isin(selected_names)].copy()
    st.dataframe(comp, use_container_width=True, height=220)

    st.markdown("### Simple test comparison (demo)")
    st.caption("Uses athlete_tests.csv (demo) if available + DB metrics if you add them later.")

    # Load demo athlete_tests.csv (optional)
    tests = load_csv("athlete_tests")
    if tests is not None and not tests.empty:
        tests = safe_df(tests)
        # expects athlete_id + metric columns
        if "athlete_id" in tests.columns:
            metric_cols = [c for c in tests.columns if c != "athlete_id"]
            metric = st.selectbox("Metric from athlete_tests.csv", metric_cols, index=0)
            comp_ids = comp["athlete_id"].astype(str).tolist()
            tview = tests[tests["athlete_id"].astype(str).isin(comp_ids)][["athlete_id", metric]].copy()
            tview = tview.merge(comp[["athlete_id", "full_name"]], on="athlete_id", how="left")
            st.bar_chart(tview.set_index("full_name")[metric])
        else:
            st.info("athlete_tests.csv موجود لكن ما فيه عمود athlete_id.")
    else:
        st.info("athlete_tests.csv not found or empty — DB metrics can still be compared via Dashboard (Player/Scout).")


# ============================================================
# PAGE: DASHBOARD (ROLE-BASED)
# ============================================================
elif page == "Dashboard":
    if not u:
        st.warning("Please login first.")
        st.stop()

    user_id, full_name, email, _, role, linked_athlete_id, academy_name = u

    st.subheader(f"{role} Dashboard")

    if role in ["Player", "Parent"]:
        st.markdown("#### Your linked athlete")
        if not linked_athlete_id:
            st.info("No athlete linked yet. Go to **Profile & Data Entry** to create/link one.")
        else:
            a = get_athlete(linked_athlete_id)
            if not a:
                st.warning("Linked athlete ID not found. Go to Profile & Data Entry to create it.")
            else:
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.metric("Athlete", a["full_name"])
                with c2:
                    st.metric("Sport", a.get("sport") or "-")
                with c3:
                    st.metric("Age Group", a.get("age_group") or "-")
                with c4:
                    mcount = len(list_metrics(linked_athlete_id))
                    st.metric("Metrics entries", mcount)

                st.markdown("#### Recent activity")
                st.dataframe(list_metrics(linked_athlete_id).head(15), use_container_width=True)
                st.dataframe(list_uploads(linked_athlete_id).head(15), use_container_width=True)

    elif role == "Scout":
        st.markdown("#### Scout tools")
        athletes = list_athletes_db()
        q = st.text_input("Search athlete (name / city / sport)")
        view = athletes.copy()
        if q.strip():
            ql = q.strip().lower()
            mask = (
                view["full_name"].str.lower().str.contains(ql, na=False) |
                view["city"].str.lower().str.contains(ql, na=False) |
                view["sport"].str.lower().str.contains(ql, na=False)
            )
            view = view[mask]

        st.dataframe(view, use_container_width=True, height=320)

        st.markdown("#### Add scout note / rating")
        if not view.empty:
            pick = st.selectbox("Choose athlete:", view["full_name"].astype(str).tolist())
            athlete_id = view[view["full_name"].astype(str) == pick]["athlete_id"].astype(str).iloc[0]

            with st.form("scout_note_form"):
                rating = st.slider("Rating (1-10)", 1, 10, 7)
                note = st.text_area("Note (strengths, weaknesses, potential, recommendation)")
                submit = st.form_submit_button("Save note")
            if submit:
                if note.strip():
                    add_scout_note(user_id, athlete_id, note.strip(), int(rating))
                    st.success("Saved.")
                else:
                    st.error("Note is required.")
            st.dataframe(list_scout_notes(athlete_id), use_container_width=True, height=220)

    elif role == "Academy":
        st.markdown(f"#### Academy: {academy_name or '(not set)'}")
        st.caption("Roster management (pilot).")
        athletes = list_athletes_db()
        pick = st.selectbox("Add athlete to roster:", athletes["full_name"].astype(str).tolist())
        athlete_id = athletes[athletes["full_name"].astype(str) == pick]["athlete_id"].astype(str).iloc[0]

        if st.button("Add to roster"):
            academy_add_roster(user_id, athlete_id)
            st.success("Added (or already exists).")

        st.markdown("#### Your roster")
        st.dataframe(academy_roster(user_id), use_container_width=True, height=420)

    elif role == "Admin":
        st.markdown("#### Admin overview")
        conn = db()
        users_df = pd.read_sql_query("SELECT id, full_name, email, role, linked_athlete_id, academy_name, created_at FROM users ORDER BY created_at DESC", conn)
        conn.close()
        st.dataframe(safe_df(users_df), use_container_width=True, height=350)

        st.markdown("#### DB Athletes")
        st.dataframe(list_athletes_db(), use_container_width=True, height=350)


# ============================================================
# PAGE: PROFILE & DATA ENTRY
# ============================================================
elif page == "Profile & Data Entry":
    if not u:
        st.warning("Please login first.")
        st.stop()

    user_id, full_name, email, _, role, linked_athlete_id, academy_name = u

    st.subheader("Profile & Data Entry")
    st.caption("Pilot feature: create/update athlete profile + enter test metrics (player/parent), view (scout/academy).")

    # Role permissions
    can_edit_profile = role in ["Player", "Parent", "Admin", "Academy"]
    can_add_metrics = role in ["Player", "Parent", "Scout", "Academy", "Admin"]

    # Choose athlete
    athletes = list_athletes_db()
    selected_athlete_id = None

    if role in ["Player", "Parent"]:
        if linked_athlete_id:
            selected_athlete_id = linked_athlete_id
            st.info(f"Using linked athlete: {linked_athlete_id}")
        else:
            st.warning("No linked athlete yet — create one below (Athlete ID) ثم تقدر تربطه بحسابك.")
    else:
        # Scout/Academy/Admin can select any athlete
        pick = st.selectbox("Select athlete:", athletes["full_name"].astype(str).tolist())
        selected_athlete_id = athletes[athletes["full_name"].astype(str) == pick]["athlete_id"].astype(str).iloc[0]

    st.divider()

    # Create/update athlete profile
    st.markdown("### Athlete Profile")
    if not selected_athlete_id:
        selected_athlete_id = st.text_input("Athlete ID (create new)", placeholder="e.g., A1001").strip()

    if selected_athlete_id:
        current = get_athlete(selected_athlete_id)

        if current:
            st.success(f"Loaded athlete: {current['full_name']} ({current['athlete_id']})")
        else:
            st.info("This athlete ID is new. Fill details and Save to create profile.")

        if not can_edit_profile:
            st.warning("Your role can view only. (No edit permissions here).")
        else:
            with st.form("ath_profile_form"):
                full_name_f = st.text_input("Full name", value=(current.get("full_name") if current else ""))
                gender_f = st.selectbox("Gender", [""] + GENDERS, index=(1 if current and current.get("gender") == "M" else 2 if current and current.get("gender") == "F" else 0))
                birth_year_f = st.number_input("Birth year", min_value=1980, max_value=dt.datetime.now().year, value=(int(current.get("birth_year") or 2010) if current else 2010))
                age_group_f = st.selectbox("Age group", [""] + AGE_GROUPS, index=(AGE_GROUPS.index(current.get("age_group")) + 1 if current and current.get("age_group") in AGE_GROUPS else 0))
                sport_f = st.text_input("Sport", value=(current.get("sport") if current else ""))
                dominant_f = st.text_input("Dominant side", value=(current.get("dominant_side") if current else ""))
                club_f = st.text_input("Club", value=(current.get("club") if current else ""))
                city_f = st.text_input("City", value=(current.get("city") if current else ""))

                prefs = st.text_area("Preferences (JSON or text)", value=(current.get("preferences_json") if current else ""), height=90)
                save = st.form_submit_button("Save profile")

            if save:
                data = {
                    "full_name": full_name_f.strip(),
                    "gender": gender_f.strip() or None,
                    "birth_year": int(birth_year_f) if birth_year_f else None,
                    "age_group": age_group_f.strip() or None,
                    "sport": sport_f.strip() or None,
                    "dominant_side": dominant_f.strip() or None,
                    "club": club_f.strip() or None,
                    "city": city_f.strip() or None,
                    "photo_path": current.get("photo_path") if current else None,
                    "preferences_json": prefs.strip() or None,
                }
                upsert_athlete_profile(selected_athlete_id, data, created_by_user_id=user_id)
                st.success("Saved athlete profile.")

                # Auto-link for Player/Parent if missing
                if role in ["Player", "Parent"] and not linked_athlete_id:
                    conn = db()
                    cur = conn.cursor()
                    cur.execute("UPDATE users SET linked_athlete_id=? WHERE id=?", (selected_athlete_id, user_id))
                    conn.commit()
                    conn.close()
                    st.success("Linked athlete to your account.")
                st.rerun()

        st.divider()
        st.markdown("### Add test metric")
        if can_add_metrics:
            with st.form("metric_form"):
                metric_name = st.text_input("Metric name", placeholder="e.g., Vertical Jump, VO2max, Sprint 30m, BMI")
                metric_value = st.number_input("Value", value=0.0)
                unit = st.text_input("Unit", placeholder="cm, sec, kg, ml/kg/min ...")
                measured_at = st.date_input("Measured date", value=dt.date.today()).strftime("%Y-%m-%d")
                notes = st.text_area("Notes (optional)", height=80)
                submit = st.form_submit_button("Add metric")
            if submit:
                if not metric_name.strip():
                    st.error("Metric name is required.")
                else:
                    add_metric(
                        athlete_id=selected_athlete_id,
                        metric_name=metric_name.strip(),
                        metric_value=float(metric_value),
                        unit=unit.strip() or None,
                        measured_at=measured_at,
                        source_role=role,
                        created_by_user_id=user_id,
                        notes=notes.strip() or None
                    )
                    st.success("Metric added.")
                    st.rerun()

        st.markdown("### Recent metrics")
        st.dataframe(list_metrics(selected_athlete_id), use_container_width=True, height=320)


# ============================================================
# PAGE: UPLOADS (PDF / PHOTO / VIDEO)
# ============================================================
elif page == "Uploads (PDF/Photo/Video)":
    if not u:
        st.warning("Please login first.")
        st.stop()

    user_id, full_name, email, _, role, linked_athlete_id, academy_name = u
    st.subheader("Uploads – Medical PDF / Photo / Video")
    st.caption("Pilot: files are saved in /uploads on the app server. In production: S3/Cloud storage + permissions + audit logs.")

    # Choose athlete
    athletes = list_athletes_db()
    selected_athlete_id = None

    if role in ["Player", "Parent"]:
        selected_athlete_id = linked_athlete_id
        if not selected_athlete_id:
            st.warning("No linked athlete. Go to Profile & Data Entry first.")
            st.stop()
        st.info(f"Uploading for athlete: {selected_athlete_id}")
    else:
        pick = st.selectbox("Select athlete:", athletes["full_name"].astype(str).tolist())
        selected_athlete_id = athletes[athletes["full_name"].astype(str) == pick]["athlete_id"].astype(str).iloc[0]

    st.divider()
    tab1, tab2, tab3 = st.tabs(["Medical PDF", "Photo", "Video"])

    with tab1:
        st.markdown("#### Upload medical test PDF")
        pdf = st.file_uploader("Choose PDF", type=["pdf"])
        title = st.text_input("Title", placeholder="e.g., Blood test, MRI, Fitness clearance")
        if st.button("Save PDF"):
            if not pdf:
                st.error("Please choose a PDF.")
            else:
                save_upload(
                    athlete_id=selected_athlete_id,
                    upload_type="medical_pdf",
                    title=(title.strip() or "Medical PDF"),
                    file_bytes=pdf.getvalue(),
                    filename=pdf.name,
                    link_url=None,
                    uploaded_by_user_id=user_id
                )
                st.success("Saved medical PDF.")
                st.rerun()

    with tab2:
        st.markdown("#### Upload athlete photo")
        img = st.file_uploader("Choose image", type=["png", "jpg", "jpeg"])
        if st.button("Save Photo"):
            if not img:
                st.error("Please choose an image.")
            else:
                file_path = save_upload(
                    athlete_id=selected_athlete_id,
                    upload_type="photo",
                    title="Profile Photo",
                    file_bytes=img.getvalue(),
                    filename=img.name,
                    link_url=None,
                    uploaded_by_user_id=user_id
                )
                # set photo_path on athlete profile
                a = get_athlete(selected_athlete_id) or {}
                a["photo_path"] = file_path
                upsert_athlete_profile(selected_athlete_id, a, created_by_user_id=None)
                st.success("Saved photo and updated athlete profile.")
                st.rerun()

    with tab3:
        st.markdown("#### Add video (link) or upload MP4")
        st.caption("Best practice: use link (YouTube/Vimeo) for pilot. MP4 upload may be limited on Streamlit hosting.")
        vlink = st.text_input("Video link URL", placeholder="https://youtube.com/...")
        vfile = st.file_uploader("Or upload video file", type=["mp4", "mov", "m4v"])
        vtitle = st.text_input("Video title", placeholder="e.g., Highlights, Training session")
        if st.button("Save Video"):
            if not vlink and not vfile:
                st.error("Provide a link or upload a video file.")
            else:
                file_bytes = vfile.getvalue() if vfile else None
                filename = vfile.name if vfile else None
                save_upload(
                    athlete_id=selected_athlete_id,
                    upload_type="video",
                    title=(vtitle.strip() or "Video"),
                    file_bytes=file_bytes,
                    filename=filename,
                    link_url=(vlink.strip() or None),
                    uploaded_by_user_id=user_id
                )
                st.success("Saved video.")
                st.rerun()

    st.divider()
    st.markdown("### All uploads for athlete")
    udf = list_uploads(selected_athlete_id)
    st.dataframe(udf, use_container_width=True, height=420)


# ============================================================
# PAGE: ADMIN PANEL
# ============================================================
elif page == "Admin Panel":
    if not u or u[4] != "Admin":
        st.warning("Admin only.")
        st.stop()

    st.subheader("Admin Panel (Pilot)")
    st.caption("User management + exports (pilot only).")

    conn = db()
    users_df = pd.read_sql_query("SELECT id, full_name, email, role, linked_athlete_id, academy_name, created_at FROM users ORDER BY created_at DESC", conn)
    conn.close()

    st.markdown("### Users")
    st.dataframe(safe_df(users_df), use_container_width=True, height=360)

    st.markdown("### Export athletes/metrics/uploads")
    a = list_athletes_db()
    st.download_button("Download athletes.csv (export)", data=a.to_csv(index=False).encode("utf-8"), file_name="asabig_athletes_export.csv")

    conn = db()
    metrics_df = pd.read_sql_query("SELECT athlete_id, metric_name, metric_value, unit, measured_at, source_role, notes FROM athlete_metrics ORDER BY measured_at DESC", conn)
    uploads_df = pd.read_sql_query("SELECT athlete_id, upload_type, title, file_path, link_url, created_at FROM uploads ORDER BY created_at DESC", conn)
    conn.close()

    st.download_button("Download metrics.csv (export)", data=safe_df(metrics_df).to_csv(index=False).encode("utf-8"), file_name="asabig_metrics_export.csv")
    st.download_button("Download uploads.csv (export)", data=safe_df(uploads_df).to_csv(index=False).encode("utf-8"), file_name="asabig_uploads_export.csv")


# ============================================================
# PAGE: ABOUT / GOVERNANCE
# ============================================================
elif page == "About / Governance":
    st.subheader("About / Governance (Pilot)")
    st.markdown("""
**ASABIG** is a national talent identification concept to unify youth athlete data and scouting signals.

**Pilot scope (Streamlit):**
- Demo datasets (benchmarks + athletes)
- Role-based login (Player / Parent / Scout / Academy / Admin)
- Athlete profile creation/update
- Data entry (metrics)
- Upload center (Medical PDF + Photo + Video link/file)
- Scout notes
- Academy roster

**Next stage (Product MVP):**
- Verified registration (Nafath / Academy verification)
- Guardian consent workflow + PDPL compliance controls
- Sport-by-sport metric standardization and normalization
- AI scoring & talent recommendations
- Federations dashboards and national reporting
- Cloud storage, audit logs, and fine-grained permissions
""")

    st.info("Pilot reminder: this is a demo running on Streamlit. For production, use a backend (API) + secure storage + full compliance controls.")


# ============================================================
# FALLBACK
# ============================================================
else:
    st.info("Select a page from the sidebar.")
