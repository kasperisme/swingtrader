import streamlit as st
from src.fundamentals import Fundamentals
import json

st.set_page_config(
    page_title="Scanning Tech sector in SP500",
    page_icon="⭐",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={
        "Get Help": "https://www.extremelycoolapp.com/help",
        "Report a bug": "https://www.extremelycoolapp.com/bug",
        "About": "# This is a header. This is an *extremely* cool app!",
    },
)


fundamentals = Fundamentals()


@st.cache_data
def get_data(sector: str = "Information Technology"):
    fundamentals.sector = sector
    fundamentals.get_ratios()
    df_ratios = fundamentals.ratio

    fundamentals.scale_ratios()
    df_scaled_ratios = fundamentals.ratio_scaled
    df_ranked_ratios = fundamentals.ratio_ranked
    df_ratio_masked = df_scaled_ratios[["symbol", "score"]].copy()

    df_ratios = df_ratios.merge(
        df_ratio_masked, left_on="symbol", right_on="symbol", how="left"
    )

    return df_ratios, df_scaled_ratios, df_ranked_ratios


sector = st.selectbox(
    "Which sector do you want to screen?", fundamentals.sector_options
)

df_ratios, df_scaled_ratios, df_ranked_ratios = get_data(sector)

df_ratios = df_ratios.reindex(sorted(df_scaled_ratios.columns), axis=1)

df_ratios = df_ratios.sort_values(by="score", ascending=False)

df_ratios = df_ratios.set_index("symbol")

ratio_logic = json.load(open("./input/ratio_logic.json", "r"))


st.write(
    """
# Fundamentals analysis
"""
)


st.write(
    """
## Ratios
"""
)

table = st.dataframe()

ticker = st.selectbox("Select a ticker to show its ranking", df_ratios.index)


tickertable = st.dataframe()

st.json(ratio_logic)


table.dataframe(df_ratios)

ticker_rank = df_ranked_ratios.loc[ticker]
ticker_rank = ticker_rank.sort_values(ascending=True)

tickertable.dataframe(ticker_rank)
