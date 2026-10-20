"""Central configuration: paths, URLs and column definitions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "outputs"

# HM Land Registry Price Paid Data (yearly files, no header row)
PPD_URL = (
    "http://prod.publicdata.landregistry.gov.uk.s3-website-eu-west-1.amazonaws.com/"
    "pp-{year}.csv"
)
PPD_COLUMNS = [
    "transaction_id", "price", "date_of_transfer", "postcode", "property_type",
    "old_new", "duration", "paon", "saon", "street", "locality", "town_city",
    "district", "county", "ppd_category_type", "record_status",
]

# Main input: London sales already joined with location and crime features
SALES_FILE = RAW_DIR / "london_sales_final.csv"
SALES_COLUMN_MAP = {
    "unique_id": "transaction_id", "price_paid": "price", "deed_date": "date_of_transfer",
    "new_build": "old_new", "estate_type": "duration",
    "transaction_category": "ppd_category_type", "town": "town_city",
}

# postcodes.io bulk lookup (max 100 postcodes per request)
POSTCODES_IO_URL = "https://api.postcodes.io/postcodes"
POSTCODES_IO_BATCH = 100

# Optional: EPC certificates, aggregated to postcode level
# (download from https://epc.opendatacommunities.org/ - free registration required)
EPC_FILE = RAW_DIR / "epc_certificates.csv"

LONDON_COUNTY = "GREATER LONDON"
MIN_PRICE = 10_000
MAX_PRICE = 20_000_000

PROPERTY_TYPE_MAP = {"D": "Detached", "S": "Semi-detached", "T": "Terraced",
                     "F": "Flat/Maisonette", "O": "Other"}
DURATION_MAP = {"F": "Freehold", "L": "Leasehold", "U": "Unknown"}

RANDOM_STATE = 42
