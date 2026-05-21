"""
utils/risk_scorer.py
────────────────────────────────────────────────────────────────────────────────
Custom Risk / Impact-Level Scoring Engine
Formula:
    impact_score = w1(sector) + w2(country) + w3(attack_type) + w4(data_exposure)

Where each component is normalised 0–1 and the final score maps to:
    ≥ 0.70  → Critical
    ≥ 0.50  → High
    ≥ 0.30  → Medium
    <  0.30 → Low
────────────────────────────────────────────────────────────────────────────────
"""

import re
import pandas as pd
from typing import Tuple

# ── Weights (must sum to 1.0) ─────────────────────────────────────────────────
W1_SECTOR       = 0.25
W2_COUNTRY      = 0.20
W3_ATTACK_TYPE  = 0.35   # highest weight — attack type drives severity most
W4_DATA_EXPOSURE= 0.20

assert abs(W1_SECTOR + W2_COUNTRY + W3_ATTACK_TYPE + W4_DATA_EXPOSURE - 1.0) < 1e-9, \
    "Weights must sum to 1.0"


# ══════════════════════════════════════════════════════════════════════════════
#  W1 — SECTOR SCORE
# ══════════════════════════════════════════════════════════════════════════════
_SECTOR_TIER1 = [
    "government", "financial service", "finance", "banking", "bank",
    "defense", "defence", "military", "healthcare", "hospital", "health",
    "energy", "utility", "utilities", "power grid", "nuclear",
]
_SECTOR_TIER2 = [
    "manufacturing", "construction", "transportation", "logistics",
    "supply chain", "building automation", "digital", "information technology",
    "it service", "telecommunication", "telecom", "media",
]
_SECTOR_TIER3 = [
    "consumer", "retail", "product", "service", "industrial",
    "plantation", "agriculture", "property", "real estate",
]


def score_sector(text: str) -> float:
    """
    Returns sector score (0.2 – 0.8) based on highest-matching tier found
    anywhere in the combined text (sector field + summary).
    """
    t = str(text).lower()
    if any(kw in t for kw in _SECTOR_TIER1):
        return 0.8
    if any(kw in t for kw in _SECTOR_TIER2):
        return 0.6
    if any(kw in t for kw in _SECTOR_TIER3):
        return 0.4
    return 0.2


# ══════════════════════════════════════════════════════════════════════════════
#  W2 — COUNTRY SCORE
# ══════════════════════════════════════════════════════════════════════════════
_MALAYSIA_KW = ["malaysia", "malaysian", "kuala lumpur", "kl", "putrajaya", "cyberjaya"]
_SEA_KW = [
    "singapore", "indonesia", "thailand", "philippines", "vietnam",
    "myanmar", "cambodia", "laos", "brunei", "timor", "southeast asia",
    "asean",
]


def score_country(text: str) -> float:
    """
    Returns country score based on geographic relevance.
        Malaysia        → 0.7
        Southeast Asia  → 0.5
        Global / other  → 0.3
    """
    t = str(text).lower()
    if any(kw in t for kw in _MALAYSIA_KW):
        return 0.7
    if any(kw in t for kw in _SEA_KW):
        return 0.5
    return 0.3


# ══════════════════════════════════════════════════════════════════════════════
#  W3 — ATTACK TYPE SCORE
# ══════════════════════════════════════════════════════════════════════════════
_ATTACK_CRITICAL = [
    "ransomware", "data breach", "supply chain attack", "supply chain",
    "advanced persistent threat", "apt", "zero-day", "zero day", "0day",
    "business email compromise", "bec", "remote code execution", "rce",
    "unauthorized privileged access", "privilege escalation",
    "critical infrastructure attack",
]
_ATTACK_MEDIUM = [
    "phishing", "spear phishing", "malware", "credential theft",
    "credential stuffing", "brute force", "distributed denial",
    "ddos", "dos attack", "insider threat", "web application attack",
    "sql injection", "xss", "api abuse", "api exploit", "spyware",
    "cloud misconfiguration", "misconfiguration",
]
_ATTACK_LOW = [
    "website defacement", "defacement", "spam", "botnet", "scanning",
    "port scan", "cryptojacking", "crypto mining", "adware",
    "reconnaissance", "recon", "social engineering", "low-level",
]


def score_attack_type(text: str) -> float:
    """
    Returns attack-type score by scanning the combined text for known keywords.
    Uses the highest severity match found (critical > medium > low).
        Critical → 0.9
        Medium   → 0.5
        Low      → 0.2
    """
    t = str(text).lower()
    if any(kw in t for kw in _ATTACK_CRITICAL):
        return 0.9
    if any(kw in t for kw in _ATTACK_MEDIUM):
        return 0.5
    if any(kw in t for kw in _ATTACK_LOW):
        return 0.2
    return 0.3   # unknown / unclassified


def classify_attack(text: str) -> str:
    """Return human-readable attack class label."""
    t = str(text).lower()
    if any(kw in t for kw in _ATTACK_CRITICAL):
        return "Critical Attack"
    if any(kw in t for kw in _ATTACK_MEDIUM):
        return "Medium Attack"
    if any(kw in t for kw in _ATTACK_LOW):
        return "Low-Level Attack"
    return "Unclassified"


# ══════════════════════════════════════════════════════════════════════════════
#  W4 — DATA EXPOSURE IMPACT SCORE
# ══════════════════════════════════════════════════════════════════════════════
_EXPOSURE_HIGH = [
    "identity theft", "privacy breach", "personally identifiable",
    "pii", "financial loss", "financial fraud", "integrity loss",
    "regulatory", "legal consequence", "fine", "gdpr", "pdpa",
    "lawsuit", "litigation", "data leak", "sensitive data exposed",
    "confidential data", "medical record", "health record",
    "credit card", "bank account", "password exposed",
]
_EXPOSURE_MED = [
    "reputational damage", "reputation", "brand damage",
    "customer trust", "public disclosure", "media coverage",
    "negative publicity",
]
_EXPOSURE_LOW = [
    "competitive disadvantage", "minor disruption", "performance impact",
    "service degradation", "limited impact", "low impact",
]


