import streamlit as st
import pandas as pd
from pathlib import Path

# =========================
# Basic page setup
# =========================
st.set_page_config(
    page_title="ASABIG Talent Platform – Pilot Demo",
    layout="wide",
)

# =========================
# Paths & data loading
# =========================
BASE_DIR = Path(__file__).parent

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
    except Exception as e:
        st.warning(f"⚠️ Error loading **{filename}**: {e}")
        return None


# Load all datasets once
dfs = {k: load_csv(k) for k in DATA_FILES.keys()}

# =========================
# Sidebar – Navigation
# =========================
st.sidebar.title("ASABIG – Navigation")
page = st.sidebar.radio(
    "اختر الصفحة / Choose page:",
    [
        "Home",
        "Benchmarks & Data",
        "Model",
        "Athletes (Demo List)",
        "Athlete Profile",
        "Athlete Comparison",
        "About / Governance",
    ],
)

st.sidebar.markdown("---")
st.sidebar.subheader("Data files status:")

for key, filename in DATA_FILES.items():
    df = dfs.get(key)
    nice_name = filename
    if df is not None:
        st.sidebar.success(nice_name)
    else:
        st.sidebar.error(nice_name)

# Convenience shortcuts
generic_df = dfs["generic_talent_data"]
field_df = dfs["field_tests"]
medical_df = dfs["medical_data"]
kpi_df = dfs["sport_specific_kpis"]
athletes_df = dfs["athletes"]
athlete_tests_df = dfs["athlete_tests"]


# =========================
# Helper functions
# =========================
def section_title(text: str):
    st.markdown(f"### {text}")


def small_note(text: str):
    st.caption(text)


def df_summary_box(df: pd.DataFrame, label: str):
    cols = st.columns(3)
    cols[0].metric("Rows", f"{len(df):,}")
    cols[1].metric("Columns", f"{len(df.columns):,}")
    cols[2].metric("Label", label)


# =========================
# PAGE: HOME
# =========================
if page == "Home":
    st.title("ASABIG – Talent Identification Platform (Pilot Demo)")

    st.markdown(
        """
ASABIG is a **data-driven talent identification platform** for youth (7–23 years),
serving the Ministry of Sport, federations, clubs, and academies in Saudi Arabia.
"""
    )

    section_title("What does ASABIG cover?")
    st.markdown(
        """
- **20+ sports** (team, individual, combat, racket, eSports)
- **M/F athletes** from **7–23 years**
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
- Aligns with **Saudi Vision 2030 – Sports & Quality of Life**
- Reduces **random selection** and **late discovery** of talent
- Creates a **national standard** for tests, thresholds, and reporting
- Supports federations, clubs, schools, and private academies
        """
    )

    section_title("الهدف (بالعربي):")
    st.markdown(
        """
- **تسريع بروز وتقييم المواهب الرياضية في المملكة**  
- إعطاء المدرب والأكاديمية والأب **صورة 360° واضحة** عن اللاعب  
- تقليل القرارات العشوائية، واستبدالها ببيانات واضحة ومؤشرات رقمية  
        """
    )

    st.markdown("---")
    st.info(
        "🔬 **This is a pilot demo running locally on your laptop.** "
        "All athlete examples are synthetic – no real player data is used."
    )

    small_note("للاستخدام في العرض فقط – يمكن تعديل النصوص حسب الجمهور المستهدف.")


