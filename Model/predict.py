"""
predict.py — Health Monitoring ECG Arrhythmia Predictor
========================================================
Loads the pre-trained XGBoost, GradientBoost, and RandomForest models
and exposes a simple `predict()` function.

Input : a dict (or list/array) of the 32 ECG feature values.
Output: dict with predictions from each model and a majority-vote result.

Label mapping (LabelEncoder alphabetical order):
    0 -> F    (Fusion beat)
    1 -> N    (Normal)
    2 -> Q    (Unclassified)
    3 -> SVEB (Supraventricular ectopic beat)
    4 -> VEB  (Ventricular ectopic beat)
"""

import warnings
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from xgboost import XGBClassifier

# ---------------------------------------------------------------------------
# Feature order — must match the training data column order (after dropping
# 'record' and 'type').
# ---------------------------------------------------------------------------
FEATURE_NAMES = [
    "0_pre-RR",     "0_post-RR",    "0_pPeak",      "0_tPeak",
    "0_rPeak",      "0_sPeak",      "0_qPeak",      "0_qrs_interval",
    "0_pq_interval","0_qt_interval","0_st_interval",
    "0_qrs_morph0", "0_qrs_morph1", "0_qrs_morph2", "0_qrs_morph3", "0_qrs_morph4",
    "1_pre-RR",     "1_post-RR",    "1_pPeak",      "1_tPeak",
    "1_rPeak",      "1_sPeak",      "1_qPeak",      "1_qrs_interval",
    "1_pq_interval","1_qt_interval","1_st_interval",
    "1_qrs_morph0", "1_qrs_morph1", "1_qrs_morph2", "1_qrs_morph3", "1_qrs_morph4",
]

# LabelEncoder fitted on ['F','N','Q','SVEB','VEB'] produces this mapping
LABEL_CLASSES = ["F", "N", "Q", "SVEB", "VEB"]

# ---------------------------------------------------------------------------
# Model paths — resolve relative to this file so it works from any cwd
# ---------------------------------------------------------------------------
_BASE = Path(__file__).parent / "models"
_MODEL_PATHS = {
    "xgb": _BASE / "xgb.json",
    "gb":  _BASE / "gb.pkl",
    "rf":  _BASE / "rf.pkl",
}

# ---------------------------------------------------------------------------
# Load models once at import time
# Suppress InconsistentVersionWarning — models work fine across minor versions
# ---------------------------------------------------------------------------
def _load_models():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xgb_model = XGBClassifier()
        xgb_model.load_model(_MODEL_PATHS["xgb"])
        gb_model = joblib.load(_MODEL_PATHS["gb"])
        rf_model = joblib.load(_MODEL_PATHS["rf"])
    return xgb_model, gb_model, rf_model

_XGB, _GB, _RF = _load_models()


# ---------------------------------------------------------------------------
# Internal helper: build a single-row DataFrame with proper column names
# so sklearn models don't warn about missing feature names.
# ---------------------------------------------------------------------------
def _to_dataframe(input_data) -> pd.DataFrame:
    if isinstance(input_data, dict):
        try:
            row = {f: [float(input_data[f])] for f in FEATURE_NAMES}
        except KeyError as e:
            raise ValueError(f"Missing feature key: {e}") from e
        return pd.DataFrame(row, columns=FEATURE_NAMES)

    arr = np.asarray(input_data, dtype=float).flatten()
    if arr.shape[0] != len(FEATURE_NAMES):
        raise ValueError(
            f"Expected {len(FEATURE_NAMES)} features, got {arr.shape[0]}."
        )
    return pd.DataFrame([arr], columns=FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def predict(input_data, model: str = "all") -> dict:
    """
    Predict ECG arrhythmia class from input features.

    Parameters
    ----------
    input_data : dict | list | np.ndarray
        - dict  : keys must match FEATURE_NAMES (order-independent).
        - list / np.ndarray : 32 values in the same order as FEATURE_NAMES.

    model : str
        Which model(s) to use: "xgb", "gb", "rf", or "all" (default).
        When "all", also returns a majority-vote prediction.

    Returns
    -------
    dict with keys "xgb", "gb", "rf" (and "majority" when model="all"),
    each containing the predicted label string, e.g. "N".

    Raises
    ------
    ValueError  — wrong number of features or unknown model name.
    """
    X = _to_dataframe(input_data)
    result = {}

    if model in ("xgb", "all"):
        result["xgb"] = LABEL_CLASSES[int(_XGB.predict(X)[0])]

    if model in ("gb", "all"):
        result["gb"] = LABEL_CLASSES[int(_GB.predict(X)[0])]

    if model in ("rf", "all"):
        result["rf"] = LABEL_CLASSES[int(_RF.predict(X)[0])]

    if model not in ("xgb", "gb", "rf", "all"):
        raise ValueError(f"model must be one of 'xgb', 'gb', 'rf', 'all'. Got: {model!r}")

    if model == "all":
        votes = [result["xgb"], result["gb"], result["rf"]]
        result["majority"] = max(set(votes), key=votes.count)

    return result


def predict_proba(input_data, model: str = "xgb") -> dict:
    """
    Return class probabilities for a single model.

    Parameters
    ----------
    input_data : dict | list | np.ndarray
        Same format as predict().
    model : str
        One of "xgb", "gb", "rf".

    Returns
    -------
    dict  {label: probability, ...}
        e.g. {"F": 0.01, "N": 0.94, "Q": 0.01, "SVEB": 0.02, "VEB": 0.02}
    """
    model_map = {"xgb": _XGB, "gb": _GB, "rf": _RF}
    if model not in model_map:
        raise ValueError(f"model must be one of {list(model_map.keys())}")

    X = _to_dataframe(input_data)
    proba = model_map[model].predict_proba(X)[0]
    return {label: float(prob) for label, prob in zip(LABEL_CLASSES, proba)}


# ---------------------------------------------------------------------------
# Interactive test when run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  ECG Arrhythmia Predictor")
    print("=" * 60)
    print(f"Paste {len(FEATURE_NAMES)} comma-separated values and press Enter.")
    print("Feature order:")
    for i, f in enumerate(FEATURE_NAMES, 1):
        print(f"  {i:02d}. {f}")
    print()

    while True:
        raw = input("Values: ").strip()
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != len(FEATURE_NAMES):
            print(f"  ⚠  Got {len(parts)} values, need {len(FEATURE_NAMES)}. Try again.\n")
            continue
        try:
            values = [float(p) for p in parts]
            break
        except ValueError as e:
            print(f"  ⚠  Non-numeric value found: {e}. Try again.\n")

    print("\n" + "-" * 60)
    result = predict(values)
    print(f"  XGBoost      : {result['xgb']}")
    print(f"  GradientBoost: {result['gb']}")
    print(f"  RandomForest : {result['rf']}")
    print(f"  Majority Vote: {result['majority']}")

    print("\n  Probabilities (XGBoost):")
    probs = predict_proba(values, model="xgb")
    for label, prob in sorted(probs.items(), key=lambda x: -x[1]):
        bar = "█" * int(prob * 30)
        print(f"    {label:<6} {prob*100:5.1f}%  {bar}")
    print("=" * 60)
