
import numpy as np

def rank_threats(matrix, weights):
    weighted = matrix * weights
    score = weighted.sum(axis=1)
    return np.argsort(score)[::-1]
