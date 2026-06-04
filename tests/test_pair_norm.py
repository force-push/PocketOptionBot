from telegram_feed.pair_norm import normalize_pair

def test_known_table_pairs():
    assert normalize_pair("AUD/USD OTC") == "AUDUSD_otc"
    assert normalize_pair("EUR/USD") == "EURUSD"

def test_generic_otc_pairs_not_in_table():
    assert normalize_pair("KES/USD OTC") == "KESUSD_otc"
    assert normalize_pair("SAR/CNY OTC") == "SARCNY_otc"
    assert normalize_pair("IRR/USD OTC") == "IRRUSD_otc"
    assert normalize_pair("OMR/CNY OTC") == "OMRCNY_otc"

def test_non_otc_generic():
    assert normalize_pair("MAD/USD") == "MADUSD"

def test_garbage_returns_none():
    assert normalize_pair("Start Autotrade") is None
    assert normalize_pair("") is None
