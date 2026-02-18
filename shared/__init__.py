"""
Shared package for the Offline Payment Protocol.
"""
import os
import sys

# Ensure the project root is on sys.path so cross-package imports work
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
