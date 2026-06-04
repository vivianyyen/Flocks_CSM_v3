
import numpy as np

def risk_metrics(confidence, runs=1000):
    vals = np.random.normal(confidence, 0.08, runs)
    vals = np.clip(vals,0,1)
    return float(vals.mean()), float(np.percentile(vals,95))
