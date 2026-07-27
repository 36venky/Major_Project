import serial
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from collections import deque
from datetime import datetime
import os
import time

# =====================================
# Configuration
# =====================================
PORT = "COM6"
BAUD_RATE = 9600
CSV_FILE = r"Trail\ecg_data.csv"

ADC_REF = 5.0
ADC_RESOLUTION = 1023

WINDOW_SIZE = 500      # Number of samples visible

# =====================================
# Connect to Arduino
# =====================================
try:
    ser = serial.Serial(PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    ser.reset_input_buffer()
    print(f"Connected to {PORT}")
except serial.SerialException as e:
    import sys
    # List available ports to help the user pick the right one
    from serial.tools import list_ports
    available = [p.device for p in list_ports.comports()]
    print(f"ERROR: Could not open {PORT} — {e}")
    print(f"Available ports: {available if available else 'None detected (is the device plugged in?)'}")
    sys.exit(1)

rows = []

# Rolling buffer for plotting
x_data = deque(maxlen=WINDOW_SIZE)
y_data = deque(maxlen=WINDOW_SIZE)

sample_no = 0

# =====================================
# Plot Setup
# =====================================
fig, ax = plt.subplots(figsize=(12, 5))

line, = ax.plot([], [], linewidth=1)

ax.set_title("Real-Time ECG")
ax.set_xlabel("Samples")
ax.set_ylabel("Voltage (mV)")

ax.set_ylim(0, 5000)
ax.set_xlim(0, WINDOW_SIZE)

ax.grid(True)


def update(frame):

    global sample_no, rows

    while ser.in_waiting:

        line_data = ser.readline().decode(errors="ignore").strip()

        if not line_data:
            continue

        if line_data == "!":
            continue

        try:
            adc_value = int(line_data)

            voltage_mv = (adc_value * ADC_REF * 1000) / ADC_RESOLUTION

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            rows.append({
                "Timestamp": timestamp,
                "ADC_Value": adc_value,
                "Voltage_mV": round(voltage_mv, 3)
            })

            sample_no += 1

            x_data.append(sample_no)
            y_data.append(voltage_mv)

            # Save every 100 samples
            if len(rows) >= 100:

                df = pd.DataFrame(rows)

                df.to_csv(
                    CSV_FILE,
                    mode="a",
                    index=False,
                    header=not os.path.exists(CSV_FILE)
                )

                rows.clear()

        except ValueError:
            continue

    line.set_data(x_data, y_data)

    if sample_no > WINDOW_SIZE:
        ax.set_xlim(sample_no - WINDOW_SIZE, sample_no)
    else:
        ax.set_xlim(0, WINDOW_SIZE)

    return line,


ani = FuncAnimation(
    fig,
    update,
    interval=20,
    blit=True,
    cache_frame_data=False
)

plt.show()

# Save remaining samples after closing plot
if rows:
    df = pd.DataFrame(rows)
    df.to_csv(
        CSV_FILE,
        mode="a",
        index=False,
        header=not os.path.exists(CSV_FILE)
    )

ser.close()