"""Numeric validation for the original cBot indicator display."""
import math

def number(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
