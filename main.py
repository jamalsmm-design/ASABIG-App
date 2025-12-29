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
    except Exception:
        # try latin-1 fallback
        return pd.read_csv(path, encoding="latin-1")


generic_df = load_csv("generic_talent_data")
field_df = load_csv("field_tests")
medical_df = load_csv("medical_data")
sport_df = load_csv("sport_specific_kpis")
athletes_df = load_csv("athletes")
athlete_tests_df = load_csv("athlete_tests")

# =========================
# Helper UI functions
# =========================
def section_title(text: str):
    st.markdown(f"### {text}")


def small_note(text: str):
    st.caption(text)


# =========================
# SAFETY: make DataFrames Arrow-compatible for st.dataframe
# (Fixes pyarrow / ArrowInvalid conversion errors)
# =========================
def safe_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make dataframe safe for Streamlit display (Arrow-compatible).
    - Converts list/dict columns to string
    - Tries to normalize mixed-type object columns safely
    """
    if df is None:
        return df

    if not isinstance(df, pd.DataFrame):
        return pd.DataFrame(df)

    if df.empty:
        return df

    out = df.copy()

    for col in out.columns:
        try:
            # Convert list/dict-like cells to string
            if out[col].apply(lambda x: isinstance(x, (list, dict))).any():
                out[col] = out[col].astype(str)

            # If object dtype, avoid mixed types causing Arrow conversion errors
            if out[col].dtype == "object":
                # Keep NaN as-is but convert non-scalar weird values to string
                out[col] = out[col].apply(
                    lambda x: x
                    if (pd.isna(x) or isinstance(x, (str, int, float, bool)))
                    else str(x)
                )
        except Exception:
            # Last resort: stringify the whole column
            out[col] = out[col].astype(str)

    return out


# =========================
# Sidebar / Navigation
# =========================
st.sidebar.title("ASABIG –\nNavigation")

page = st.sidebar.radio(
    "Choose page:",
    ["Home", "Benchmarks & Data", "Model", "Athletes (Demo List)", "Athlete Profile", "Athlete Comparison", "About / Governance"],
)

st.sidebar.markdown("---")
st.sidebar.subheader("Data files status:")

for k, v in DATA_FILES.items():
    p = BASE_DIR / v
    if p.exists():
        st.sidebar.success(v)
    else:
        st.sidebar.error(f"{v} (missing)")


# =========================
# PAGE: HOME
# =========================
if page == "Home":
    st.title("ASABIG – Talent Identification Platform (Pilot Demo)")
    st.write(
        "ASABIG is a data-driven talent identification platform for youth (7–23 years), "
        "serving the Ministry of Sport, federations, clubs, and academies in Saudi Arabia."
    )

    section_title("What does ASABIG cover?")
    st.markdown(
        """
- 20+ sports (team, individual, combat, racket, eSports)  
- M/F athletes from 7–23 years  
- Integrated view of:
  - Generic growth & maturation
  - Field performance tests
  - Medical & safety gates
  - Sport-specific KPIs
        """
    )

    section_title("Why it matters (for Saudi Arabia)?")
    st.markdown(
        """
- Aligns with Saudi Vision 2030 – Sports & Quality of Life  
- Reduces random selection and late discovery of talent  
- Creates a national standard for tests, thresholds, and reporting  
- Supports federations, clubs, schools, and private academies  
        """
    )

    st.markdown("### الهدف (بالعربي)")
    st.markdown(
        """
