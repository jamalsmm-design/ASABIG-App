import streamlit as st
import pandas as pd
from pathlib import Path
import sqlite3
import json
import hashlib
import secrets
import datetime
import re

# =========================
# Basic page setup
# =========================
st.set_page_config(
    page_title="ASABIG Talent Platform – Pilot Demo",
    layout="wide",
)

BASE_DIR = Path(__file__).parent

# =========================
# Data files (CSV demo)
# =========================
DATA_FILES = {
    "generic_talent_data": "generic_talent_data.csv",
    "field_tests": "field_tests.csv",
    "medical_data": "medical_data.csv",
    "sport_specific_kpis": "sport_specific_kpis.csv",
    "athletes": "athletes.csv",
    "athlete_tests": "athlete_tests.csv",
}

# =========================
# Storage (SQLite + uploads)
# =========================
DB_PATH = BASE_DIR / "asabig.db"
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_MEDICAL = UPLOADS_DIR / "medical"
UPLOADS_PHOTOS = UPLOADS_DIR / "photos"

UPLOADS_DIR.mkdir(exist_ok=True)
UPLOADS_MEDICAL.mkdir(exist_ok=True)
UPLOADS_PHOTOS.mkdir(exist_ok=True)


def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = db_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL,
        salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        player_code TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        gender TEXT,
        birth_year INTEGER,
        sport TEXT,
        club TEXT,
        city TEXT,
        photo_path TEXT,
        preferences_json TEXT,
        consent_parent INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS parent_links (
        parent_user_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(parent_user_id, player_id),
        FOREIGN KEY(parent_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        test_date TEXT NOT NULL,
        test_name TEXT NOT NULL,
        value REAL,
        unit TEXT,
        notes TEXT,
        entered_by_user_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
        FOREIGN KEY(entered_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS medical_docs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        doc_type TEXT NOT NULL,
        doc_date TEXT,
        file_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        notes TEXT,
        uploaded_by_user_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
        FOREIGN KEY(uploaded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        notes TEXT,
        uploaded_by_user_id INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
        FOREIGN KEY(uploaded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS scout_shortlist (
        scout_user_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        rating INTEGER,
        notes TEXT,
        created_at TEXT NOT NULL,
        PRIMARY KEY(scout_user_id, player_id),
        FOREIGN KEY(scout_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS academy_roster (
        academy_user_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(academy_user_id, player_id),
        FOREIGN KEY(academy_user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()


init_db()

# =========================
# Utilities
# =========================
def now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def safe_filename(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "_", name)
    return name[:120] if name else "file"


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def normalize_gender_value(x) -> str:
    if pd.isna(x):
        return x
    s = str(x).strip().upper()
    mapping = {
        "MALE": "M",
        "M": "M",
        "FEMALE": "F",
        "F": "F",
        "M\\F": "M/F",
        "M/F": "M/F",
        "M / F": "M/F",
        "MF": "M/F",
    }
    return mapping.get(s, s)


def normalize_gender_column(df: pd.DataFrame, col: str) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns:
        return df
    df = df.copy()
    df[col] = df[col].apply(normalize_gender_value)
    return df


def apply_inclusive_gender_filter(df: pd.DataFrame, col: str, selection: str) -> pd.DataFrame:
    if df is None or df.empty or col not in df.columns or selection == "All":
        return df
    if selection == "M":
        return df[df[col].isin(["M", "M/F"])]
    if selection == "F":
        return df[df[col].isin(["F", "M/F"])]
    if selection == "M/F":
        return df[df[col] == "M/F"]
    return df


def section_title(text: str):
    st.markdown(f"### {text}")


def small_note(text: str):
    st.caption(text)


# =========================
# CSV loader (demo)
# =========================
@st.cache_data
def load_csv(name: str):
    filename = DATA_FILES.get(name)
    if not filename:
        return None
    path = BASE_DIR / filename
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        st.warning(f"⚠️ Error loading **{filename}**: {e}")
        return None


dfs = {k: load_csv(k) for k in DATA_FILES.keys()}
generic_df = normalize_gender_column(dfs.get("generic_talent_data"), "Gender")
field_df = normalize_gender_column(dfs.get("field_tests"), "Gender")
medical_df = normalize_gender_column(dfs.get("medical_data"), "Gender")
kpi_df = normalize_gender_column(dfs.get("sport_specific_kpis"), "Gender")
athletes_df = dfs.get("athletes")
athlete_tests_df = dfs.get("athlete_tests")

# =========================
# Auth (session)
# =========================
if "user" not in st.session_state:
    st.session_state.user = None  # dict: {id,email,full_name,role}
if "active_player_id" not in st.session_state:
    st.session_state.active_player_id = None


def set_user(user_row: dict):
    st.session_state.user = user_row


def logout():
    st.session_state.user = None
    st.session_state.active_player_id = None


def get_user():
    return st.session_state.user


def require_login():
    if not get_user():
        st.warning("Please login to access this page.")
        st.stop()


def role():
    u = get_user()
    return u["role"] if u else None


# =========================
# DB helpers
# =========================
def db_fetchone(query, params=()):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return row


def db_fetchall(query, params=()):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def db_execute(query, params=()):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def ensure_player_record_for_user(user_id: int, full_name: str) -> int:
    # If user already linked to a player row, return it
    row = db_fetchone("SELECT id FROM players WHERE user_id = ?", (user_id,))
    if row:
        return int(row[0])

    # Create new player record
    code = "P-" + secrets.token_hex(4).upper()  # e.g., P-1A2B3C4D
    created = now_iso()
    prefs = json.dumps({"visibility": "Private"})
    pid = db_execute(
        """INSERT INTO players (user_id, player_code, full_name, preferences_json, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, code, full_name, prefs, created)
    )
    return pid


def get_player_by_id(player_id: int):
    row = db_fetchone(
        """SELECT id, user_id, player_code, full_name, gender, birth_year, sport, club, city,
                  photo_path, preferences_json, consent_parent, created_at
           FROM players WHERE id = ?""",
        (player_id,)
    )
    if not row:
        return None
    keys = ["id","user_id","player_code","full_name","gender","birth_year","sport","club","city",
            "photo_path","preferences_json","consent_parent","created_at"]
    d = dict(zip(keys, row))
    try:
        d["preferences"] = json.loads(d["preferences_json"]) if d["preferences_json"] else {}
    except Exception:
        d["preferences"] = {}
    return d


def get_players_for_parent(parent_user_id: int):
    rows = db_fetchall("""
        SELECT p.id, p.player_code, p.full_name, p.gender, p.birth_year, p.sport, p.club, p.city, p.consent_parent
        FROM parent_links pl
        JOIN players p ON p.id = pl.player_id
        WHERE pl.parent_user_id = ?
        ORDER BY p.full_name
    """, (parent_user_id,))
    return rows


def parent_link_player(parent_user_id: int, player_code: str) -> bool:
    row = db_fetchone("SELECT id FROM players WHERE player_code = ?", (player_code.strip(),))
    if not row:
        return False
    player_id = int(row[0])
    try:
        db_execute(
            "INSERT OR IGNORE INTO parent_links (parent_user_id, player_id, created_at) VALUES (?, ?, ?)",
            (parent_user_id, player_id, now_iso())
        )
        return True
    except Exception:
        return False


# =========================
# Sidebar UI
# =========================
st.sidebar.title("ASABIG – Navigation")

# Data files status (demo)
st.sidebar.subheader("Data files status:")
for key, filename in DATA_FILES.items():
    if dfs.get(key) is not None:
        st.sidebar.success(filename)
    else:
        st.sidebar.error(filename)

st.sidebar.markdown("---")

u = get_user()
if u:
    st.sidebar.success(f"Logged in: {u['full_name']} ({u['role']})")
    if st.sidebar.button("Logout"):
        logout()
        st.rerun()
else:
    st.sidebar.info("Not logged in")

# Page menu (public + auth + dashboards)
base_pages = ["Home", "Benchmarks & Data", "Model", "Athletes (Demo List)", "Athlete Profile", "Athlete Comparison", "About / Governance"]
auth_pages = ["Login / Register"]

role_pages = []
if u:
    role_pages.append("Dashboard")  # role-specific inside
    if u["role"] == "Admin":
        role_pages.append("Admin Panel")

page = st.sidebar.radio("Choose page:", auth_pages + role_pages + base_pages)

# =========================
# PAGE: LOGIN / REGISTER
# =========================
if page == "Login / Register":
    st.title("Login / Register")

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        st.subheader("Login")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("Login"):
            if not email or not password:
                st.error("Please enter email and password.")
            else:
                row = db_fetchone("SELECT id, email, full_name, role, salt, password_hash FROM users WHERE email = ?", (email.strip().lower(),))
                if not row:
                    st.error("Invalid credentials.")
                else:
                    user_id, em, full_name, r, salt, ph = row
                    if hash_password(password, salt) != ph:
                        st.error("Invalid credentials.")
                    else:
                        set_user({"id": int(user_id), "email": em, "full_name": full_name, "role": r})
                        st.success("Logged in successfully.")
                        st.rerun()

    with tab2:
        st.subheader("Register")
        full_name = st.text_input("Full name", key="reg_full_name")
        email = st.text_input("Email", key="reg_email")
        role_sel = st.selectbox("Role", ["Player", "Parent", "Scout", "Academy"], index=0, key="reg_role")
        password = st.text_input("Password", type="password", key="reg_password")
        password2 = st.text_input("Confirm password", type="password", key="reg_password2")

        if st.button("Create account"):
            email_norm = (email or "").strip().lower()
            if not full_name or not email_norm or not password:
                st.error("Please fill all required fields.")
            elif password != password2:
                st.error("Passwords do not match.")
            else:
                existing = db_fetchone("SELECT id FROM users WHERE email = ?", (email_norm,))
                if existing:
                    st.error("Email already registered. Please login.")
                else:
                    salt = secrets.token_hex(16)
                    ph = hash_password(password, salt)
                    uid = db_execute(
                        """INSERT INTO users (email, full_name, role, salt, password_hash, created_at)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (email_norm, full_name.strip(), role_sel, salt, ph, now_iso())
                    )

                    # If Player role, create a player profile with a code
                    if role_sel == "Player":
                        pid = ensure_player_record_for_user(uid, full_name.strip())
                        p = get_player_by_id(pid)
                        st.success(f"Account created. Your Player Code is: {p['player_code']} (save it).")
                    else:
                        st.success("Account created successfully. Please login.")

# =========================
# PAGE: DASHBOARD (Role-based)
# =========================
elif page == "Dashboard":
    require_login()
    u = get_user()
    st.title(f"Dashboard – {u['role']}")

    # -------------------------
    # PLAYER DASHBOARD
    # -------------------------
    if u["role"] == "Player":
        player_id = ensure_player_record_for_user(u["id"], u["full_name"])
        st.session_state.active_player_id = player_id
        p = get_player_by_id(player_id)

        c1, c2, c3 = st.columns(3)
        c1.metric("Player Code", p["player_code"])
        c2.metric("Consent (Parent)", "Yes" if p["consent_parent"] else "No")
        vis = p.get("preferences", {}).get("visibility", "Private")
        c3.metric("Visibility", vis)

        st.markdown("---")
        section_title("Profile")
        colA, colB = st.columns([1, 2])

        with colA:
            if p["photo_path"] and Path(p["photo_path"]).exists():
                st.image(str(p["photo_path"]), caption="Profile Photo", use_container_width=True)
            photo = st.file_uploader("Upload profile photo (jpg/png)", type=["jpg", "jpeg", "png"])
            if photo and st.button("Save photo"):
                fname = safe_filename(f"{p['player_code']}_{photo.name}")
                out = UPLOADS_PHOTOS / fname
                out.write_bytes(photo.getbuffer())
                db_execute("UPDATE players SET photo_path = ? WHERE id = ?", (str(out), player_id))
                st.success("Photo saved.")
                st.rerun()

        with colB:
            full_name = st.text_input("Full name", value=p["full_name"])
            gender = st.selectbox("Gender", ["", "M", "F", "M/F"], index=0 if not p["gender"] else ["", "M", "F", "M/F"].index(normalize_gender_value(p["gender"])))
            birth_year = st.number_input("Birth year", min_value=1990, max_value=2035, value=int(p["birth_year"]) if p["birth_year"] else 2010)
            sport = st.text_input("Sport", value=p["sport"] or "")
            club = st.text_input("Club / Academy", value=p["club"] or "")
            city = st.text_input("City", value=p["city"] or "")

            visibility = st.selectbox("Visibility preference", ["Private", "Partial", "Full"], index=["Private","Partial","Full"].index(p.get("preferences", {}).get("visibility", "Private")))
            if st.button("Save profile"):
                prefs = p.get("preferences", {})
                prefs["visibility"] = visibility
                db_execute(
                    """UPDATE players
                       SET full_name=?, gender=?, birth_year=?, sport=?, club=?, city=?, preferences_json=?
                       WHERE id=?""",
                    (full_name.strip(), gender, int(birth_year), sport.strip(), club.strip(), city.strip(), json.dumps(prefs), player_id)
                )
                st.success("Profile updated.")
                st.rerun()

        st.markdown("---")
        section_title("Enter Test Data")
        tcol1, tcol2, tcol3 = st.columns(3)
        test_date = tcol1.date_input("Test date", value=datetime.date.today())
        test_name = tcol2.text_input("Test name (e.g., 20m Sprint, Vertical Jump)")
        unit = tcol3.text_input("Unit (e.g., s, cm, kg)")
        value = st.number_input("Value", value=0.0, step=0.1)
        notes = st.text_area("Notes (optional)")

        if st.button("Save test"):
            if not test_name:
                st.error("Test name is required.")
            else:
                db_execute(
                    """INSERT INTO tests (player_id, test_date, test_name, value, unit, notes, entered_by_user_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (player_id, test_date.isoformat(), test_name.strip(), float(value), unit.strip(), notes.strip(), u["id"], now_iso())
                )
                st.success("Test saved.")
                st.rerun()

        st.markdown("#### Latest tests")
        tests = db_fetchall(
            """SELECT test_date, test_name, value, unit, notes
               FROM tests WHERE player_id=? ORDER BY test_date DESC, id DESC LIMIT 20""",
            (player_id,)
        )
        if tests:
            df = pd.DataFrame(tests, columns=["Date", "Test", "Value", "Unit", "Notes"])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No tests saved yet.")

        st.markdown("---")
        section_title("Medical Upload (PDF)")
        pdf = st.file_uploader("Upload medical report (PDF)", type=["pdf"])
        doc_type = st.text_input("Document type (e.g., Blood Test, MRI, Clearance)")
        doc_date = st.date_input("Document date", value=datetime.date.today())

        if st.button("Upload medical PDF"):
            if not pdf or not doc_type:
                st.error("Please upload a PDF and enter document type.")
            else:
                fname = safe_filename(f"{p['player_code']}_{doc_type}_{pdf.name}")
                out = UPLOADS_MEDICAL / fname
                out.write_bytes(pdf.getbuffer())
                db_execute(
                    """INSERT INTO medical_docs (player_id, doc_type, doc_date, file_path, status, uploaded_by_user_id, created_at)
                       VALUES (?, ?, ?, ?, 'Pending', ?, ?)""",
                    (player_id, doc_type.strip(), doc_date.isoformat(), str(out), u["id"], now_iso())
                )
                st.success("Medical PDF uploaded (Pending).")
                st.rerun()

        st.markdown("#### Medical documents")
        docs = db_fetchall(
            """SELECT doc_type, doc_date, status, file_path, created_at
               FROM medical_docs WHERE player_id=? ORDER BY id DESC LIMIT 20""",
            (player_id,)
        )
        if docs:
            df = pd.DataFrame(docs, columns=["Type", "Date", "Status", "File", "Uploaded"])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No medical documents uploaded yet.")

        st.markdown("---")
        section_title("Videos (Links)")
        vtitle = st.text_input("Video title")
        vurl = st.text_input("Video URL (YouTube/Drive/etc.)")
        vnotes = st.text_area("Video notes (optional)", key="vnotes_player")

        if st.button("Add video link"):
            if not vtitle or not vurl:
                st.error("Title and URL are required.")
            else:
                db_execute(
                    """INSERT INTO videos (player_id, title, url, notes, uploaded_by_user_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (player_id, vtitle.strip(), vurl.strip(), vnotes.strip(), u["id"], now_iso())
                )
                st.success("Video saved.")
                st.rerun()

        vids = db_fetchall("""SELECT title, url, notes, created_at FROM videos WHERE player_id=? ORDER BY id DESC LIMIT 20""", (player_id,))
        if vids:
            dfv = pd.DataFrame(vids, columns=["Title", "URL", "Notes", "Added"])
            st.dataframe(dfv, use_container_width=True)
        else:
            st.info("No videos added yet.")

    # -------------------------
    # PARENT DASHBOARD
    # -------------------------
    elif u["role"] == "Parent":
        section_title("Link to your child (Player Code)")
        code = st.text_input("Enter Player Code (e.g., P-1A2B3C4D)")
        if st.button("Link player"):
            if not code:
                st.error("Enter a player code.")
            else:
                ok = parent_link_player(u["id"], code)
                if ok:
                    st.success("Player linked successfully.")
                    st.rerun()
                else:
                    st.error("Invalid code or unable to link.")

        st.markdown("---")
        section_title("Your linked players")
        rows = get_players_for_parent(u["id"])
        if not rows:
            st.info("No linked players yet.")
        else:
            df = pd.DataFrame(rows, columns=["Player ID", "Code", "Name", "Gender", "Birth", "Sport", "Club", "City", "Consent"])
            st.dataframe(df, use_container_width=True)

            player_ids = df["Player ID"].tolist()
            chosen = st.selectbox("Select a player to manage", player_ids)
            p = get_player_by_id(int(chosen))

            st.markdown("#### Consent")
            consent = st.checkbox("I confirm parental consent for data sharing (within ASABIG)", value=bool(p["consent_parent"]))
            if st.button("Save consent"):
                db_execute("UPDATE players SET consent_parent=? WHERE id=?", (1 if consent else 0, p["id"]))
                st.success("Consent updated.")
                st.rerun()

            st.markdown("---")
            section_title("Upload medical PDF for this player")
            pdf = st.file_uploader("Upload medical report (PDF)", type=["pdf"], key="parent_pdf")
            doc_type = st.text_input("Document type", key="parent_doc_type")
            doc_date = st.date_input("Document date", value=datetime.date.today(), key="parent_doc_date")

            if st.button("Upload medical PDF (Parent)"):
                if not pdf or not doc_type:
                    st.error("Please upload a PDF and enter document type.")
                else:
                    fname = safe_filename(f"{p['player_code']}_{doc_type}_{pdf.name}")
                    out = UPLOADS_MEDICAL / fname
                    out.write_bytes(pdf.getbuffer())
                    db_execute(
                        """INSERT INTO medical_docs (player_id, doc_type, doc_date, file_path, status, uploaded_by_user_id, created_at)
                           VALUES (?, ?, ?, ?, 'Pending', ?, ?)""",
                        (p["id"], doc_type.strip(), doc_date.isoformat(), str(out), u["id"], now_iso())
                    )
                    st.success("Medical PDF uploaded (Pending).")
                    st.rerun()

    # -------------------------
    # SCOUT DASHBOARD
    # -------------------------
    elif u["role"] == "Scout":
        section_title("Search players")
        q = st.text_input("Search by name / sport / club / city")
        # Search in DB players (MVP)
        params = []
        where = ""
        if q.strip():
            where = "WHERE full_name LIKE ? OR sport LIKE ? OR club LIKE ? OR city LIKE ?"
            like = f"%{q.strip()}%"
            params = [like, like, like, like]

        rows = db_fetchall(
            f"""SELECT id, player_code, full_name, gender, birth_year, sport, club, city, consent_parent
                FROM players {where}
                ORDER BY full_name LIMIT 200""",
            tuple(params)
        )
        if rows:
            df = pd.DataFrame(rows, columns=["ID", "Code", "Name", "Gender", "Birth", "Sport", "Club", "City", "Consent"])
            st.dataframe(df, use_container_width=True)

            section_title("Shortlist")
            pid = st.number_input("Player ID to shortlist", min_value=1, step=1)
            rating = st.slider("Rating", 1, 10, 7)
            notes = st.text_area("Notes", key="scout_notes")
            if st.button("Add/Update shortlist"):
                db_execute(
                    """INSERT INTO scout_shortlist (scout_user_id, player_id, rating, notes, created_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(scout_user_id, player_id) DO UPDATE SET rating=excluded.rating, notes=excluded.notes""",
                    (u["id"], int(pid), int(rating), notes.strip(), now_iso())
                )
                st.success("Shortlist updated.")

            sl = db_fetchall(
                """SELECT p.player_code, p.full_name, s.rating, s.notes, s.created_at
                   FROM scout_shortlist s JOIN players p ON p.id=s.player_id
                   WHERE s.scout_user_id=? ORDER BY s.created_at DESC""",
                (u["id"],)
            )
            if sl:
                sdf = pd.DataFrame(sl, columns=["Code", "Name", "Rating", "Notes", "Saved"])
                st.dataframe(sdf, use_container_width=True)
        else:
            st.info("No players found yet in DB (create Player accounts first).")

    # -------------------------
    # ACADEMY DASHBOARD
    # -------------------------
    elif u["role"] == "Academy":
        section_title("Academy Roster")
        st.info("MVP: add players to your roster by Player Code.")
        code = st.text_input("Player Code to add to roster")
        if st.button("Add to roster"):
            row = db_fetchone("SELECT id FROM players WHERE player_code=?", (code.strip(),))
            if not row:
                st.error("Invalid Player Code.")
            else:
                player_id = int(row[0])
                db_execute(
                    "INSERT OR IGNORE INTO academy_roster (academy_user_id, player_id, created_at) VALUES (?, ?, ?)",
                    (u["id"], player_id, now_iso())
                )
                st.success("Added to roster.")
                st.rerun()

        roster = db_fetchall(
            """SELECT p.player_code, p.full_name, p.gender, p.birth_year, p.sport, p.club, p.city
               FROM academy_roster ar JOIN players p ON p.id=ar.player_id
               WHERE ar.academy_user_id=?
               ORDER BY p.full_name""",
            (u["id"],)
        )
        if roster:
            df = pd.DataFrame(roster, columns=["Code","Name","Gender","Birth","Sport","Club","City"])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No players in roster yet.")

    else:
        st.info("Role not recognized.")

# =========================
# PAGE: ADMIN PANEL
# =========================
elif page == "Admin Panel":
    require_login()
    if role() != "Admin":
        st.error("Admins only.")
        st.stop()

    st.title("Admin Panel")
    section_title("Users")
    users = db_fetchall("SELECT id, email, full_name, role, created_at FROM users ORDER BY id DESC LIMIT 200")
    st.dataframe(pd.DataFrame(users, columns=["ID","Email","Name","Role","Created"]), use_container_width=True)

    st.markdown("---")
    section_title("Medical Docs (Approve/Reject)")
    docs = db_fetchall("""
        SELECT d.id, p.player_code, p.full_name, d.doc_type, d.doc_date, d.status, d.file_path, d.created_at
        FROM medical_docs d
        JOIN players p ON p.id=d.player_id
        ORDER BY d.id DESC LIMIT 200
    """)
    if docs:
        ddf = pd.DataFrame(docs, columns=["DocID","PlayerCode","PlayerName","Type","Date","Status","File","Uploaded"])
        st.dataframe(ddf, use_container_width=True)

        doc_id = st.number_input("DocID", min_value=1, step=1)
        new_status = st.selectbox("Set status", ["Pending","Approved","Rejected"])
        note = st.text_input("Admin note (optional)")
        if st.button("Update doc status"):
            db_execute("UPDATE medical_docs SET status=?, notes=? WHERE id=?", (new_status, note.strip(), int(doc_id)))
            st.success("Updated.")
            st.rerun()
    else:
        st.info("No medical docs uploaded yet.")

# =========================
# PAGE: HOME
# =========================
elif page == "Home":
    st.title("ASABIG – Talent Identification Platform (Pilot Demo)")
    st.markdown(
        """
ASABIG is a **data-driven talent identification platform** for youth (7–23 years),
serving federations, clubs, academies, and national stakeholders in Saudi Arabia.
"""
    )
    section_title("What does ASABIG cover?")
    st.markdown(
        """
- **Multi-sport** framework (extendable)
- **M/F athletes** from **7–23 years**
- Integrated view of:
  - Generic growth & maturation
  - Field performance tests
  - Medical & safety gates
  - Sport-specific KPIs
        """
    )
    section_title("Why it matters?")
    st.markdown(
        """
- Reduces **random selection** and **late discovery**
- Creates **national benchmarks**
- Enables **structured scouting** and **athlete development tracking**
        """
    )
    st.info("🔬 Pilot demo: the DB users/players here are for testing only.")

# =========================
# PAGE: BENCHMARKS & DATA
# =========================
elif page == "Benchmarks & Data":
    st.title("Benchmarks & Data – ASABIG Pilot Demo")

    dataset_name = st.selectbox(
        "Choose dataset:",
        ["Generic Talent Data", "Field Tests", "Medical Data", "Sport-Specific KPIs"],
    )

    if dataset_name == "Generic Talent Data":
        df = generic_df
        label = "generic_talent_data.csv"
    elif dataset_name == "Field Tests":
        df = field_df
        label = "field_tests.csv"
    elif dataset_name == "Medical Data":
        df = medical_df
        label = "medical_data.csv"
    else:
        df = kpi_df
        label = "sport_specific_kpis.csv"

    if df is None:
        st.error(f"File for **{dataset_name}** not found.")
        st.stop()

    cols = st.columns(3)
    cols[0].metric("Rows", f"{len(df):,}")
    cols[1].metric("Columns", f"{len(df.columns):,}")
    cols[2].metric("Label", label)

    filter_cols = st.columns(3)

    if "Age Group(s)" in df.columns:
        age_value = filter_cols[0].selectbox(
            "Age group filter",
            ["All"] + sorted(df["Age Group(s)"].dropna().unique().tolist())
        )
        if age_value != "All":
            df = df[df["Age Group(s)"] == age_value]

    # Gender filter (Inclusive logic)
    if "Gender" in df.columns:
        gender_value = filter_cols[1].selectbox("Gender filter", ["All", "M", "F", "M/F"], index=0)
        df = apply_inclusive_gender_filter(df, "Gender", gender_value)

    if "Sport" in df.columns:
        sport_value = filter_cols[2].selectbox(
            "Sport filter",
            ["All"] + sorted(df["Sport"].dropna().unique().tolist())
        )
        if sport_value != "All":
            df = df[df["Sport"] == sport_value]

    st.markdown("#### Data preview")
    st.dataframe(df, use_container_width=True)

    with st.expander("Summary (numeric columns)"):
        st.write(df.describe(include="all"))

# =========================
# PAGE: MODEL
# =========================
elif page == "Model":
    st.title("ASABIG Model – From Raw Data to Decisions")
    section_title("Pipeline")
    st.markdown("`Testing → Data Capture → Cleaning → Benchmarks → Scorecards → Dashboards → Decisions`")

# =========================
# PAGE: ATHLETES (DEMO LIST)
# =========================
elif page == "Athletes (Demo List)":
    st.title("Athletes – Demo Data (CSV)")
    if athletes_df is None:
        st.error("athletes.csv not found.")
        st.stop()
    st.dataframe(athletes_df, use_container_width=True)

# =========================
# PAGE: ATHLETE PROFILE
# =========================
elif page == "Athlete Profile":
    st.title("Athlete Profile – Demo (CSV)")
    if athletes_df is None:
        st.error("athletes.csv not found.")
        st.stop()

    display_col = "full_name" if "full_name" in athletes_df.columns else athletes_df.columns[0]
    athlete_name = st.selectbox("Select athlete (demo):", athletes_df[display_col].tolist())
    row = athletes_df[athletes_df[display_col] == athlete_name].iloc[0]
    st.json(row.to_dict())

# =========================
# PAGE: ATHLETE COMPARISON (UP TO 6)
# =========================
elif page == "Athlete Comparison":
    st.title("Athlete Comparison – Side by Side (Demo CSV)")
    if athletes_df is None:
        st.error("athletes.csv not found.")
        st.stop()

    display_col = "full_name" if "full_name" in athletes_df.columns else athletes_df.columns[0]

    MAX_COMPARE = 6
    selected_names = st.multiselect(
        f"Select up to {MAX_COMPARE} athletes to compare:",
        athletes_df[display_col].tolist(),
    )
    if len(selected_names) > MAX_COMPARE:
        st.warning(f"Showing first {MAX_COMPARE} athletes only.")
        selected_names = selected_names[:MAX_COMPARE]

    if not selected_names:
        st.info("Select athletes to compare.")
        st.stop()

    comp_df = athletes_df[athletes_df[display_col].isin(selected_names)].copy()
    st.dataframe(comp_df, use_container_width=True)

# =========================
# PAGE: ABOUT / GOVERNANCE
# =========================
elif page == "About / Governance":
    st.title("About ASABIG – Governance & Data Protection")
    st.markdown(
        """
- Role-based access (Player / Parent / Scout / Academy / Admin)  
- Parental consent tracking  
- Medical documents flagged as Pending/Approved/Rejected  
        """
    )
