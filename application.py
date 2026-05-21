import streamlit as st

st.set_page_config(
    page_title="Incident Intelligence Dashboard",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from supabase import create_client          # ← direct client so we can paginate
from utils.charts import (
    render_incidents_by_category,
    render_incidents_by_type,
    render_incidents_by_country,
    render_impact_distribution,
    render_timeline,
    render_wordcloud,
    render_source_breakdown,
)
from utils.chatbot import chatbot_ui
from utils.risk_scorer import score_dataframe, compute_impact_score

TZ_MY = ZoneInfo("Asia/Kuala_Lumpur")
def now_my(): return datetime.now(tz=TZ_MY)


# ══════════════════════════════════════════════════════════════════════════════
#  SUPABASE — paginated fetch (replaces get_data so ALL rows are returned)
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def _supabase():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


def get_data(table: str) -> pd.DataFrame:
    """Fetch every row from *table* using 1 000-row pages."""
    client   = _supabase()
    all_rows = []
    page     = 0
    page_size = 1000

    while True:
        start = page * page_size
        end   = start + page_size - 1
        try:
            resp = client.table(table).select("*").range(start, end).execute()
        except Exception as e:
            st.error(f"Supabase error fetching {table}: {e}")
            break

        batch = resp.data or []
        all_rows.extend(batch)

        if len(batch) < page_size:   # last page
            break
        page += 1

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)

    # ── column normalisation for incidents ───────────────────────────────────
    # Your DB uses "publication_date"; charts expect "incident_date".
    # Also derive "country" / "category" / "impact" if missing.
    if table == "incidents":
        # date alias
        if "incident_date" not in df.columns and "publication_date" in df.columns:
            df["incident_date"] = df["publication_date"]

        # country  — try common column names, else "Unknown"
        if "country" not in df.columns:
            for alt in ("nation", "location", "geo", "region"):
                if alt in df.columns:
                    df["country"] = df[alt]
                    break
            else:
                df["country"] = "Unknown"

        # category — try common alternatives, else "Uncategorised"
        if "category" not in df.columns:
            for alt in ("type", "threat_type", "incident_category"):
                if alt in df.columns:
                    df["category"] = df[alt]
                    break
            else:
                df["category"] = "Uncategorised"

        # incident_type alias
        if "incident_type" not in df.columns:
            for alt in ("type", "attack_type", "threat_type"):
                if alt in df.columns:
                    df["incident_type"] = df[alt]
                    break
            else:
                df["incident_type"] = df.get("category", "Unknown")

        # impact — try common alternatives, else "Unknown"
        # Note: do NOT use "severity" as fallback here — severity is its own column
        # and is read directly in render_intel_feed.
        if "impact" not in df.columns:
            for alt in ("criticality", "priority"):
                if alt in df.columns:
                    df["impact"] = df[alt]
                    break
            else:
                df["impact"] = "Unknown"

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  CSS
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body { font-family: 'IBM Plex Sans', sans-serif; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0a0d13 !important;
    border-right: 1px solid #1a1f2e !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 0 !important; }
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label { color: #8b949e !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: #f0f6fc !important; }

/* ── Top nav bar ── */
[data-testid="stTopNavigation"] {
    background: #0d1117 !important;
    border-bottom: 1px solid #21262d !important;
}
[data-testid="stTopNavigation"] a { color: #8b949e !important; font-size: 13px !important; }
[data-testid="stTopNavigation"] a[aria-current="page"] {
    color: #f0f6fc !important;
    border-bottom: 2px solid #388bfd !important;
}

/* ── Page header ── */
.dash-header {
    background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
    border: 1px solid #21262d; border-radius: 12px;
    padding: 20px 28px; margin-bottom: 22px;
    display: flex; align-items: center; justify-content: space-between;
}
.dash-title    { font-size: 22px; font-weight: 600; color: #f0f6fc; letter-spacing: -0.3px; }
.dash-subtitle { font-size: 12.5px; color: #8b949e; margin-top: 3px; }
.dash-live     { font-size: 11.5px; color: #3fb950; font-family:'IBM Plex Mono',monospace; }
.live-dot {
    display: inline-block; width: 7px; height: 7px;
    background: #3fb950; border-radius: 50%; margin-right: 5px;
    animation: blink 2s infinite; vertical-align: middle;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.25} }

/* ── KPI cards ── */
.kpi-card {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 18px 20px; text-align: center; transition: border-color .2s;
}
.kpi-card:hover { border-color: #388bfd; }
.kpi-number { font-size: 36px; font-weight: 600; color: #f0f6fc; font-family:'IBM Plex Mono',monospace; line-height: 1; }
.kpi-label  { font-size: 12px; color: #8b949e; margin-top: 6px; text-transform: uppercase; letter-spacing: .08em; }
.kpi-delta  { font-size: 12px; margin-top: 6px; font-family:'IBM Plex Mono',monospace; }
.kpi-up   { color: #3fb950; }
.kpi-warn { color: #f78166; }

/* ── Section headers ── */
.section-header {
    font-size: 13px; font-weight: 500; color: #8b949e;
    text-transform: uppercase; letter-spacing: .1em;
    margin: 24px 0 12px; border-bottom: 1px solid #21262d; padding-bottom: 8px;
}

/* ── Victim cards ── */
.victim-card {
    background: #161b22; border: 1px solid #21262d;
    border-left: 3px solid #f78166; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 10px;
}
.victim-name  { font-size: 15px; font-weight: 600; color: #f0f6fc; }
.victim-meta  { font-size: 12px; color: #8b949e; margin-top: 4px; font-family:'IBM Plex Mono',monospace; }
.victim-badge {
    display: inline-block; font-size: 11px; font-family:'IBM Plex Mono',monospace;
    padding: 2px 8px; border-radius: 4px; margin-top: 6px; font-weight: 600;
}
.sev-critical { background:#3d0f0f; color:#ff6b6b; }
.sev-high     { background:#2d1b0a; color:#ffa94d; }
.sev-medium   { background:#1e2a0a; color:#a9d64b; }
.sev-low      { background:#0a1f2a; color:#4fc3f7; }

/* ── Chat hero ── */
.chat-hero {
    background: linear-gradient(135deg,#0d1117 0%,#161b22 60%,#1a2332 100%);
    border: 1px solid #21262d; border-radius: 14px;
    padding: 36px; margin-bottom: 24px; text-align: center;
}
.chat-hero-title { font-size: 26px; font-weight: 600; color: #f0f6fc; margin-top: 10px; }
.chat-hero-sub   { font-size: 14px; color: #8b949e; margin-top: 6px; }

/* ── Intel feed cards ── */
.intel-feed-card {
    background: #161b22; border: 1px solid #21262d;
    border-radius: 10px; padding: 14px 18px;
    margin-bottom: 10px; position: relative;
    overflow: hidden; transition: border-color .2s;
}
.intel-feed-card:hover { border-color: #388bfd; }
.intel-accent { position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
.accent-critical { background: #ff6b6b; }
.accent-high     { background: #ffa94d; }
.accent-medium   { background: #4fc3f7; }
.accent-low      { background: #3fb950; }
.intel-top {
    display: flex; align-items: center; gap: 7px;
    flex-wrap: wrap; margin-bottom: 7px;
}
.intel-badge {
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600;
    letter-spacing: .07em; padding: 3px 9px; border-radius: 100px; text-transform: uppercase;
}
.ibadge-critical { background: #3d0f0f; color: #ff6b6b; }
.ibadge-high     { background: #2d1b0a; color: #ffa94d; }
.ibadge-medium   { background: #0a1f2a; color: #4fc3f7; }
.ibadge-low      { background: #0a1f17; color: #3fb950; }
.ibadge-unknown  { background: #1c1c1c; color: #8b949e; }
.intel-cat {
    font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 500;
    padding: 2px 9px; border-radius: 100px; border: 1px solid #21262d;
    color: #8b949e; text-transform: uppercase; letter-spacing: .06em;
}
.intel-hot {
    background: #ff6b6b; color: #fff;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 700;
    padding: 3px 9px; border-radius: 100px; letter-spacing: .1em; text-transform: uppercase;
    animation: blink 1.8s ease-in-out infinite;
}
.intel-title   { font-size: 16px; font-weight: 600; color: #f0f6fc; line-height: 1.45; margin-bottom: 6px; }
.intel-summary { font-size: 14px; color: #c9d1d9; line-height: 1.6; margin-bottom: 10px; }
.intel-footer  {
    display: flex; align-items: center;
    justify-content: space-between; flex-wrap: wrap; gap: 6px;
}
.intel-source {
    font-family: 'IBM Plex Mono', monospace; font-size: 12.5px;
    color: #6e7681; display: flex; align-items: center; gap: 5px;
}
.intel-source-dot { width: 5px; height: 5px; border-radius: 50%; background: #21262d; flex-shrink: 0; }
.intel-time { font-family: 'IBM Plex Mono', monospace; font-size: 12.5px; color: #6e7681; }

hr { border-color: #21262d !important; }
[data-testid="stMetric"] { background: transparent; }
.stPlotlyChart { border: 1px solid #21262d; border-radius: 10px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def page_header(title: str, subtitle: str):
    st.markdown(f"""
    <div class="dash-header">
        <div>
            <div class="dash-title">{title}</div>
            <div class="dash-subtitle">{subtitle}</div>
        </div>
        <div class="dash-live">
            <span class="live-dot"></span>
            {now_my().strftime('%d %b %Y, %H:%M:%S')} GMT+8
        </div>
    </div>
    """, unsafe_allow_html=True)


def kpi_row(specs: list):
    for col, val, label, delta, dtype in specs:
        val_str     = f"{val:,}" if isinstance(val, int) else str(val)
        num_size    = "24px" if isinstance(val, str) and len(val) > 6 else "36px"
        delta_class = f"kpi-{dtype}" if dtype else "kpi-label"
        col.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-number" style="font-size:{num_size}">{val_str}</div>
            <div class="kpi-label">{label}</div>
            <div class="kpi-delta {delta_class}">{delta}</div>
        </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED SIDEBAR COMPONENTS
# ══════════════════════════════════════════════════════════════════════════════
def _sidebar_branding():
    st.markdown(f"""
    <div style="padding:20px 4px 14px;border-bottom:1px solid #1a1f2e;margin-bottom:10px;">
        <div style="font-size:16px;font-weight:600;color:#f0f6fc;">🛡️ Incident Intel</div>
        <div style="font-size:11px;color:#484f58;font-family:'IBM Plex Mono',monospace;margin-top:3px;">
            <span class="live-dot"></span> LIVE · {now_my().strftime('%H:%M')} GMT+8
        </div>
    </div>
    """, unsafe_allow_html=True)


def _filter_label(text="Filters"):
    return (
        f"<div style='font-size:10px;font-weight:600;color:#484f58;"
        f"text-transform:uppercase;letter-spacing:.12em;"
        f"padding:12px 16px 4px;border-top:1px solid #1a1f2e;margin-top:10px;'>"
        f"{text}</div>"
    )


def _sidebar_footer():
    st.markdown("---")
    auto_refresh = st.toggle("Auto-refresh (60s)", value=False, key="auto_refresh")
    if auto_refresh:
        st.info("Auto-refresh enabled (refresh page manually every 60s)")
    st.markdown(
        "<div style='font-size:10.5px;color:#484f58;line-height:1.8;margin-top:6px;'>"
        "Data source: Supabase Postgres<br>"
        "Model: claude-sonnet-4-20250514<br>"
        "Feed: ransomware.live"
        "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  INTEL FEED RENDERER
# ══════════════════════════════════════════════════════════════════════════════
import re as _re

def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities, returning clean plain text."""
    text = str(text)
    text = _re.sub(r'<[^>]+>', '', text)   # strip all <tags>
    text = text.replace("&amp;",  "&")
    text = text.replace("&lt;",   "<")
    text = text.replace("&gt;",   ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;",  "'")
    text = text.replace("&nbsp;", " ")
    text = _re.sub(r'\s+', ' ', text)      # collapse extra whitespace
    return text.strip()


def render_intel_feed(df: pd.DataFrame, max_items: int = 20):
    """Render a live intelligence feed from the incidents DataFrame."""

    IMPACT_ACCENT = {
        "critical": "accent-critical",
        "high":     "accent-high",
        "medium":   "accent-medium",
        "low":      "accent-low",
    }
    IMPACT_BADGE = {
        "critical": "ibadge-critical",
        "high":     "ibadge-high",
        "medium":   "ibadge-medium",
        "low":      "ibadge-low",
    }

    # Resolve column names with safe fallbacks
    title_col          = next((c for c in ("title", "headline", "name")             if c in df.columns), None)
    summary_col        = next((c for c in ("summary", "description", "content")     if c in df.columns), None)
    source_col         = next((c for c in ("source", "origin", "feed")              if c in df.columns), None)
    impact_col         = next((c for c in ("impact", "criticality")                 if c in df.columns), None)
    severity_col       = next((c for c in ("severity",)                             if c in df.columns), None)
    incident_type_col  = next((c for c in ("incident_type", "type", "attack_type")  if c in df.columns), None)
    entity_col         = next((c for c in ("entity_affected", "entity", "target", "victim") if c in df.columns), None)
    date_col           = next((c for c in ("incident_date", "publication_date", "date") if c in df.columns), None)

    feed_df = df.copy()
    if date_col:
        feed_df = feed_df.sort_values(date_col, ascending=False)
    feed_df = feed_df.head(max_items)

    if feed_df.empty:
        st.info("No incidents match the current filters.")
        return

    now = now_my()

    for _, row in feed_df.iterrows():
        # Prefer the explicit 'severity' column; fall back to 'impact'
        sev_raw    = str(row.get(severity_col, "") if severity_col else "").strip().lower()
        impact_raw = str(row.get(impact_col,   "") if impact_col   else "").strip().lower()
        # Use severity if it's a recognised level, else try impact, else unknown
        impact_key = (
            sev_raw    if sev_raw    in IMPACT_BADGE else
            impact_raw if impact_raw in IMPACT_BADGE else
            "unknown"
        )
        accent_cls = IMPACT_ACCENT.get(impact_key, "accent-low")
        badge_cls  = IMPACT_BADGE.get(impact_key, "ibadge-unknown")
        impact_lbl = impact_key.capitalize()

        # ── top-row fields: incident_type + entity_affected ──────────────────
        inc_type = str(row.get(incident_type_col, "") if incident_type_col else "").strip()
        entity   = str(row.get(entity_col, "")        if entity_col        else "").strip()

        inc_type_html = (
            f'<span class="intel-cat">{inc_type}</span>' if inc_type and inc_type.lower() not in ("", "nan", "none") else ""
        )
        entity_html = (
            f'<span class="intel-cat" style="color:#c9d1d9;border-color:#388bfd;">{entity}</span>'
            if entity and entity.lower() not in ("", "nan", "none") else ""
        )

        title   = _strip_html(str(row.get(title_col,   "Untitled") if title_col   else "Untitled"))
        summary = _strip_html(str(row.get(summary_col, "")         if summary_col else ""))
        # Truncate at sentence boundary first, then word boundary — no mid-word cuts
        if len(summary) > 400:
            # Try to cut at last full sentence within 400 chars
            cut = summary[:400]
            last_period = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            if last_period > 150:
                summary = cut[:last_period + 1]
            else:
                # Fall back to last word boundary
                last_space = cut.rfind(" ")
                summary = cut[:last_space] + "…" if last_space > 0 else cut + "…"
        source  = _strip_html(str(row.get(source_col, "Unknown source") if source_col else "Unknown source"))

        # Relative time string
        time_str = ""
        if date_col and pd.notna(row.get(date_col)):
            delta = now - row[date_col]
            mins  = int(delta.total_seconds() / 60)
            if mins < 1:
                time_str = "just now"
            elif mins < 60:
                time_str = f"{mins} min ago"
            elif mins < 1440:
                time_str = f"{mins // 60} hr ago"
            else:
                days = mins // 1440
                time_str = f"{days} day{'s' if days > 1 else ''} ago"

        # HOT = critical or high AND posted within last 6 hours
        is_hot = (
            impact_key in ("critical", "high")
            and date_col
            and pd.notna(row.get(date_col))
            and (now - row[date_col]).total_seconds() < 21600
        )
        hot_html = '<span class="intel-hot">🔥 HOT</span>' if is_hot else ""

        severity_badge_html = f'<span class="intel-badge {badge_cls}">{impact_lbl}</span>'

        card_html = (
            f'<div class="intel-feed-card">'
            f'<div class="intel-accent {accent_cls}"></div>'
            f'<div style="padding-left:12px;">'
            f'<div class="intel-top">'
            f'{severity_badge_html}'
            f'{inc_type_html}'
            f'{entity_html}'
            f'{hot_html}'
            f'</div>'
            f'<div class="intel-title">{title}</div>'
            f'<div class="intel-summary">{summary}</div>'
            f'<div class="intel-footer">'
            f'<span class="intel-source"><span class="intel-source-dot"></span>{source}</span>'
            f'<span class="intel-time">{time_str}</span>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 1 — CYBER NEWS
# ══════════════════════════════════════════════════════════════════════════════
def page_cyber_news():
    # ── Load ALL incidents first (needed to populate filter options) ──────────
    @st.cache_data(ttl=120, show_spinner=False)
    def load_incidents():
        return get_data("incidents")   # ← paginated, returns ALL rows

    with st.spinner("Loading incidents…"):
        df_raw = load_incidents()

    if df_raw is None or df_raw.empty:
        st.error("⚠️ Could not load data from Supabase. Check your `.streamlit/secrets.toml`.")
        with st.sidebar:
            _sidebar_branding()
            _sidebar_footer()
        st.stop()

    # ── Parse dates ──────────────────────────────────────────────────────────
    df_all = df_raw.copy()
    for col in ("incident_date", "publication_date"):
        if col in df_all.columns:
            df_all[col] = pd.to_datetime(
                df_all[col], errors="coerce", utc=True
            ).dt.tz_convert(TZ_MY)

    # ── Sidebar (uses df_all for dynamic filter options) ─────────────────────
    with st.sidebar:
        _sidebar_branding()
        st.markdown(_filter_label(), unsafe_allow_html=True)

        min_date = df_all["incident_date"].dropna().min().date() \
                   if "incident_date" in df_all.columns and not df_all["incident_date"].isna().all() \
                   else date(2026, 1, 1)

        date_range = st.date_input(
            "Date range (GMT+8)",
            value=(min_date, now_my().date()),
            max_value=now_my().date(),
            key="news_date",
        )

        cat_opts     = sorted(df_all["category"].dropna().unique().tolist()) \
                       if "category" in df_all.columns else []
        country_opts = sorted(df_all["country"].dropna().unique().tolist()) \
                       if "country" in df_all.columns else []

        category_filter = st.multiselect("Category", options=cat_opts,
                                          placeholder="All categories", key="news_cat")
        country_filter  = st.multiselect("Country",  options=country_opts,
                                          placeholder="All countries",  key="news_ctry")
        impact_filter   = st.multiselect("Impact",
                                          options=["Critical","High","Medium","Low","Unknown"],
                                          placeholder="All impacts",    key="news_impact")

        _sidebar_footer()

    page_header("📰 Cyber News", "Threat intelligence · Incident feed · Real-time monitoring")

    # ── Apply filters ─────────────────────────────────────────────────────────
    df = df_all.copy()

    if len(date_range) == 2:
        s = pd.Timestamp(date_range[0], tz=TZ_MY)
        e = pd.Timestamp(date_range[1], tz=TZ_MY) + timedelta(days=1) - timedelta(seconds=1)
        if "incident_date" in df.columns:
            df = df[df["incident_date"].between(s, e, inclusive="both")]

    if category_filter and "category" in df.columns:
        df = df[df["category"].isin(category_filter)]
    if country_filter and "country" in df.columns:
        df = df[df["country"].isin(country_filter)]
    if impact_filter and "impact" in df.columns:
        df = df[df["impact"].isin(impact_filter)]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    total_incidents    = len(df)
    total_sources      = df["source"].nunique() if "source" in df.columns else 0
    critical_count     = len(df[df["impact"].str.lower() == "critical"]) \
                         if "impact" in df.columns else 0
    countries_affected = df.loc[
        df["country"].notna() & (df["country"] != "Unknown"), "country"
    ].nunique() if "country" in df.columns else 0

    new_this_week = len(
        df[df["incident_date"] >= (now_my() - timedelta(days=7))]
    ) if "incident_date" in df.columns else 0

    k1, k2, k3, k4, k5 = st.columns(5)
    kpi_row([
        (k1, total_incidents,    "Total Incidents",    f"+{new_this_week} this week", "up"),
        (k2, total_sources,      "Crawled Sources",    "Unique domains",              ""),
        (k3, critical_count,     "Critical Incidents", "Needs attention",             "warn" if critical_count else ""),
        (k4, countries_affected, "Countries Affected", "Unique nations",              ""),
        (k5, new_this_week,      "New This Week",      "Last 7 days",                 "up"),
    ])

    # ── Charts ────────────────────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Incident Overview</div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1: render_incidents_by_category(df)
    with c2: render_incidents_by_type(df)

    st.markdown("<div class='section-header'>Trends & Impact</div>", unsafe_allow_html=True)
    c3, c4 = st.columns([2, 1])
    with c3: render_timeline(df)
    with c4: render_impact_distribution(df)

    st.markdown("<div class='section-header'>Geography & Sources</div>", unsafe_allow_html=True)
    c5, c6 = st.columns([2, 1])
    with c5: render_incidents_by_country(df)
    with c6: render_source_breakdown(df)

    st.markdown("<div class='section-header'>Text Insights</div>", unsafe_allow_html=True)
    w1, w2 = st.columns(2)
    with w1: render_wordcloud(df, column="summary",           title="Summary Keywords")
    with w2: render_wordcloud(df, column="relevant_keywords", title="Relevant Keywords")

    # ── Live Intelligence Feed ────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Live Intelligence Feed</div>", unsafe_allow_html=True)

    # Impact filter buttons (All / Critical / High / Medium / Low)
    if "feed_impact_active" not in st.session_state:
        st.session_state["feed_impact_active"] = "All"

    active_level = st.session_state["feed_impact_active"]

    feed_df = df.copy()
    if active_level != "All" and "impact" in feed_df.columns:
        feed_df = feed_df[feed_df["impact"].str.lower() == active_level.lower()]

    total_feed = len(feed_df)

    st.markdown(
        f"<div style='display:flex;align-items:center;gap:8px;"
        f"font-family:\"IBM Plex Mono\",monospace;font-size:11px;"
        f"color:#484f58;margin:6px 0 10px;'>"
        f"<span style='width:8px;height:8px;border-radius:50%;background:#ff6b6b;"
        f"display:inline-block;animation:blink 1.8s ease-in-out infinite;flex-shrink:0;'></span>"
        f"<span style='color:#f0f6fc;font-weight:700;text-transform:uppercase;letter-spacing:.12em;'>"
        f"Live Intelligence Feed</span>"
        f"<span style='background:#161b22;border:1px solid #21262d;border-radius:100px;"
        f"padding:2px 10px;font-size:10px;'>{total_feed} items</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    render_intel_feed(feed_df, max_items=20)


    # ── Raw data expander ─────────────────────────────────────────────────────
    with st.expander("📋 View raw incident data"):
        preferred  = ["id","title","incident_date","publication_date",
                      "category","incident_type","country","impact","source"]
        show_cols  = [c for c in preferred if c in df.columns] or list(df.columns)
        display_df = df[show_cols].copy()
        if "incident_date" in display_df.columns:
            display_df = display_df.sort_values("incident_date", ascending=False)
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        with st.expander("🔍 Debug: column names & row count"):
            st.code(
                f"Rows fetched (raw): {len(df_raw)}\n"
                f"Rows after filter:  {len(df)}\n"
                f"Columns: {list(df_raw.columns)}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 2 — RANSOMWARE LIVE
# ══════════════════════════════════════════════════════════════════════════════
def page_ransomware():
    @st.cache_data(ttl=300, show_spinner=False)
    def load_ransomware():
        return get_data("ransomware_victims")   # ← paginated

    with st.spinner("Loading ransomware data…"):
        rw_raw = load_ransomware()

    with st.sidebar:
        _sidebar_branding()
        st.markdown(_filter_label(), unsafe_allow_html=True)

        _rw_tmp = rw_raw.copy() if rw_raw is not None and not rw_raw.empty else pd.DataFrame()
        if "date" in _rw_tmp.columns:
            _rw_tmp["date"] = pd.to_datetime(_rw_tmp["date"], errors="coerce", utc=True).dt.tz_convert(TZ_MY)

        rw_min_date = _rw_tmp["date"].dropna().min().date() \
                      if "date" in _rw_tmp.columns and not _rw_tmp["date"].isna().all() \
                      else date(2024, 1, 1)

        rw_date_range = st.date_input(
            "Date range",
            value=(rw_min_date, now_my().date()),
            max_value=now_my().date(),
            key="rw_date",
        )

        rw_country_opts = sorted(_rw_tmp["country"].dropna().unique().tolist()) \
                          if "country" in _rw_tmp.columns else []
        rw_sector_opts  = sorted(_rw_tmp["sector"].dropna().unique().tolist()) \
                          if "sector"  in _rw_tmp.columns else []

        rw_country_filter  = st.multiselect("Country",  options=rw_country_opts,
                                             placeholder="All countries",  key="rw_country")
        rw_sector_filter   = st.multiselect("Sector",   options=rw_sector_opts,
                                             placeholder="All sectors",    key="rw_sector")
        rw_severity_filter = st.multiselect("Severity",
                                             options=["Critical","High","Medium","Low"],
                                             placeholder="All severities", key="rw_severity")

        _sidebar_footer()

    page_header("🔴 Ransomware Live", "Real-time victim tracker · Powered by ransomware.live")

    if rw_raw is None or rw_raw.empty:
        st.warning("⚠️ No ransomware data found. The table may be empty or not yet crawled.")
        st.stop()

    rw = rw_raw.copy()
    if "date" in rw.columns:
        rw["date"] = pd.to_datetime(rw["date"], errors="coerce", utc=True).dt.tz_convert(TZ_MY)

    rw_f     = rw.copy()
    date_col = "date" if "date" in rw_f.columns else None

    if date_col and len(rw_date_range) == 2:
        s = pd.Timestamp(rw_date_range[0], tz=TZ_MY)
        e = pd.Timestamp(rw_date_range[1], tz=TZ_MY) + timedelta(days=1) - timedelta(seconds=1)
        rw_f = rw_f[rw_f[date_col].between(s, e, inclusive="both")]
    if rw_country_filter and "country" in rw_f.columns:
        rw_f = rw_f[rw_f["country"].isin(rw_country_filter)]
    if rw_sector_filter and "sector" in rw_f.columns:
        rw_f = rw_f[rw_f["sector"].isin(rw_sector_filter)]
    if rw_severity_filter and "severity" in rw_f.columns:
        rw_f = rw_f[rw_f["severity"].isin(rw_severity_filter)]

    total_victims  = len(rw_f)
    total_sectors  = rw_f["sector"].nunique()  if "sector"  in rw_f.columns else 0
    top_sector     = rw_f["sector"].value_counts().idxmax() \
                     if "sector" in rw_f.columns and total_victims > 0 else "—"
    rw_countries_n = rw_f["country"].nunique() if "country" in rw_f.columns else 0
    new_rw_week    = len(rw_f[rw_f[date_col] >= now_my() - timedelta(days=7)]) \
                     if date_col else 0

    rk1, rk2, rk3, rk4, rk5 = st.columns(5)
    kpi_row([
        (rk1, total_victims,  "Total Victims",        f"+{new_rw_week} this week", "warn"),
        (rk2, total_sectors,  "Affected Sectors",     "Tracked sectors",            "warn"),
        (rk3, f'<span style="color:#cc0000">{top_sector}</span>', "Most Targeted Sector", "By victim count", ""),
        (rk4, rw_countries_n, "Countries Hit",        "Unique nations",             ""),
        (rk5, new_rw_week,    "New This Week",        "Last 7 days",                "warn" if new_rw_week else ""),
    ])

    st.markdown("<div class='section-header'>Attack Trends</div>", unsafe_allow_html=True)
    if date_col and not rw_f.empty:
        tl = rw_f.set_index(date_col).resample("W").size().reset_index(name="victims")
        tl.columns = ["week", "victims"]
        fig = px.area(tl, x="week", y="victims", title="Weekly Victims",
                      color_discrete_sequence=["#f78166"], template="plotly_dark")
        fig.update_traces(fill="tozeroy", fillcolor="rgba(247,129,102,0.15)", line=dict(color="#f78166", width=2))
        fig.update_layout(paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                          font_color="#c9d1d9", title_font_color="#f0f6fc",
                          xaxis=dict(showgrid=False),
                          yaxis=dict(showgrid=True, gridcolor="#21262d", tickformat="d", dtick=1),
                          margin=dict(l=10,r=10,t=40,b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("<div class='section-header'>Sectors</div>", unsafe_allow_html=True)
    rc2, rc4 = st.columns([1, 1])
    with rc2:
        if "sector" in rw_f.columns and not rw_f.empty:
            tg = rw_f["sector"].value_counts().head(10).reset_index()
            tg.columns = ["sector", "count"]
            fig = px.pie(tg, names="sector", values="count", title="Top Targeted Sectors",
                         color_discrete_sequence=px.colors.sequential.Reds_r,
                         hole=0.4, template="plotly_dark")
            fig.update_layout(paper_bgcolor="#161b22", font_color="#c9d1d9",
                              title_font_color="#fcf3f0",
                              legend=dict(font=dict(size=10)),
                              margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig, use_container_width=True)

    with rc4:
        if "threat_actor" in rw_f.columns and not rw_f.empty:
            ta = rw_f["threat_actor"].value_counts().head(5).reset_index()
            ta.columns = ["threat_actor", "count"]
            fig = px.bar(ta, x="count", y="threat_actor", orientation="h",
                         title="Top 5 Threat Actors",
                         color="count", color_continuous_scale=["#21262d","#f78166"],
                         template="plotly_dark")
            fig.update_layout(paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                              font_color="#c9d1d9", title_font_color="#f0f6fc",
                              yaxis=dict(autorange="reversed"),
                              coloraxis_showscale=False,
                              margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig, use_container_width=True)

    if "severity" in rw_f.columns and not rw_f.empty:
        st.markdown("<div class='section-header'>Severity Distribution</div>", unsafe_allow_html=True)
        sv1, sv2 = st.columns([1, 2])
        SEV_ORDER  = ["Critical","High","Medium","Low"]
        SEV_COLORS = {"Critical":"#ff6b6b","High":"#ffa94d","Medium":"#a9d64b","Low":"#4fc3f7"}
        sev_counts = (rw_f["severity"].value_counts()
                      .reindex(SEV_ORDER).dropna().reset_index())
        sev_counts.columns = ["severity","count"]
        with sv1:
            for _, row in sev_counts.iterrows():
                pct   = int(row["count"] / total_victims * 100) if total_victims else 0
                color = SEV_COLORS.get(row["severity"], "#8b949e")
                st.markdown(f"""
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;
                            background:#161b22;border:1px solid #21262d;
                            border-left:3px solid {color};border-radius:8px;padding:10px 14px;">
                    <span style="font-size:13px;font-weight:600;color:{color};min-width:68px;">{row['severity']}</span>
                    <div style="flex:1;background:#21262d;border-radius:4px;height:8px;">
                        <div style="width:{pct}%;background:{color};height:8px;border-radius:4px;"></div>
                    </div>
                    <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                                 color:#8b949e;min-width:72px;text-align:right;">
                        {int(row['count']):,} ({pct}%)
                    </span>
                </div>""", unsafe_allow_html=True)
        with sv2:
            fig = px.bar(sev_counts, x="severity", y="count", title="Victims by Severity",
                         color="severity", color_discrete_map=SEV_COLORS,
                         category_orders={"severity": SEV_ORDER}, template="plotly_dark")
            fig.update_layout(paper_bgcolor="#161b22", plot_bgcolor="#161b22",
                              font_color="#c9d1d9", title_font_color="#f0f6fc",
                              showlegend=False, margin=dict(l=10,r=10,t=40,b=10))
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("<div class='section-header'>Recent Victim Posts</div>", unsafe_allow_html=True)
    SEV_CLASS = {"critical":"sev-critical","high":"sev-high","medium":"sev-medium","low":"sev-low"}
    if not rw_f.empty and date_col:
        for _, row in rw_f.sort_values(date_col, ascending=False).head(30).iterrows():
            title    = row.get("organization", "Unknown Victim")
            country  = row.get("country",  "—")
            sector   = row.get("sector",   "—")
            severity = row.get("severity", "—")
            disc     = row.get("date", pd.NaT)
            disc_str = disc.strftime("%d %b %Y, %H:%M") if pd.notna(disc) else "—"
            sev_cls  = SEV_CLASS.get(str(severity).lower(), "")
            st.markdown(f"""
            <div class="victim-card">
                <div class="victim-name">{title}</div>
                <div class="victim-meta">
                    📅 {disc_str} &nbsp;·&nbsp; 🌏 {country} &nbsp;·&nbsp; 🏭 {sector}
                </div>
                <span class="victim-badge {sev_cls}">⚠ {severity}</span>
            </div>""", unsafe_allow_html=True)
    else:
        st.info("No victims match the current filters.")

    with st.expander("📋 View raw ransomware data"):
        preferred_rw = ["organization","country","sector","severity","date"]
        show_rw      = [c for c in preferred_rw if c in rw_f.columns] or list(rw_f.columns)
        rw_disp      = rw_f[show_rw].copy()
        if date_col: rw_disp = rw_disp.sort_values(date_col, ascending=False)
        st.dataframe(rw_disp, use_container_width=True, hide_index=True)
        with st.expander("🔍 Debug: column names"):
            st.code(
                f"Rows fetched (raw): {len(rw_raw)}\n"
                f"Rows after filter:  {len(rw_f)}\n"
                f"Columns: {list(rw_raw.columns)}"
            )


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 3 — AI ANALYST
# ══════════════════════════════════════════════════════════════════════════════
def page_ai_analyst():
    page_header("🤖 AI Analyst", "Ask anything about the threat landscape · Powered by Groq")

    st.markdown("""
    <div class="chat-hero">
        <div style="font-size:48px;">🤖</div>
        <div class="chat-hero-title">Incident Intelligence Analyst</div>
        <div class="chat-hero-sub">
            Ask questions about incidents, ransomware trends, affected sectors,
            countries, threat actors — backed by your live Supabase data.
        </div>
    </div>
    """, unsafe_allow_html=True)

    @st.cache_data(ttl=120, show_spinner=False)
    def load_incidents_for_chat():
        return get_data("incidents")

    with st.spinner("Preparing data context for AI…"):
        df_chat = load_incidents_for_chat()

    if df_chat is not None and not df_chat.empty:
        for col in ("incident_date", "publication_date"):
            if col in df_chat.columns:
                df_chat[col] = pd.to_datetime(
                    df_chat[col], errors="coerce", utc=True
                ).dt.tz_convert(TZ_MY)
        chatbot_ui(df_chat)
    else:
        st.error("⚠️ Could not load incident data. Check your Supabase connection.")


# ══════════════════════════════════════════════════════════════════════════════
#  PAGE 4 — RISK ASSESSMENT
# ══════════════════════════════════════════════════════════════════════════════
def page_risk_assessment():
    @st.cache_data(ttl=120, show_spinner=False)
    def load_incidents_risk():
        return get_data("incidents")

    with st.spinner("Loading incidents for risk analysis…"):
        df_raw = load_incidents_risk()

    with st.sidebar:
        _sidebar_branding()
        st.markdown(_filter_label("Risk Filters"), unsafe_allow_html=True)
        _sidebar_footer()

    page_header("⚖️ Risk Assessment", "Custom impact scoring · Formula-driven severity classification")

    if df_raw is None or df_raw.empty:
        st.error("⚠️ Could not load data from Supabase.")
        st.stop()

    # parse dates
    df_all = df_raw.copy()
    for col in ("incident_date", "publication_date"):
        if col in df_all.columns:
            df_all[col] = pd.to_datetime(df_all[col], errors="coerce", utc=True).dt.tz_convert(TZ_MY)

    # ── Formula explainer card ────────────────────────────────────────────────
    st.markdown("""
    <div style="background:#131829;border:1px solid #1e2130;border-radius:12px;padding:20px 26px;margin-bottom:22px;">
        <div style="font-size:14px;font-weight:700;color:#e8ecf4;margin-bottom:10px;">📐 Impact Score Formula</div>
        <div style="font-family:'IBM Plex Mono',monospace;font-size:13px;color:#4f8ef7;margin-bottom:14px;">
            Impact Score = 0.25 × Sector + 0.20 × Country + 0.35 × Attack Type + 0.20 × Data Exposure
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
            <div style="background:#0d1022;border:1px solid #1e2130;border-radius:8px;padding:12px;">
                <div style="font-size:11px;font-weight:600;color:#7a8599;text-transform:uppercase;letter-spacing:.09em;margin-bottom:6px;">W1 · Sector (25%)</div>
                <div style="font-size:12px;color:#b0bccf;line-height:1.7;">
                    🔴 Gov/Health/Finance/Defense/Energy → 0.8<br>
                    🟠 Manufacturing/Telecom/Transport → 0.6<br>
                    🟡 Consumer/Retail/Industrial → 0.4<br>
                    ⚪ Other → 0.2
                </div>
            </div>
            <div style="background:#0d1022;border:1px solid #1e2130;border-radius:8px;padding:12px;">
                <div style="font-size:11px;font-weight:600;color:#7a8599;text-transform:uppercase;letter-spacing:.09em;margin-bottom:6px;">W2 · Country (20%)</div>
                <div style="font-size:12px;color:#b0bccf;line-height:1.7;">
                    🇲🇾 Malaysia → 0.7<br>
                    🌏 Southeast Asia → 0.5<br>
                    🌐 Global / Other → 0.3
                </div>
            </div>
            <div style="background:#0d1022;border:1px solid #1e2130;border-radius:8px;padding:12px;">
                <div style="font-size:11px;font-weight:600;color:#7a8599;text-transform:uppercase;letter-spacing:.09em;margin-bottom:6px;">W3 · Attack Type (35%)</div>
                <div style="font-size:12px;color:#b0bccf;line-height:1.7;">
                    🔴 Ransomware/RCE/APT/Breach → 0.9<br>
                    🟠 Phishing/Malware/DDoS/BF → 0.5<br>
                    🟡 Defacement/Spam/Recon → 0.2
                </div>
            </div>
            <div style="background:#0d1022;border:1px solid #1e2130;border-radius:8px;padding:12px;">
                <div style="font-size:11px;font-weight:600;color:#7a8599;text-transform:uppercase;letter-spacing:.09em;margin-bottom:6px;">W4 · Data Exposure (20%)</div>
                <div style="font-size:12px;color:#b0bccf;line-height:1.7;">
                    🔴 Identity/Financial/Legal → 0.8<br>
                    🟠 Reputational damage → 0.5<br>
                    🟡 Competitive/Minor → 0.3
                </div>
            </div>
        </div>
        <div style="margin-top:12px;font-size:12px;color:#7a8599;">
            Thresholds: <span style="color:#f76c6c;font-weight:600;">Critical ≥ 0.70</span> &nbsp;·&nbsp;
            <span style="color:#f7a94f;font-weight:600;">High ≥ 0.50</span> &nbsp;·&nbsp;
            <span style="color:#4f8ef7;font-weight:600;">Medium ≥ 0.30</span> &nbsp;·&nbsp;
            <span style="color:#3ecf8e;font-weight:600;">Low &lt; 0.30</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Score all rows ────────────────────────────────────────────────────────
    with st.spinner("Applying risk formula to all incidents…"):
        df_scored = score_dataframe(df_all)

    SEV_COLORS = {
        "Critical": ("#f76c6c","#3d0f0f"),
        "High":     ("#f7a94f","#2d1b0a"),
        "Medium":   ("#4f8ef7","#0a1f2a"),
        "Low":      ("#3ecf8e","#0a1f17"),
    }
    SEV_ORDER = ["Critical","High","Medium","Low"]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    dist = df_scored["severity"].value_counts()
    total = len(df_scored)
    k_cols = st.columns(5)
    kpi_row([
        (k_cols[0], total,                  "Total Assessed",    "All incidents",        ""),
        (k_cols[1], int(dist.get("Critical",0)), "Critical",     "Score ≥ 0.70",         "warn"),
        (k_cols[2], int(dist.get("High",0)),    "High",          "Score ≥ 0.50",         "warn"),
        (k_cols[3], int(dist.get("Medium",0)),  "Medium",        "Score ≥ 0.30",         "up"),
        (k_cols[4], int(dist.get("Low",0)),     "Low",           "Score < 0.30",         ""),
    ])

    # ── Distribution charts ───────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Severity Distribution</div>", unsafe_allow_html=True)
    ch1, ch2, ch3 = st.columns([1,1,1])

    with ch1:
        # Donut
        d_data = pd.DataFrame({
            "Severity": SEV_ORDER,
            "Count": [int(dist.get(s,0)) for s in SEV_ORDER]
        })
        fig = px.pie(d_data, names="Severity", values="Count", hole=0.55,
                     color="Severity",
                     color_discrete_map={s:SEV_COLORS[s][0] for s in SEV_ORDER},
                     title="Severity Split")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", font_color="#b0bccf",
                          title_font_color="#e8ecf4", margin=dict(l=0,r=0,t=36,b=0),
                          legend=dict(font=dict(size=11)))
        st.plotly_chart(fig, use_container_width=True)

    with ch2:
        # Risk score distribution histogram
        fig2 = px.histogram(df_scored, x="risk_score", nbins=20,
                            color_discrete_sequence=["#4f8ef7"],
                            title="Risk Score Distribution")
        fig2.add_vline(x=0.70, line_dash="dash", line_color="#f76c6c",
                       annotation_text="Critical", annotation_font_color="#f76c6c")
        fig2.add_vline(x=0.50, line_dash="dash", line_color="#f7a94f",
                       annotation_text="High",     annotation_font_color="#f7a94f")
        fig2.add_vline(x=0.30, line_dash="dash", line_color="#4f8ef7",
                       annotation_text="Medium",   annotation_font_color="#4f8ef7")
        fig2.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#b0bccf", title_font_color="#e8ecf4",
                           xaxis=dict(gridcolor="#1e2130", range=[0,1]),
                           yaxis=dict(gridcolor="#1e2130"),
                           margin=dict(l=10,r=10,t=36,b=10))
        st.plotly_chart(fig2, use_container_width=True)

    with ch3:
        # Average component scores radar / bar
        comp_avg = pd.DataFrame({
            "Component": ["Sector (W1)", "Country (W2)", "Attack Type (W3)", "Data Exposure (W4)"],
            "Avg Score": [
                df_scored["sector_score"].mean(),
                df_scored["country_score"].mean(),
                df_scored["attack_type_score"].mean(),
                df_scored["data_exposure_score"].mean(),
            ]
        })
        fig3 = px.bar(comp_avg, x="Component", y="Avg Score",
                      color="Avg Score", color_continuous_scale=["#1e2130","#f76c6c"],
                      title="Avg Component Scores",
                      text=comp_avg["Avg Score"].round(2))
        fig3.update_traces(textposition="outside", textfont_color="#e8ecf4")
        fig3.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#b0bccf", title_font_color="#e8ecf4",
                           coloraxis_showscale=False,
                           xaxis=dict(gridcolor="#1e2130", tickfont=dict(size=10)),
                           yaxis=dict(gridcolor="#1e2130", range=[0,1]),
                           margin=dict(l=10,r=10,t=36,b=10))
        st.plotly_chart(fig3, use_container_width=True)

    # ── Attack class breakdown ─────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Attack Class Breakdown</div>", unsafe_allow_html=True)
    if "attack_class" in df_scored.columns:
        ac_counts = df_scored["attack_class"].value_counts().reset_index()
        ac_counts.columns = ["Attack Class","Count"]
        ac_colors = {
            "Critical Attack":  "#f76c6c",
            "Medium Attack":    "#f7a94f",
            "Low-Level Attack": "#3ecf8e",
            "Unclassified":     "#7a8599",
        }
        fig_ac = px.bar(ac_counts, x="Count", y="Attack Class", orientation="h",
                        color="Attack Class",
                        color_discrete_map=ac_colors,
                        title="Incidents by Attack Class")
        fig_ac.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                             font_color="#b0bccf", title_font_color="#e8ecf4",
                             yaxis=dict(categoryorder="total ascending"),
                             showlegend=False,
                             margin=dict(l=10,r=10,t=36,b=10),
                             xaxis=dict(gridcolor="#1e2130"),
                             yaxis2=dict(gridcolor="#1e2130"))
        st.plotly_chart(fig_ac, use_container_width=True)

    # ── Top critical incidents table ───────────────────────────────────────────
    st.markdown("<div class='section-header'>Top Critical & High Incidents</div>", unsafe_allow_html=True)

    top_df = df_scored[df_scored["severity"].isin(["Critical","High"])]\
                .sort_values("risk_score", ascending=False).head(20)

    title_col   = next((c for c in ("title","headline","name") if c in top_df.columns), None)
    date_col    = next((c for c in ("incident_date","publication_date") if c in top_df.columns), None)
    country_col = "country" if "country" in top_df.columns else None
    cat_col     = "category" if "category" in top_df.columns else None

    for _, row in top_df.iterrows():
        title   = _strip_html(str(row.get(title_col, "Untitled") if title_col else "Untitled"))[:100]
        sev     = row.get("severity","Unknown")
        score   = row.get("risk_score", 0)
        country = str(row.get(country_col,"") if country_col else "")
        cat     = str(row.get(cat_col,   "") if cat_col     else "")
        ac      = row.get("attack_class","")
        date_s  = ""
        if date_col and pd.notna(row.get(date_col)):
            try: date_s = row[date_col].strftime("%d %b %Y")
            except: pass

        fg, bg = SEV_COLORS.get(sev, ("#7a8599","#1c1c1c"))
        cat_color = _get_category_color(cat)
        bar_pct   = int(score * 100)

        # sub-scores
        s1 = row.get("sector_score",0)
        s2 = row.get("country_score",0)
        s3 = row.get("attack_type_score",0)
        s4 = row.get("data_exposure_score",0)

        st.markdown(f"""
        <div style="background:#131829;border:1px solid #1e2130;border-left:3px solid {fg};
                    border-radius:10px;padding:14px 18px;margin-bottom:8px;">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
                <div style="font-size:14px;font-weight:600;color:#e8ecf4;">{title}</div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <span style="background:{bg};color:{fg};font-size:11px;font-weight:700;
                                 font-family:'IBM Plex Mono',monospace;padding:2px 10px;
                                 border-radius:100px;text-transform:uppercase;">{sev}</span>
                    <span style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                                 font-weight:700;color:{fg};">{score:.3f}</span>
                </div>
            </div>
            <div style="background:#1e2130;border-radius:4px;height:6px;margin-bottom:10px;">
                <div style="width:{bar_pct}%;background:linear-gradient(90deg,{bg},{fg});height:6px;border-radius:4px;"></div>
            </div>
            <div style="display:flex;gap:18px;font-size:11px;color:#7a8599;font-family:'IBM Plex Mono',monospace;flex-wrap:wrap;">
                <span>📅 {date_s}</span>
                <span>🌏 {country}</span>
                <span style="color:{cat_color};">⬛ {cat}</span>
                <span>⚡ {ac}</span>
                <span style="margin-left:auto;">
                    S:{s1:.2f} · C:{s2:.2f} · A:{s3:.2f} · D:{s4:.2f}
                </span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Write-back section ────────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Push Scores to Supabase</div>", unsafe_allow_html=True)
    st.markdown("""
    <div style="background:#0d1022;border:1px solid #1e2130;border-radius:10px;padding:16px 20px;margin-bottom:16px;">
        <div style="font-size:13px;color:#b0bccf;line-height:1.7;">
            Click <b style="color:#e8ecf4;">Apply & Save to Database</b> to overwrite the
            <code style="color:#4f8ef7;">severity</code>, <code style="color:#4f8ef7;">risk_score</code>,
            and all component score columns in Supabase with the formula results.<br>
            <span style="color:#f7a94f;">⚠ Requires the <b>service_role</b> key in your secrets — the anon key is read-only.</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_btn, col_status = st.columns([1, 3])
    with col_btn:
        run_push = st.button("💾 Apply & Save to Database", type="primary", use_container_width=True)

    if run_push:
        from utils.risk_scorer import build_update_payload
        client = _supabase()

        id_col = next((c for c in ("id","uuid","incident_id") if c in df_scored.columns), None)
        if not id_col:
            st.error("❌ No ID column found (id / uuid / incident_id). Cannot upsert.")
        else:
            records = []
            for _, row in df_scored.iterrows():
                payload = build_update_payload(row)
                payload[id_col] = row[id_col]
                records.append(payload)

            bar     = st.progress(0, text="Pushing scores to Supabase…")
            success = 0
            errors  = 0
            BATCH   = 50

            for i in range(0, len(records), BATCH):
                batch = records[i:i+BATCH]
                try:
                    client.table("incidents").upsert(batch, on_conflict=id_col).execute()
                    success += len(batch)
                except Exception as e:
                    errors += len(batch)
                    st.warning(f"Batch error: {e}")
                bar.progress(min((i+BATCH)/len(records), 1.0),
                             text=f"Pushed {min(i+BATCH, len(records))}/{len(records)} rows…")

            if errors == 0:
                st.success(f"✅ {success} rows updated successfully in Supabase!")
                st.cache_data.clear()
            else:
                st.warning(f"⚠️ {success} rows pushed, {errors} failed. Check column names and key permissions.")
                st.markdown("""
                **If you see errors, run this SQL in Supabase → SQL Editor first:**
                ```sql
                ALTER TABLE public.incidents
                  ADD COLUMN IF NOT EXISTS risk_score          FLOAT,
                  ADD COLUMN IF NOT EXISTS sector_score        FLOAT,
                  ADD COLUMN IF NOT EXISTS country_score       FLOAT,
                  ADD COLUMN IF NOT EXISTS attack_type_score   FLOAT,
                  ADD COLUMN IF NOT EXISTS data_exposure_score FLOAT,
                  ADD COLUMN IF NOT EXISTS attack_class        TEXT;
                ```
                """)

    # ── Full scored table ─────────────────────────────────────────────────────
    with st.expander("📋 View all scored incidents"):
        show_cols = [c for c in [
            title_col, "severity","risk_score",
            "sector_score","country_score","attack_type_score","data_exposure_score",
            "attack_class", date_col, country_col, cat_col
        ] if c and c in df_scored.columns]
        st.dataframe(
            df_scored[show_cols].sort_values("risk_score", ascending=False),
            use_container_width=True, hide_index=True
        )


# ══════════════════════════════════════════════════════════════════════════════
#  NAVIGATION
# ══════════════════════════════════════════════════════════════════════════════
pg = st.navigation(
    [
        st.Page(page_cyber_news,      title="Cyber News",       icon="📰", default=True),
        st.Page(page_ransomware,      title="Ransomware Live",  icon="🔴"),
        st.Page(page_risk_assessment, title="Risk Assessment",  icon="⚖️"),
        st.Page(page_ai_analyst,      title="AI Analyst",       icon="🤖"),
    ],
    position="top",
)

pg.run()
