import os
import numpy as np
import pandas as pd
import wfdb
from scipy.signal import butter, filtfilt
from concurrent.futures import ProcessPoolExecutor

from sklearn.utils.class_weight import compute_class_weight, compute_sample_weight
from sklearn.metrics import classification_report, accuracy_score
from xgboost import XGBClassifier

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLING_RATE = 360
WINDOW_BEFORE = 90
WINDOW_AFTER = 100

AAMI_MAPPING = {
    'N': 0, 'L': 0, 'R': 0, 'e': 0, 'j': 0,
    'A': 1, 'a': 1, 'J': 1, 'S': 1,
    'V': 2, 'E': 2,
    'F': 3,
    '/': 4, 'f': 4, 'Q': 4
}

# Standard De Chazal AAMI inter-patient partition
DS1_TRAIN_IDS = [
    '101', '106', '108', '109', '112', '114', '115', '116', '118', '119', '122',
    '124', '201', '203', '205', '207', '208', '209', '215', '220', '223', '230'
]

DS2_TEST_IDS = [
    '100', '103', '105', '111', '113', '117', '121', '123', '200', '202', '210',
    '212', '213', '214', '219', '221', '222', '228', '231', '232', '233', '234'
]

RECORD_IDS = DS1_TRAIN_IDS + DS2_TEST_IDS

# ---------------------------------------------------------------------------
# Signal processing helpers
# ---------------------------------------------------------------------------
def bandpass_filter(data, lowcut=0.5, highcut=45.0, fs=SAMPLING_RATE, order=2):
    nyquist = 0.5 * fs
    b, a = butter(order, [lowcut / nyquist, highcut / nyquist], btype='band')
    return filtfilt(b, a, data)


def normalize_signal(data):
    std = np.std(data)
    if std == 0:
        return data - np.mean(data)
    return (data - np.mean(data)) / std


def process_single_record(record_id, data_dir='./mitdb'):
    path = os.path.join(data_dir, record_id)
    if not os.path.exists(f"{path}.dat"):
        return [], [], []

    record = wfdb.rdrecord(path)
    annotation = wfdb.rdann(path, 'atr')

    signal = record.p_signal[:, 0]
    filtered_signal = bandpass_filter(signal)

    X_rec, y_rec, record_ids = [], [], []

    for peak, symbol in zip(annotation.sample, annotation.symbol):
        if symbol in AAMI_MAPPING:
            label = AAMI_MAPPING[symbol]
            if peak - WINDOW_BEFORE >= 0 and peak + WINDOW_AFTER < len(filtered_signal):
                segment = filtered_signal[peak - WINDOW_BEFORE : peak + WINDOW_AFTER]
                X_rec.append(normalize_signal(segment))
                y_rec.append(label)
                record_ids.append(record_id)

    return X_rec, y_rec, record_ids


# ---------------------------------------------------------------------------
# Step 1: Extract beats and save to CSV
# ---------------------------------------------------------------------------
def extract_and_save(data_dir='./mitdb', output_csv='mitbih_interpatient_processed.csv'):
    if not os.path.exists(data_dir):
        wfdb.dl_database('mitdb', dl_dir=data_dir)

    print("Extracting beats with Patient Record IDs...")
    X, y, records = [], [], []

    with ProcessPoolExecutor() as executor:
        futures = [executor.submit(process_single_record, rid, data_dir) for rid in RECORD_IDS]
        for future in futures:
            X_rec, y_rec, r_ids = future.result()
            X.extend(X_rec)
            y.extend(y_rec)
            records.extend(r_ids)

    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.int64)

    feature_cols = [f'sample_{i}' for i in range(X.shape[1])]
    df = pd.DataFrame(X, columns=feature_cols)
    df['label'] = y
    df['record_id'] = records

    df.to_csv(output_csv, index=False)
    print(f"Saved to '{output_csv}' successfully!")
    return output_csv