# =========================
# PAGE: BENCHMARKS & DATA
# =========================
elif page == "Benchmarks & Data":
    st.title("Benchmarks & Data – ASABIG Pilot Demo")

    dataset_name = st.selectbox(
        "Choose dataset:",
        [
            "Generic Talent Data",
            "Field Tests",
            "Medical Data",
            "Sport-Specific KPIs",
        ],
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
    else:
        df_summary_box(df, label)

        # Simple filters (if columns exist)
        filter_cols = st.columns(3)

        if "Age Group(s)" in df.columns:
            age_value = filter_cols[0].selectbox(
                "Age group filter", ["All"] + sorted(df["Age Group(s)"].dropna().unique().tolist())
            )
            if age_value != "All":
                df = df[df["Age Group(s)"] == age_value]

        if "Gender" in df.columns:
            gender_value = filter_cols[1].selectbox(
                "Gender filter", ["All"] + sorted(df["Gender"].dropna().unique().tolist())
            )
            if gender_value != "All":
                df = df[df["Gender"] == gender_value]

        if "Sport" in df.columns:
            sport_value = filter_cols[2].selectbox(
                "Sport filter", ["All"] + sorted(df["Sport"].dropna().unique().tolist())
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

    section_title("1. Data inputs")
    st.markdown(
        """
- **Growth & maturation**: standing height, sitting height, body mass, BMI, PHV, etc.  
- **Field performance**: sprint tests, agility, jumps, endurance, sport-specific skills.  
- **Medical & safety**: red-flags, clearance to train/compete, return-to-play.  
- **Context**: years of sport, training age, club/academy, preferred role/position.
        """
    )

    section_title("2. Processing")
    st.markdown(
        """
- Standardizes tests across clubs and academies.  
- Compares athletes to **age- and sex-specific benchmarks**.  
- Flags **early / late maturers** to avoid unfair comparison.  
- Builds a **talent profile** per athlete and per sport.
        """
    )

    section_title("3. Outputs")
    st.markdown(
        """
- **Coach dashboard**: strengths, gaps, and training priorities.  
- **Federation dashboard**: national depth charts and pipeline visibility.  
- **Parents & athletes**: simple, visual reports (no complex jargon).  
        """
    )

    st.markdown("---")
    st.subheader("Simplified pipeline")
    st.markdown(
        """
`Testing → Data Capture → Cleaning & Standardisation → Benchmarks →  
Talent Scorecards → Dashboards & Alerts → Decisions (Selection / Development Plan)`
        """
    )

    small_note("يمكن لاحقاً إضافة رسومات توضيحية (flowchart) أو أيقونات بسيطة.")


# =========================
# PAGE: ATHLETES (DEMO LIST)
# =========================
elif page == "Athletes (Demo List)":
    st.title("Athletes – Demo Data (Synthetic)")

    if athletes_df is None:
        st.error("athletes.csv not found.")
    else:
        df = athletes_df.copy()

        # Basic filters
        cols = st.columns(3)

        if "sport" in df.columns:
            sport = cols[0].selectbox(
                "Sport", ["All"] + sorted(df["sport"].dropna().unique().tolist())
            )
            if sport != "All":
                df = df[df["sport"] == sport]

        if "club" in df.columns:
            club = cols[1].selectbox(
                "Club / Academy", ["All"] + sorted(df["club"].dropna().unique().tolist())
            )
            if club != "All":
                df = df[df["club"] == club]

        if "gender" in df.columns:
            gender = cols[2].selectbox(
                "Gender", ["All"] + sorted(df["gender"].dropna().unique().tolist())
            )
            if gender != "All":
                df = df[df["gender"] == gender]

        st.markdown("#### Athlete list")
        st.dataframe(df, use_container_width=True)

        small_note("كل الأسماء والمعلومات هنا تجريبية (ليست لاعبين حقيقيين).")


# =========================
# PAGE: ATHLETE PROFILE
# =========================
elif page == "Athlete Profile":
    st.title("Athlete Profile – 360° View (Demo)")

    if athletes_df is None:
        st.error("athletes.csv not found.")
    else:
        # Choose athlete
        if "full_name" in athletes_df.columns:
            display_col = "full_name"
        else:
            # fallback: first column
            display_col = athletes_df.columns[0]

        athlete_name = st.selectbox(
            "Select athlete (demo):",
            athletes_df[display_col].tolist(),
        )

        athlete_row = athletes_df[athletes_df[display_col] == athlete_name].iloc[0]

        cols = st.columns(3)
        if "sport" in athletes_df.columns:
            cols[0].metric("Sport", str(athlete_row.get("sport", "-")))
        if "club" in athletes_df.columns:
            cols[1].metric("Club / Academy", str(athlete_row.get("club", "-")))
        if "city" in athletes_df.columns:
            cols[2].metric("City", str(athlete_row.get("city", "-")))

        cols2 = st.columns(3)
        if "gender" in athletes_df.columns:
            cols2[0].metric("Gender", str(athlete_row.get("gender", "-")))
        if "birth_year" in athletes_df.columns:
            cols2[1].metric("Birth year", str(athlete_row.get("birth_year", "-")))
        if "dominant_side" in athletes_df.columns:
            cols2[2].metric("Dominant side", str(athlete_row.get("dominant_side", "-")))

        st.markdown("---")
        section_title("Field & lab tests (from athlete_tests.csv)")

        if athlete_tests_df is None:
            st.info("No athlete_tests.csv file found yet – this section is just a placeholder.")
        else:
            df_tests = athlete_tests_df.copy()

            # Prefer to match by athlete_id if present
            if "athlete_id" in df_tests.columns and "athlete_id" in athletes_df.columns:
                aid = athlete_row.get("athlete_id")
                df_tests = df_tests[df_tests["athlete_id"] == aid]
            else:
                # fallback attempt: match by name if column exists
                name_cols = [c for c in df_tests.columns if "name" in c.lower()]
                if name_cols:
                    nc = name_cols[0]
                    df_tests = df_tests[df_tests[nc] == athlete_name]

            if df_tests.empty:
                st.info(
                    "No linked test records found for this athlete in **athlete_tests.csv**. "
                    "يمكن لاحقاً ربط الاختبارات باستخدام athlete_id أو الاسم."
                )
            else:
                st.dataframe(df_tests, use_container_width=True)

                # Simple chart if numeric
                numeric_cols = df_tests.select_dtypes("number").columns.tolist()
                if numeric_cols:
                    metric_col = st.selectbox(
                        "Select metric to plot", numeric_cols, key="metric_select_profile"
                    )
                    st.line_chart(df_tests[metric_col], use_container_width=True)


# =========================
# PAGE: ATHLETE COMPARISON
# =========================
elif page == "Athlete Comparison":
    st.title("Athlete Comparison – Side by Side (Demo)")

    if athletes_df is None:
        st.error("athletes.csv not found.")
    else:
        if "full_name" in athletes_df.columns:
            display_col = "full_name"
        else:
            display_col = athletes_df.columns[0]

        selected_names = st.multiselect(
            "Select up to 4 athletes to compare:",
            athletes_df[display_col].tolist(),
        )

        if not selected_names:
            st.info("اختر لاعب أو أكثر من القائمة للمقارنة.")
        else:
            if len(selected_names) > 4:
                st.warning("سيتم عرض أول أربعة لاعبين فقط.")
                selected_names = selected_names[:4]

            comp_df = athletes_df[athletes_df[display_col].isin(selected_names)].copy()
            st.dataframe(comp_df, use_container_width=True)

            if athlete_tests_df is not None and "athlete_id" in athlete_tests_df.columns and "athlete_id" in athletes_df.columns:
                st.markdown("#### Simple test comparison (demo)")
                # pick first numeric column if exists
                numeric_cols = athlete_tests_df.select_dtypes("number").columns.tolist()
                if numeric_cols:
                    metric_col = st.selectbox(
                        "Metric from athlete_tests.csv",
                        numeric_cols,
                        key="metric_select_comp",
                    )
                    merged = athlete_tests_df.merge(
                        athletes_df[[ "athlete_id", display_col ]],
                        on="athlete_id",
                        how="left",
                    )
                    merged = merged[merged[display_col].isin(selected_names)]
                    pivot = merged.pivot_table(
                        index=display_col,
                        values=metric_col,
                        aggfunc="mean",
                    )
                    st.bar_chart(pivot, use_container_width=True)
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
- **Platform (ASABIG)**: provides tools, analytics, and secure data infrastructure.
        """
    )

    section_title("Access control")
    st.markdown(
        """
- **Coach view**: teams, tests, training reports.  
- **Medical view**: clearance, red-flags, return-to-play notes.  
- **Federation view**: aggregated talent pipeline (no personal identifiers).  
        """
    )

    section_title("Privacy & safety")
    st.markdown(
        """
- No social media style exposure of youth players.  
- All reports are **role-based** and **need-to-know**.  
- Parents/guardians can request **access, correction, or deletion** of their child’s data.  
        """
    )

    st.markdown("---")
    st.subheader("Next Steps (Implementation Roadmap)")
    st.markdown(
        """
1. **Connect ASABIG** with real partners:  
   - Academies, clubs, school sports programs.  

2. **Move from local CSV demo** to:  
   - Centralised database.  
   - Secure cloud / on-prem hosting (as required).  
   - API integration with existing systems.  

3. **Add dashboards & alerts**:  
   - Coach & federation dashboards.  
   - Automated reports per athlete.  
   - Smart alerts for risk (injury, overload, dropout).  
        """
    )

    st.markdown("---")
    st.subheader("ملاحظة ختامية (بالعربي):")
    st.markdown(
        """
هذه النسخة **تجريبية محلية**، توضح فكرة المنصّة وكيف يمكن أن تتحوّل لاحقاً  
إلى نظام وطني متكامل لاكتشاف وتطوير المواهب الرياضية في المملكة 🌱🇸🇦.
        """
    )

    small_note("يمكن تعديل النصوص بالكامل حسب الجهة: وزارة الرياضة، اتحاد، مستثمر،…")
