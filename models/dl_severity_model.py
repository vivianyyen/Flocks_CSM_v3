
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
    txt = df.astype(str).agg(" ".join, axis=1)
    preds = txt.apply(predict_severity)
    df["dl_severity"] = preds.apply(lambda x: x["severity"])
    df["dl_confidence"] = preds.apply(lambda x: x["confidence"])
    return df
