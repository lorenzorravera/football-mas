# Stub — no_control variant uses custom SQL only, not the function registry.
import pandas as pd

FUNCTION_REGISTRY = {}

def safe_call_function(func, params):
    return pd.DataFrame()
