import pandas as pd

from src.clean import clean, normalise_postcode
from src.config import PPD_COLUMNS


def _row(**kw):
    base = dict(zip(PPD_COLUMNS, [
        "{A1}", "500000", "2023-05-01 00:00", "sw1a1aa", "F", "N", "L", "1", "",
        "DOWNING ST", "", "LONDON", "CITY OF WESTMINSTER", "GREATER LONDON", "A", "A"]))
    base.update(kw)
    return base


def test_normalise_postcode():
    s = pd.Series(["sw1a1aa", " E1  6AN ", "n19gu"])
    assert normalise_postcode(s).tolist() == ["SW1A 1AA", "E1 6AN", "N1 9GU"]


def test_clean_filters():
    df = pd.DataFrame([
        _row(),
        _row(transaction_id="{A2}", ppd_category_type="B"),   # non-standard sale
        _row(transaction_id="{A3}", county="KENT"),           # outside London
        _row(transaction_id="{A4}", property_type="O"),       # other
        _row(transaction_id="{A5}", price="500"),             # too cheap
        _row(transaction_id="{A1}"),                          # duplicate
    ])
    out = clean(df)
    assert out["transaction_id"].tolist() == ["{A1}"]
    assert out.loc[0, "postcode"] == "SW1A 1AA"
    assert out.loc[0, "property_type"] == "Flat/Maisonette"
    assert out.loc[0, "postcode_sector"] == "SW1A 1"
    assert out.loc[0, "outward_code"] == "SW1A"
