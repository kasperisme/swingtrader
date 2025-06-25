import strategies.models as models
import datetime
from src.fmp import fmp
import random

f = fmp()
m = models.models()

symbols = [
    "PLMR",
    "NOW",
    "RYAN",
    "META",
    "KKR",
    "SFM",
    "PSN",
    "WING",
    "ESQ",
    "SPOT",
    "VERX",
]

symbols = ["MSFT", "AMZN", "META", "AAPL", "GOOGL", "NVDA", "TSLA"]

symbols = ["AAPL"]

startcapital = 100000
startdate = datetime.datetime(2018, 1, 1)
enddate = datetime.datetime(2024, 10, 6)

df_sp500 = f.daily_chart("^SPX", startdate.strftime(m.strf), enddate.strftime(m.strf))

endcapital = 0
for symbol in symbols:
    df = m.dataconstruct(
        symbol, datetime.datetime(2021, 1, 1), datetime.datetime(2024, 10, 6)
    )

    df, trades = m.apply_strategy(df, m.strategy_VPC_SMA)

    fig = m.get_graph(df)
    akktrade = 1
    for i in trades:
        akktrade = akktrade * (1 + i["pnl%"])

    if False:
        print("Symbol: ", symbol)
        print("Trades: ", len(trades))
        print("Akk. trade: ", akktrade)
        print("Buy and hold: ", df["close"].iloc[-1] / df["close"].iloc[0])

    endcapital = endcapital + (startcapital * akktrade)

print("End capital: ", endcapital)
print("Performance: ", endcapital / ((startcapital) * len(symbols)))
print("SP500: ", df_sp500["close"].iloc[-1] / df_sp500["close"].iloc[0])

df.to_excel("test.xlsx")

fig.show()
