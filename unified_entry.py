# -*- coding: utf-8 -*-
"""Compatibility entrypoint for setups already targeting unified_entry.py.

The preferred existing Streamlit Cloud Main file path is now ``app.py``.
Both entrypoints run the same chat_ui.py and install the same server-side
OAuth endpoints. No Streamlit app deletion or domain change is required.
"""
import os

import streamlit as st
from starlette.middleware import Middleware
from starlette.routing import Route

from core.unified_web import BrokerReturnMiddleware, login_start, login_logout

os.environ['AGENT_UNIFIED_ENTRY_READY'] = '1'

app = st.App('chat_ui.py', routes=[
    Route('/pa-agent/auth/start', login_start, methods=['GET']),
    Route('/pa-agent/auth/logout', login_logout, methods=['GET']),
], middleware=[Middleware(BrokerReturnMiddleware)])
