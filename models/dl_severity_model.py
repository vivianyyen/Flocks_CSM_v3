
from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification

LABELS = ["Low","Medium","High","Critical"]

class ThreatSeverityModel:
    def __init__(self, model_name="distilbert-base-uncased"):
        self.tokenizer = DistilBertTokenizerFast.from_pretrained(model_name)
        self.model = DistilBertForSequenceClassification.from_pretrained(model_name, num_labels=4)

    def predict(self, text):
        # placeholder inference hook
        return {"severity":"High","confidence":0.88}