- مشروع وطني يرفع جودة اكتشاف الموهبة بشكل مبكر  
- يعطي المدرب والأكاديمية رؤية رقمية 360 لملف اللاعب  
- يخدم وزارة الرياضة والاتحادات عبر بيانات موحدة وتقارير رقمية  
        """
    )

    st.info(
        "This is a pilot demo running locally on your laptop. All athlete examples are synthetic – no real player data is used."
    )


# =========================
# PAGE: BENCHMARKS & DATA
# =========================
elif page == "Benchmarks & Data":
    st.title("Benchmarks & Data – ASABIG Pilot Demo")

    datasets = {
        "Generic Talent Data": generic_df,
        "Field Tests": field_df,
        "Medical Data": medical_df,
        "Sport Specific KPIs": sport_df,
    }

    dataset_name = st.selectbox("Choose dataset:", list(datasets.keys()))
    df = datasets[dataset_name]

    if df is None:
        st.error("Dataset not found (CSV missing).")
    else:
        st.write(f"Rows: {len(df)}")
        st.write(f"Columns: {len(df.columns)}")
        st.write("Label")
        st.subheader(DATA_FILES[list(datasets.keys()).index(dataset_name)] if dataset_name in datasets else "dataset.csv")

        # Filters
        filter_cols = st.columns(3)

        if "Age Group(s)" in df.columns:
            age_value = filter_cols[0].selectbox(
                "Age group filter", ["All"] + sorted(df["Age Group(s)"].dropna().unique().tolist())
            )
            if age_value != "All":
                df = df[df["Age Group(s)"] == age_value]

        if "Gender" in df.columns:
            # Force consistent gender options + special rule:
            # - If user selects "M" -> show rows where Gender is "M" OR "M/F"
            # - If user selects "F" -> show rows where Gender is "F" OR "M/F"
            # - If user selects "M/F" -> show only "M/F"
            gender_options = ["All", "M", "F", "M/F"]
            gender_value = filter_cols[1].selectbox("Gender filter", gender_options)
            if gender_value != "All":
                if gender_value == "M":
                    df = df[df["Gender"].isin(["M", "M/F"])]
                elif gender_value == "F":
                    df = df[df["Gender"].isin(["F", "M/F"])]
                else:  # "M/F"
                    df = df[df["Gender"] == "M/F"]

        if "Sport" in df.columns:
            sport_value = filter_cols[2].selectbox(
                "Sport filter", ["All"] + sorted(df["Sport"].dropna().unique().tolist())
            )
            if sport_value != "All":
                df = df[df["Sport"] == sport_value]

        st.subheader("Data preview")
        st.dataframe(safe_df(df), use_container_width=True)

        with st.expander("Summary (numeric columns)"):
            st.write(df.describe(include="all"))


# =========================
# PAGE: MODEL
# =========================
elif page == "Model":
    st.title("ASABIG Model – From Raw Data to Decisions")

    section_title("1. Data inputs")
    st.markdown(
        """
- **Growth & maturation**: standing height, sitting height, body mass, BMI, PHV, etc.  
- **Field performance**: sprint tests, agility, jumps, endurance, sport-specific skills.  
- **Medical & safety**: injury history, ECG flags, asthma, concussion risk.  
- **Context**: training age, position, competition level.
        """
    )

    section_title("2. Standardization & Quality")
    st.markdown(
        """
- Unified definitions + measurement methods  
- Benchmarks by age group and sex  
- Quality checks: outliers, missing values, implausible growth patterns
        """
    )

    section_title("3. Scoring & Decision layer (pilot)")
    st.markdown(
        """
