#!/usr/bin/env python3
"""Test script to verify ConfluenceEngine uses settings.min_signal_agreement"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from signals.confluence import ConfluenceEngine
from signals.base import BaseSignal
from signals.rsi import RSISignal
from config.settings import settings
from unittest.mock import AsyncMock
import pandas as pd
from datetime import datetime

def test_confluence_uses_settings():
    """Test that ConfluenceEngine uses settings value when min_agreement not provided"""
    
    # Create mock signals
    signals = [
        RSISignal(period=14),
        RSISignal(period=14),
        RSISignal(period=14),
    ]
    
    # Create engine WITHOUT explicit min_agreement (should use settings)
    engine = ConfluenceEngine(signals)
    
    print(f"Settings min_signal_agreement: {settings.min_signal_agreement}")
    print(f"Engine min_agreement: {engine.min_agreement}")
    
    # They should match
    assert engine.min_agreement == settings.min_signal_agreement, \
        f"Expected {settings.min_signal_agreement}, got {engine.min_agreement}"
    
    print("✓ Test passed: ConfluenceEngine uses settings value when min_agreement not provided")

def test_confluence_respects_explicit_value():
    """Test that ConfluenceEngine respects explicit min_agreement parameter"""
    
    signals = [
        RSISignal(period=14),
        RSISignal(period=14),
    ]
    
    # Create engine WITH explicit min_agreement (should use that value)
    explicit_value = 4
    engine = ConfluenceEngine(signals, min_agreement=explicit_value)
    
    print(f"Explicit min_agreement: {explicit_value}")
    print(f"Engine min_agreement: {engine.min_agreement}")
    
    # Should use explicit value, not settings
    assert engine.min_agreement == explicit_value, \
        f"Expected {explicit_value}, got {engine.min_agreement}"
    assert engine.min_agreement != settings.min_signal_agreement, \
        "Should not use settings value when explicit value provided"
    
    print("✓ Test passed: ConfluenceEngine respects explicit min_agreement value")

if __name__ == "__main__":
    print("Testing ConfluenceEngine settings usage...")
    print("=" * 50)
    
    test_confluence_uses_settings()
    test_confluence_respects_explicit_value()
    
    print("=" * 50)
    print("All tests passed! ✓")