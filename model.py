"""
ML Risk Prediction Model for Fire Safety Equipment Register
Uses scikit-learn RandomForestClassifier to predict equipment at risk of failing inspection.
"""

import os
import pickle
import numpy as np
from datetime import datetime

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'risk_model.pkl')
# On Vercel (read-only filesystem) fall back to /tmp which is writable
if not os.access(os.path.dirname(os.path.abspath(__file__)), os.W_OK):
    MODEL_PATH = '/tmp/risk_model.pkl'



def _build_feature_vector(eq):
    """Convert an equipment row (dict or sqlite3.Row) into a numeric feature vector."""
    age_days = eq['age_days'] or 0
    days_since_inspection = eq['days_since_inspection'] or 0
    days_until_due = eq['days_until_due'] or 0
    inspection_count = eq['inspection_count'] or 0
    fail_count = eq['fail_count'] or 0
    interval_months = eq['default_interval_months'] or 12

    fail_rate = fail_count / max(inspection_count, 1)

    return [
        float(age_days),
        float(days_since_inspection),
        float(days_until_due),
        float(inspection_count),
        float(fail_count),
        float(fail_rate),
        float(interval_months),
    ]


def predict_risk(equipment_rows):
    """
    Predict inspection risk for each equipment item.

    Parameters
    ----------
    equipment_rows : list of sqlite3.Row or dict-like
        Rows returned by get_equipment_for_prediction().

    Returns
    -------
    list of dict with keys:
        equipment_id, at_risk (bool), risk_probability (float 0-1), confidence (float 0-1)
    """
    results = []

    if not equipment_rows:
        return results

    model = _load_model()

    for eq in equipment_rows:
        eq_id = eq['equipment_id']
        features = _build_feature_vector(eq)

        if model is not None:
            try:
                proba = model.predict_proba([features])[0]
                # Class 1 = at_risk
                risk_prob = float(proba[1]) if len(proba) > 1 else 0.0
                at_risk = risk_prob >= 0.5
                confidence = float(max(proba))
            except Exception:
                risk_prob, at_risk, confidence = _heuristic_risk(eq)
        else:
            risk_prob, at_risk, confidence = _heuristic_risk(eq)

        results.append({
            'equipment_id': eq_id,
            'at_risk': at_risk,
            'risk_probability': round(risk_prob, 3),
            'confidence': round(confidence, 3),
        })

    return results


def _heuristic_risk(eq):
    """Simple rule-based fallback when no trained model is available."""
    days_until_due = eq['days_until_due'] or 0
    fail_count = eq['fail_count'] or 0
    inspection_count = eq['inspection_count'] or 1

    fail_rate = fail_count / max(inspection_count, 1)

    # Overdue or high fail rate → at risk
    if days_until_due < 0:
        risk_prob = min(0.9 + abs(days_until_due) / 365 * 0.1, 0.99)
    elif days_until_due <= 30:
        risk_prob = 0.6 + fail_rate * 0.3
    else:
        risk_prob = fail_rate * 0.4

    risk_prob = max(0.0, min(1.0, risk_prob))
    at_risk = risk_prob >= 0.5
    confidence = 0.7  # fixed heuristic confidence
    return risk_prob, at_risk, confidence


def train_model(equipment_rows, inspection_rows):
    """
    Train (or retrain) the RandomForest model using historical data.

    Labels equipment as 'at_risk' (1) if it has ever failed an inspection
    or is currently overdue.

    Parameters
    ----------
    equipment_rows : list of sqlite3.Row / dict-like
    inspection_rows : list of sqlite3.Row / dict-like

    Returns
    -------
    Trained model, or None if there is not enough data.
    """
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
    except ImportError:
        print("scikit-learn not installed – skipping model training.")
        return None

    if not equipment_rows or len(equipment_rows) < 5:
        print("Not enough equipment data to train model (need at least 5 records).")
        return None

    # Build failure lookup from inspection history
    fail_set = set()
    for insp in (inspection_rows or []):
        if insp['result'] in ('fail', 'needs_repair'):
            fail_set.add(insp['equipment_id'])

    X, y = [], []
    for eq in equipment_rows:
        features = _build_feature_vector(eq)
        days_until_due = eq['days_until_due'] or 0
        label = 1 if (eq['equipment_id'] in fail_set or days_until_due < 0) else 0
        X.append(features)
        y.append(label)

    X = np.array(X)
    y = np.array(y)

    # Need at least both classes to train
    if len(set(y)) < 2:
        print("Training data has only one class – using heuristic model.")
        return None

    try:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )
    except ValueError:
        X_train, y_train = X, y

    clf = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
    clf.fit(X_train, y_train)

    # Persist model — gracefully skip if filesystem is read-only (e.g. Vercel)
    try:
        with open(MODEL_PATH, 'wb') as f:
            pickle.dump(clf, f)
        print(f"Model trained on {len(X_train)} samples and saved to {MODEL_PATH}.")
    except OSError as e:
        print(f"Could not save model to disk ({e}); using in-memory model for this session.")

    return clf


def _load_model():
    """Load persisted model from disk, return None if not found or corrupt."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Could not load model: {e}")
        return None
