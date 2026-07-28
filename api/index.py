"""
Vercel WSGI entry point for the Fire Safety Register Flask app.
Vercel Python serverless runtime looks for an `app` WSGI callable
at api/index.py.
"""

import sys
import os

# Make the project root importable so that app.py, database.py, model.py
# can all be found when Vercel runs this file from the api/ subdirectory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app import app          # noqa: E402  (must come after sys.path fix)

# Vercel expects the WSGI callable to be named `app`.
# Flask's application object IS a WSGI callable, so no extra wrapper needed.
