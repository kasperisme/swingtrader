from src import helpers
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd 

if 'trend_template' not in st.session_state:
    st.session_state["trend_template"]=[]

df = pd.DataFrame(st.session_state["trend_template"])

df = df.drop_duplicates(subset=["ticker"])

st.dataframe(df)