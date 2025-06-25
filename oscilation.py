import strategies.models as models
import datetime
from src.fmp import fmp
import random
from scipy.signal import hilbert, find_peaks
import numpy as np
from dotenv import load_dotenv
import plotly.graph_objects as go
from plotly.subplots import make_subplots

load_dotenv()

m = models.models()
f = fmp()

startdate = datetime.datetime(2018, 1, 1)
enddate = datetime.datetime(2024, 10, 6)

df = f.daily_chart("^SPX", startdate.strftime(m.strf), enddate.strftime(m.strf))


def detect_decreasing_oscillations(signal, threshold=0.5, distance=21):
    # Step 1: Detect the peaks in the signal
    peaks, _ = find_peaks(signal, distance=distance)
    print(peaks)
    # Step 2: Check if the amplitude of peaks is decreasing
    decreasing_periods = []
    for i in range(1, len(peaks)):
        # Compare the current peak height to the previous one
        if (
            signal[peaks[i]] < signal[peaks[i - 1]]
            and (signal[peaks[i - 1]] - signal[peaks[i]]) > threshold
        ):
            decreasing_periods.append(
                peaks[i]
            )  # Mark the period of decreasing amplitude

    return decreasing_periods


peaks_20_periods = detect_decreasing_oscillations(
    df["close"], threshold=0.5, distance=20
)

valley_20_periods = detect_decreasing_oscillations(
    -df["close"], threshold=0.5, distance=20
)

extremes = valley_20_periods + peaks_20_periods

print(valley_20_periods)

print(peaks_20_periods)

print(sorted(extremes))

# find periods where no peaks or valleys are found
no_peaks_valleys = []

started = False
startindex = 0
for i in range(len(df)):
    if i not in extremes:
        if not started:
            started = True
            startindex = i
    else:
        if started:
            no_peaks_valleys.append((startindex, i))

        started = False

template = "plotly_dark"
fig = make_subplots(
    rows=3,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.03,
    subplot_titles=("OHLC", "Volume", "EPS slope"),
    row_width=[0.1, 0.1, 0.5],
)

fig.update_layout(
    template=template,
    yaxis_autorange=True,
    yaxis_fixedrange=False,
    xaxis_rangeslider_visible=False,
)

fig.add_trace(
    go.Candlestick(
        x=df["date"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
    ),
    row=1,
    col=1,
)

for i in no_peaks_valleys:
    fig.add_trace(
        go.Scatter(
            x=[df["date"].iloc[i[0]], df["date"].iloc[i[1]]],
            y=[df["low"].iloc[i[0]], df["high"].iloc[i[1]]],
        ),
        row=1,
        col=1,
    )

fig.show()
