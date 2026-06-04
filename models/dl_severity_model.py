
import pandas as pd

def predict_severity(text):
    t = str(text).lower()
    critical = ["ransomware","data breach","zero-day","apt","critical infrastructure"]
    high = ["phishing","malware","ddos","credential"]
    score = 0.3
    if any(k in t for k in critical):
        score = 0.92
        sev = "Critical"
    elif any(k in t for k in high):
        score = 0.75
        sev = "High"
    else:
        score = 0.55
        sev = "Medium"
    return {"severity": sev, "confidence": score}

def score_dataframe_dl(df):
    if df is None or len(df) == 0:
        return df

    df = df.copy()

    def build_text(row):
        parts = []
        for value in row.values:
            try:
                parts.append(str(value))
            except Exception:
                pass
        return " ".join(parts)

    text_series = df.apply(build_text, axis=1)

    predictions = text_series.apply(predict_severity)

    df["dl_severity"] = predictions.apply(
        lambda x: x.get("severity", "Medium")
    )

    df["dl_confidence"] = predictions.apply(
        lambda x: x.get("confidence", 0.5)
    )

    return df
