# -*- coding: utf-8 -*-
"""ProjectAgain Agent — stable Streamlit Cloud main file (v0.19.4).

Deploy with Main file path ``app.py``. Streamlit discovers this st.App ASGI
entrypoint, registers secure unified-login routes, and runs the unchanged
chat UI located at ``chat_ui.py``. Do not import or execute chat_ui.py here:
Streamlit must render it in its own script context.
"""
import os

import streamlit as st
from starlette.middleware import Middleware
from starlette.routing import Route

from core.unified_web import BrokerReturnMiddleware, login_start, login_logout, process_callback

# Set only by the ASGI launcher; the cookie flow is never enabled by chat_ui
# running independently with `streamlit run chat_ui.py`.
os.environ['AGENT_UNIFIED_ENTRY_READY'] = '1'

app = st.App('chat_ui.py', routes=[
    Route('/pa-agent/auth/start', login_start, methods=['GET']),
    Route('/pa-agent/auth/callback', process_callback, methods=['GET']),
    Route('/pa-agent/auth/logout', login_logout, methods=['GET']),
], middleware=[Middleware(BrokerReturnMiddleware)])
