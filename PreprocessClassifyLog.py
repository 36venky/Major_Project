import os
import csv
from datetime import datetime
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt
from xgboost import XGBClassifier

# Ensure logs directory exists
os.makedirs("logs", exist_ok=True)

class ECGPreprocessor:

    def __init__(
        self,
        SamplingFreq=360,
        WindowB4Peak=90,
        WindowAfPeak=100,
        LowerBound=0.5,
        UpperBound=45.0,
        Order=2
    ):
        self.SamplingFreq = SamplingFreq
        self.WindowB4Peak = WindowB4Peak
        self.WindowAfPeak = WindowAfPeak
        self.LowerBound = LowerBound
        self.UpperBound = UpperBound
        self.Order = Order

        # Initialize CSV log files with headers
        self._initialize_csv_logs()

        # Load trained XGBoost model once
        print("[INFO] Loading trained XGBoost model from 'saved_models/ecg_xgboost.json'...")
        self.Model = XGBClassifier()
        self.Model.load_model("saved_models/ecg_xgboost.json")
        print("[INFO] XGBoost model loaded successfully.")

        # AAMI class names
        self.ClassNames = {
            0: "N",
            1: "S",
            2: "V",
            3: "F",
            4: "Q"
        }

    def _initialize_csv_logs(self):
        """Create or initialize CSV log files with proper column headers."""
        
        # 1. Butterworth Filter Log
        self.filter_csv = "logs/butterworth_filter_log.csv"
        with open(self.filter_csv, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "InputSamples", "OutputSamples", "LowerBound_Hz", "UpperBound_Hz", "Order"])

        # 2. Pan-Tompkins Detector Log
        self.pt_csv = "logs/pan_tompkins_log.csv"
        with open(self.pt_csv, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "InitialSignalLevel", "NoiseLevel", "Threshold1", "Threshold2", "TotalCandidatePeaks", "RPeaksDetected"])

        # 3. Beat Extraction Log
        self.extract_csv = "logs/beat_extraction_log.csv"
        with open(self.extract_csv, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "BeatIndex", "RPeakIndex", "Mean", "Std", "Status"])

        # 4. XGBoost Predictions Log
        self.predict_csv = "logs/xgboost_predictions_log.csv"
        with open(self.predict_csv, mode="w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "BeatIndex", "RPeakIndex", "ClassID", "RiskLevel"])

    def _log_row(self, filepath, row_data):
        """Helper to append a row to a specific CSV log."""
        with open(filepath, mode="a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row_data)

    # =========================================================
    # Butterworth bandpass filter
    # =========================================================
    def ButterWorthFilter(self, Signal):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [1] Applying Butterworth bandpass filter...")
        
        NyquistFreq = self.SamplingFreq / 2
        Coeff1, Coeff2 = butter(
            self.Order,
            [self.LowerBound / NyquistFreq, self.UpperBound / NyquistFreq],
            btype="band"
        )
        FilteredSignal = filtfilt(Coeff1, Coeff2, Signal)
        
        # Log to CSV
        self._log_row(self.filter_csv, [timestamp, len(Signal), len(FilteredSignal), self.LowerBound, self.UpperBound, self.Order])
        return FilteredSignal

    # =========================================================
    # Pan-Tompkins feature extraction
    # =========================================================
    def PanTompkinsFeature(self, Signal):
        Derivative = np.diff(Signal, prepend=Signal[0])
        Squared = Derivative ** 2
        IntegrationWindow = int(0.15 * self.SamplingFreq)
        Kernel = np.ones(IntegrationWindow) / IntegrationWindow
        Integral = np.convolve(Squared, Kernel, mode="same")
        return Integral

    # =========================================================
    # Pan-Tompkins R-peak detector
    # =========================================================
    def PanTompkinsDetector(self, Signal):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [3] Detecting R-peaks...")
        
        Integral = self.PanTompkinsFeature(Signal)

        InitialLength = min(len(Integral), int(2 * self.SamplingFreq))
        InitialSignal = Integral[:InitialLength]

        SignalLevel = 0.25 * np.max(InitialSignal) if len(InitialSignal) > 0 else 0
        NoiseLevel = 0.5 * np.mean(InitialSignal) if len(InitialSignal) > 0 else 0

        Threshold1 = NoiseLevel + 0.25 * (SignalLevel - NoiseLevel)
        Threshold2 = 0.5 * Threshold1

        Peaks = []
        for i in range(1, len(Integral) - 1):
            if Integral[i] > Integral[i - 1] and Integral[i] >= Integral[i + 1]:
                Peaks.append(i)
        Peaks = np.asarray(Peaks, dtype=int)

        ActualPeaks = []
        RIntervals = []
        CoolDown = int(0.20 * self.SamplingFreq)
        LastPeak = -np.inf

        for Index in Peaks:
            PeakValue = Integral[Index]
            if PeakValue >= Threshold1:
                if Index - LastPeak < CoolDown:
                    continue
                ActualPeaks.append(Index)
                if LastPeak != -np.inf:
                    Interval = Index - LastPeak
                    RIntervals.append(Interval)
                    if len(RIntervals) > 8:
                        RIntervals.pop(0)
                LastPeak = Index
                SignalLevel = 0.125 * PeakValue + 0.875 * SignalLevel
            else:
                NoiseLevel = 0.125 * PeakValue + 0.875 * NoiseLevel

            Threshold1 = NoiseLevel + 0.25 * (SignalLevel - NoiseLevel)
            Threshold2 = 0.5 * Threshold1

        SearchBackPeaks = []
        if len(ActualPeaks) >= 2:
            for i in range(1, len(ActualPeaks)):
                PreviousPeak = ActualPeaks[i - 1]
                CurrentPeak = ActualPeaks[i]
                CurrentInterval = CurrentPeak - PreviousPeak

                if len(RIntervals) > 0:
                    AverageRR = np.mean(RIntervals)
                else:
                    AverageRR = CurrentInterval

                if CurrentInterval > 1.66 * AverageRR:
                    Candidates = Peaks[(Peaks > PreviousPeak) & (Peaks < CurrentPeak)]
                    BestPeak = None
                    BestValue = -np.inf

                    for Candidate in Candidates:
                        CandidateValue = Integral[Candidate]
                        if CandidateValue > Threshold2 and CandidateValue > BestValue:
                            BestValue = CandidateValue
                            BestPeak = Candidate

                    if BestPeak is not None:
                        SearchBackPeaks.append(BestPeak)

        ActualPeaks.extend(SearchBackPeaks)
        ActualPeaks = sorted(set(ActualPeaks))

        RPeaks = []
        SearchRadius = int(0.08 * self.SamplingFreq)

        for Peak in ActualPeaks:
            Start = max(0, Peak - SearchRadius)
            End = min(len(Signal), Peak + SearchRadius + 1)
            LocalRegion = Signal[Start:End]
            if len(LocalRegion) == 0:
                continue
            RPeak = Start + np.argmax(LocalRegion)

            if not RPeaks or (RPeak - RPeaks[-1] >= CoolDown):
                RPeaks.append(RPeak)

        RPeaks = np.asarray(RPeaks, dtype=int)
        
        # Log Pan-Tompkins summary to CSV
        self._log_row(self.pt_csv, [timestamp, round(SignalLevel, 4), round(NoiseLevel, 4), round(Threshold1, 4), round(Threshold2, 4), len(Peaks), len(RPeaks)])
        
        print(f"    R-peaks detected : {len(RPeaks)}")
        return RPeaks, Integral

    # =========================================================
    # Extract and normalize 190-sample beats
    # =========================================================
    def ExtractBeats(self, Signal, RPeaks):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [4] Extracting and normalizing ECG beats...")
        
        Beats = []
        ValidRPeaks = []
        TotalSamples = self.WindowB4Peak + self.WindowAfPeak

        for i, RPeak in enumerate(RPeaks):
            Start = RPeak - self.WindowB4Peak
            End = RPeak + self.WindowAfPeak

            if Start < 0 or End > len(Signal):
                self._log_row(self.extract_csv, [timestamp, i + 1, RPeak, 0.0, 0.0, "Skipped_OutOfBounds"])
                continue

            Beat = Signal[Start:End]
            if len(Beat) != TotalSamples:
                self._log_row(self.extract_csv, [timestamp, i + 1, RPeak, 0.0, 0.0, "Skipped_InvalidLength"])
                continue

            Mean = np.mean(Beat)
            Std = np.std(Beat)

            if Std == 0:
                NormalizedBeat = Beat - Mean
            else:
                NormalizedBeat = (Beat - Mean) / Std

            Beats.append(NormalizedBeat)
            ValidRPeaks.append(RPeak)
            
            # Log individual beat extraction metrics to CSV
            self._log_row(self.extract_csv, [timestamp, len(Beats), RPeak, round(Mean, 4), round(Std, 4), "Valid"])

        X = np.asarray(Beats, dtype=np.float32)
        print(f"    Valid beats      : {len(X)}")

        return X, np.asarray(ValidRPeaks, dtype=int)

    # =========================================================
    # Predict using trained XGBoost model
    # =========================================================
    def Predict(self, Signal):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("=" * 60)
        print(f"[{timestamp}] STARTING ECG XGBOOST PREDICTION PIPELINE")
        print("=" * 60)

        FilteredSignal = self.ButterWorthFilter(Signal)
        RPeaks, Integral = self.PanTompkinsDetector(FilteredSignal)
        X, ValidRPeaks = self.ExtractBeats(FilteredSignal, RPeaks)

        if X.shape[0] == 0:
            print("[WARNING] No valid ECG beats detected.")
            return {
                "predictions": np.empty(0, dtype=np.int64),
                "risk_levels": [],
                "r_peaks": ValidRPeaks
            }

        print(f"[{timestamp}] [5] Running XGBoost model inference...")
        Predictions = self.Model.predict(X)
        Predictions = np.asarray(Predictions, dtype=np.int64)

        ClassPredictions = [
            self.ClassNames[int(Prediction)]
            for Prediction in Predictions
        ]

        print(f"[{timestamp}] [6] Logging predictions to CSV and summary:")
        for i in range(len(Predictions)):
            # Log prediction to CSV
            self._log_row(self.predict_csv, [timestamp, i + 1, ValidRPeaks[i], int(Predictions[i]), ClassPredictions[i]])
            print(
                f"    Beat {i + 1:3d} | "
                f"R-peak = {ValidRPeaks[i]:6d} | "
                f"Risk Level = {ClassPredictions[i]}"
            )

        print("=" * 60)
        print("PREDICTION COMPLETE")
        print("=" * 60)

        return {
            "predictions": Predictions,
            "risk_levels": ClassPredictions,
            "r_peaks": ValidRPeaks,
            "filtered_signal": FilteredSignal,
            "integrated_signal": Integral,
            "beats": X
        }

    # =========================================================
    # Plot ECG preprocessing stages
    # =========================================================
    def PlotProcessing(
        self,
        Signal,
        FilteredSignal,
        Integral,
        RPeaks,
        Beats=None
    ):
        Time = np.arange(len(Signal)) / self.SamplingFreq
        HasBeats = Beats is not None and len(Beats) > 0
        NumPlots = 4 if HasBeats else 3

        fig, axes = plt.subplots(NumPlots, 1, figsize=(14, 3 * NumPlots))

        axes[0].plot(Time, Signal, color="tab:blue")
        axes[0].set_title("Raw ECG Signal")
        axes[0].set_ylabel("Amplitude")
        axes[0].set_xlabel("Time (seconds)")
        axes[0].grid(True)

        axes[1].plot(Time, FilteredSignal, color="tab:orange")
        axes[1].scatter(
            RPeaks / self.SamplingFreq,
            FilteredSignal[RPeaks],
            color="red",
            marker="o",
            label="R-Peaks"
        )
        axes[1].set_title("Filtered ECG with Detected R-Peaks")
        axes[1].set_ylabel("Amplitude")
        axes[1].set_xlabel("Time (seconds)")
        axes[1].grid(True)
        axes[1].legend(loc="upper right")

        axes[2].plot(Time, Integral, color="tab:green")
        axes[2].set_title("Pan-Tompkins Moving-Window Integration")
        axes[2].set_ylabel("Integrated Energy")
        axes[2].set_xlabel("Time (seconds)")
        axes[2].grid(True)

        if HasBeats:
            for Beat in Beats:
                axes[3].plot(Beat, alpha=0.3, color="tab:purple")
            axes[3].set_title("Extracted and Normalized 190-Sample Beats")
            axes[3].set_xlabel("Sample Index")
            axes[3].set_ylabel("Normalized Amplitude")
            axes[3].grid(True)

        plt.tight_layout()
        plt.show()

    # =========================================================
    # Process CSV file
    # =========================================================
    def PredictFromCSV(self, CSVPath, TargetColumn="Voltage_mV"):
        print(f"Loading ECG data from CSV: '{CSVPath}'...")
        Data = pd.read_csv(CSVPath)

        if TargetColumn in Data.columns:
            Signal = Data[TargetColumn].values
        elif "ADC_Value" in Data.columns:
            Signal = Data["ADC_Value"].values
        else:
            raise ValueError(
                f"Column '{TargetColumn}' or 'ADC_Value' not found in CSV."
            )

        Signal = np.asarray(Signal, dtype=np.float64)
        Result = self.Predict(Signal)

        if len(Result["r_peaks"]) > 0:
            self.PlotProcessing(
                Signal,
                Result["filtered_signal"],
                Result["integrated_signal"],
                Result["r_peaks"],
                Result["beats"]
            )

        return Result

    def __call__(self, Signal):
        return self.Predict(Signal)


if __name__ == "__main__":
    Preprocessor = ECGPreprocessor()
    Result = Preprocessor.PredictFromCSV("data.csv", TargetColumn="Voltage_mV")