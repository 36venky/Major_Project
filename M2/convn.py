import pandas as pd

# Input and output files
input_file = "M2\data.csv"
output_file = "M2\data_converted.csv"

# Temporary calibration constants
ADC_BASELINE = 343
ADC_TO_MV = 0.00806

# Read CSV
df = pd.read_csv(input_file)

# Calculate ECG voltage in mV
df["ECG_mV"] = (df["ADC_Value"] - ADC_BASELINE) * ADC_TO_MV

# Save to a separate CSV
df.to_csv(output_file, index=False)

print("Conversion completed.")
print(f"Input file  : {input_file}")
print(f"Output file : {output_file}")
print(f"Total samples: {len(df)}")

# Show first few results
print("\nConverted data:")
print(df.head(20))