# ---------------------------------------------------------------------------
# Step 2: Build inter-patient train / val / test splits
# ---------------------------------------------------------------------------
def build_splits(csv_path='mitbih_interpatient_processed.csv'):
    df = pd.read_csv(csv_path)
    df['record_id'] = df['record_id'].astype(str)

    # 4 DS1 patients held out strictly for validation
    VAL_PATIENTS   = ['118', '119', '208', '209']
    TRAIN_PATIENTS = [p for p in DS1_TRAIN_IDS if p not in VAL_PATIENTS]

    train_df = df[df['record_id'].isin(TRAIN_PATIENTS)]
    val_df   = df[df['record_id'].isin(VAL_PATIENTS)]
    test_df  = df[~df['record_id'].isin(DS1_TRAIN_IDS)]   # All DS2 patients

    X_train = train_df.drop(columns=['label', 'record_id']).values.astype(np.float32)
    y_train = train_df['label'].values.astype(np.int64)

    X_val   = val_df.drop(columns=['label', 'record_id']).values.astype(np.float32)
    y_val   = val_df['label'].values.astype(np.int64)

    X_test  = test_df.drop(columns=['label', 'record_id']).values.astype(np.float32)
    y_test  = test_df['label'].values.astype(np.int64)

    print("\nDataset Split Summary:")
    print(f" - Train Set:      {X_train.shape[0]} beats ({len(TRAIN_PATIENTS)} Patients)")
    print(f" - Validation Set: {X_val.shape[0]} beats ({len(VAL_PATIENTS)} Patients)")
    print(f" - Test Set:       {X_test.shape[0]} beats (Unseen DS2 Patients)")

    return X_train, y_train, X_val, y_val, X_test, y_test


# ---------------------------------------------------------------------------
# Step 3: Train XGBoost
# ---------------------------------------------------------------------------
def train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test,
                  model_dir='saved_models'):
    os.makedirs(model_dir, exist_ok=True)

    class_names = [
        'N (Normal)', 'S (Supraventricular)', 'V (Ventricular)',
        'F (Fusion)', 'Q (Unknown)'
    ]

    # Compute sample weights to handle class imbalance
    xgb_sample_weights = compute_sample_weight('balanced', y_train)

    print("\n" + "=" * 50)
    print("TRAINING: XGBoost Classifier")
    print("=" * 50)

    xgb_model = XGBClassifier(
        n_estimators=300,
        learning_rate=0.08,
        max_depth=6,
        objective='multi:softprob',
        num_class=5,
        tree_method='hist',
        early_stopping_rounds=10,
        random_state=42
    )

    xgb_model.fit(
        X_train, y_train,
        sample_weight=xgb_sample_weights,
        eval_set=[(X_val, y_val)],
        verbose=False
    )

    model_path = os.path.join(model_dir, 'ecg_xgboost.json')
    xgb_model.save_model(model_path)
    print(f"Model saved to '{model_path}'")

    # Evaluate
    y_pred   = xgb_model.predict(X_test)
    y_train_pred = xgb_model.predict(X_train)
    y_val_pred   = xgb_model.predict(X_val)

    print(f"\nXGBoost Best Iteration : {xgb_model.best_iteration}")
    print(f"Train Accuracy         : {accuracy_score(y_train, y_train_pred):.4f}")
    print(f"Validation Accuracy    : {accuracy_score(y_val, y_val_pred):.4f}")
    print(f"Test Accuracy          : {accuracy_score(y_test, y_pred):.4f}")
    print(classification_report(y_test, y_pred, target_names=class_names))

    return xgb_model


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    csv_path = 'mitbih_interpatient_processed.csv'

    # Only re-extract if the processed CSV doesn't already exist
    if not os.path.exists(csv_path):
        extract_and_save(data_dir='./mitdb', output_csv=csv_path)

    X_train, y_train, X_val, y_val, X_test, y_test = build_splits(csv_path)
    train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test)
