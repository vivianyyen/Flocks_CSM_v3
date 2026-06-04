
import numpy as np

def simulate_risk(likelihood, impact, runs=1000):
    samples = np.random.normal(likelihood * impact, 0.05, runs)
    return {
        "mean": float(np.mean(samples)),
        "p95": float(np.percentile(samples,95))
    }
