import streamlit as st

st.set_page_config(
    page_title="Hello",
    page_icon="👋",
)

st.write("# Welcome to swing-scanner")

st.sidebar.success("Select a demo above.")

st.markdown(
    """
    ## What is swing-scanner?
    swing-scanner is a tool to help you find stocks that are in a good position to swing trade.

    ## How does it work?
    1. Select a Daily chart from the menu to the left.
    2. The demo will show you a list of stocks that are in a good position to swing trade.
    3. You can then use this information to make your own trades.

    ## Method to the madness
    We use a combination of technical indicators to determine if a stock is in a good position to swing trade, these are primarily based on the Minervini trend template.

    ## Disclaimer
    This is not financial advice. Always do your own research before making any trades.
"""
)
