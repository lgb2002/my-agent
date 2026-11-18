"""Streamlit Cloud ASGI entrypoint for ProjectAgain v0.37 unified login.

Change the Streamlit Cloud Main file path from app.py to unified_entry.py when
activating the new flow. Keep app.py intact for the legacy OIDC/Broker fallback.
"""
import os

import streamlit as st
from starlette.middleware import Middleware
from starlette.routing import Route

from core.unified_web import BrokerReturnMiddleware, login_start, login_logout

# Only the actual secure ASGI entrypoint may activate the unified cookie path.
os.environ['AGENT_UNIFIED_ENTRY_READY'] = '1'
app = st.App('app.py', routes=[
    Route('/pa-agent/auth/start', login_start, methods=['GET']),
    Route('/pa-agent/auth/logout', login_logout, methods=['GET']),
], middleware=[Middleware(BrokerReturnMiddleware)])