def score_data_exposure(text: str) -> float:
    """
    Returns data-exposure impact score from summary text.
        High (identity/financial/legal) → 0.8
        Medium (reputational)           → 0.5
        Low (competitive/minor)         → 0.3
    """
    t = str(text).lower()
    if any(kw in t for kw in _EXPOSURE_HIGH):
        return 0.8
    if any(kw in t for kw in _EXPOSURE_MED):
        return 0.5
    if any(kw in t for kw in _EXPOSURE_LOW):
        return 0.3
    return 0.3   # default: unknown → treat as low


# ══════════════════════════════════════════════════════════════════════════════
#  COMPOSITE SCORER
# ══════════════════════════════════════════════════════════════════════════════
def compute_impact_score(
    sector_text:   str,
    country_text:  str,
    attack_text:   str,
    summary_text:  str,
) -> Tuple[float, str, dict]:
    """
    Compute the weighted impact score for a single incident.

    Parameters
    ----------
    sector_text  : incident sector / category field
    country_text : country / region field
    attack_text  : incident_type / attack_type field
    summary_text : full summary / description field

    Returns
    -------
    (score: float, severity_label: str, breakdown: dict)
        score          — raw weighted score [0, 1]
        severity_label — "Critical" | "High" | "Medium" | "Low"
        breakdown      — per-component scores for transparency
    """
    # Build combined texts for each dimension
    combined_sector  = f"{sector_text} {summary_text}"
    combined_country = f"{country_text} {summary_text}"
    combined_attack  = f"{attack_text} {summary_text}"
    combined_exposure= summary_text

    s1 = score_sector(combined_sector)
    s2 = score_country(combined_country)
    s3 = score_attack_type(combined_attack)
    s4 = score_data_exposure(combined_exposure)

    total = W1_SECTOR * s1 + W2_COUNTRY * s2 + W3_ATTACK_TYPE * s3 + W4_DATA_EXPOSURE * s4

    if total >= 0.70:
        label = "Critical"
    elif total >= 0.50:
        label = "High"
    elif total >= 0.30:
        label = "Medium"
    else:
        label = "Low"

    breakdown = {
        "sector_score":        round(s1, 3),
        "country_score":       round(s2, 3),
        "attack_type_score":   round(s3, 3),
        "data_exposure_score": round(s4, 3),
        "weighted_total":      round(total, 4),
        "attack_class":        classify_attack(combined_attack),
    }

    return round(total, 4), label, breakdown


# ══════════════════════════════════════════════════════════════════════════════
#  DATAFRAME-LEVEL SCORER
# ══════════════════════════════════════════════════════════════════════════════
def score_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply the risk formula to every row of a DataFrame.

    Looks for these columns (with automatic fallbacks):
        sector   → category, incident_category, sector
        country  → country, nation, location, region
        attack   → incident_type, attack_type, type, threat_type
        summary  → summary, description, content

    Adds / overwrites:
        risk_score          float   weighted composite score
        severity            str     Critical / High / Medium / Low
        sector_score        float   W1 component
        country_score       float   W2 component
        attack_type_score   float   W3 component
        data_exposure_score float   W4 component
        attack_class        str     human-readable attack tier
    """
    df = df.copy()

    def _pick(cols):
        for c in cols:
            if c in df.columns:
                return c
        return None

    sector_col   = _pick(["sector", "category", "incident_category"])
    country_col  = _pick(["country", "nation", "location", "region"])
    attack_col   = _pick(["incident_type", "attack_type", "type", "threat_type"])
    summary_col  = _pick(["summary", "description", "content"])

    scores      = []
    labels      = []
    breakdowns  = []

    for _, row in df.iterrows():
        sector  = str(row.get(sector_col,  "")) if sector_col  else ""
        country = str(row.get(country_col, "")) if country_col else ""
        attack  = str(row.get(attack_col,  "")) if attack_col  else ""
        summary = str(row.get(summary_col, "")) if summary_col else ""

        score, label, bd = compute_impact_score(sector, country, attack, summary)
        scores.append(score)
        labels.append(label)
        breakdowns.append(bd)

    df["risk_score"]          = scores
    df["severity"]            = labels
    df["sector_score"]        = [b["sector_score"]        for b in breakdowns]
    df["country_score"]       = [b["country_score"]       for b in breakdowns]
    df["attack_type_score"]   = [b["attack_type_score"]   for b in breakdowns]
    df["data_exposure_score"] = [b["data_exposure_score"] for b in breakdowns]
    df["attack_class"]        = [b["attack_class"]        for b in breakdowns]

    return df


# ══════════════════════════════════════════════════════════════════════════════
#  SUPABASE WRITE-BACK HELPER
# ══════════════════════════════════════════════════════════════════════════════
def build_update_payload(row: pd.Series) -> dict:
    """
    Build the dict to UPSERT back to Supabase for a single scored row.
    Only includes the columns we want to overwrite.
    """
    return {
        "severity":            row["severity"],
        "risk_score":          float(row["risk_score"]),
        "sector_score":        float(row["sector_score"]),
        "country_score":       float(row["country_score"]),
        "attack_type_score":   float(row["attack_type_score"]),
        "data_exposure_score": float(row["data_exposure_score"]),
        "attack_class":        row["attack_class"],
    }
