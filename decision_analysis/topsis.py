
import pandas as pd

def rank_dataframe(df):
    sev_map={"Low":1,"Medium":2,"High":3,"Critical":4}
    df["decision_score"]=(df["dl_confidence"]*0.6 +
                          df["dl_severity"].map(sev_map).fillna(1)/4*0.4)
    return df.sort_values("decision_score",ascending=False)
