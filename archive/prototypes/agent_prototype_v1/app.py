"""
Entry point for deployment platforms.
"""

import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "streamlit", "run", "streamlit_app.py"])