- Convert tests into percentile vs age/sex benchmarks  
- Produce a simple **Talent Readiness Score**  
- Flag medical risks (red/amber/green)  
- Output: short report for coach + parent + scout (role-based)
        """
    )


# =========================
# PAGE: ATHLETES (LIST)
# =========================
elif page == "Athletes (Demo List)":
    st.title("Athletes – Demo List")

    if athletes_df is None:
        st.error("athletes.csv not found.")
    else:
        st.dataframe(safe_df(athletes_df), use_container_width=True)


# =========================
# PAGE: ATHLETE PROFILE
# =========================
elif page == "Athlete Profile":
    st.title("Athlete Profile (Demo)")

    if athletes_df is None:
        st.error("athletes.csv not found.")
    else:
        display_col = "full_name" if "full_name" in athletes_df.columns else athletes_df.columns[0]
        athlete_name = st.selectbox("Select athlete (demo):", athletes_df[display_col].astype(str).tolist())

        row = athletes_df[athletes_df[display_col].astype(str) == str(athlete_name)].iloc[0]
        st.json(row.to_dict())


# =========================
# PAGE: ATHLETE COMPARISON (UP TO 6)
# =========================
elif page == "Athlete Comparison":
    st.title("Athlete Comparison – Side by Side (Demo)")

    if athletes_df is None:
        st.error("athletes.csv not found.")
    else:
        display_col = "full_name" if "full_name" in athletes_df.columns else athletes_df.columns[0]

        selected_names = st.multiselect(
            "Select up to 6 athletes to compare:",
            athletes_df[display_col].tolist(),
        )

        if not selected_names:
            st.info("اختر لاعب أو أكثر من القائمة للمقارنة.")
        else:
            if len(selected_names) > 6:
                st.warning("سيتم عرض أول ستة لاعبين فقط.")
                selected_names = selected_names[:6]

            df_selected = athletes_df[athletes_df[display_col].isin(selected_names)].copy()
            st.subheader("Athletes (Basic Info)")
            st.dataframe(safe_df(df_selected), use_container_width=True)

            if athlete_tests_df is not None and "full_name" in athlete_tests_df.columns:
                df_tests = athlete_tests_df[athlete_tests_df["full_name"].isin(selected_names)].copy()

                st.subheader("Athlete Tests (if available)")
                st.dataframe(safe_df(df_tests), use_container_width=True)

                # Simple chart demo: pick a numeric metric if available
                numeric_cols = df_tests.select_dtypes(include="number").columns.tolist()
                if numeric_cols:
                    metric_col = st.selectbox("Select numeric test metric to chart:", numeric_cols)
                    st.line_chart(df_tests.set_index("full_name")[metric_col], use_container_width=True)
                else:
                    small_note("لا توجد أعمدة رقمية واضحة في athlete_tests.csv لعمل مخطط بسيط.")


# =========================
# PAGE: ABOUT / GOVERNANCE
# =========================
elif page == "About / Governance":
    st.title("About ASABIG – Governance & Data Protection")

    section_title("Data ownership & roles")
    st.markdown(
        """
- **Athletes & guardians**: own their personal data.  
- **Institutions (clubs, academies, federations)**: act as custodians and operators.  
- **Scouts & talent directors**: limited access by role and consent.  
- **Ministry / federations**: aggregated analytics and national dashboards.
        """
    )

    section_title("Privacy & compliance principles")
    st.markdown(
        """
- PDPL-aligned data handling (Saudi Personal Data Protection Law).  
- Consent-first for minors, guardian approval required.  
- Data minimization: collect only what’s needed for sports performance & safety.  
- Security: encryption, audit logs, role-based access.  
        """
    )

    section_title("Future: registration, dashboards, uploads (planned)")
    st.markdown(
        """
✅ نعم نقدر نضيف في Streamlit (Pilot) بشكل تدريجي:
- تسجيل دخول (Player / Parent / Scout / Academy)  
- لوحة لكل دور + صلاحيات  
- إدخال بيانات اللاعب + سجل تدريبات  
- رفع PDF للفحوصات الطبية + صور + فيديوهات  
- تفضيلات اللاعب + الأهداف + الإشعارات  
لكن هذا يحتاج توسعة مع قاعدة بيانات/تخزين ملفات (مثل SQLite + Storage)  
        """
    )

    st.markdown("---")
    st.subheader("Next Steps (Implementation Roadmap)")
    st.markdown(
        """
1. Connect with real partners (academies, clubs).  
2. Move from CSV demo to secure DB + file storage.  
3. Add registration + role dashboards + uploads.  
4. Add analytics: trends, percentile scoring, risk flags.  
        """
    )
