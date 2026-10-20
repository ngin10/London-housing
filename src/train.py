"""Train a LightGBM price model with a time-based holdout.

Usage:
    python -m src.train --test-months 3
"""
import argparse
import json

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error

from src.build_dataset import OUT as DATA_PATH
from src.config import OUTPUT_DIR, RANDOM_STATE
from src.features import CATEGORICAL, feature_columns


def time_split(df: pd.DataFrame, test_months: int):
    months = sorted(df["month"].unique())
    cutoff = months[-test_months]
    return df[df["month"] < cutoff], df[df["month"] >= cutoff], cutoff


def evaluate(y_true_price: np.ndarray, y_pred_price: np.ndarray) -> dict:
    ape = np.abs(y_pred_price - y_true_price) / y_true_price
    return {
        "MAE_gbp": float(mean_absolute_error(y_true_price, y_pred_price)),
        "MAPE": float(ape.mean()),
        "median_APE": float(np.median(ape)),
        "within_10pct": float((ape <= 0.10).mean()),
        "within_20pct": float((ape <= 0.20).mean()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-months", type=int, default=3)
    args = parser.parse_args()

    df = pd.read_parquet(DATA_PATH)
    for c in CATEGORICAL:
        df[c] = df[c].astype("category")
    features = feature_columns(df)
    train, test, cutoff = time_split(df, args.test_months)
    print(f"Train: {len(train):,} rows | Test: {len(test):,} rows (from {cutoff})")

    # Last 10% of training period as validation for early stopping
    val_cut = train["date"].quantile(0.9)
    tr, va = train[train["date"] < val_cut], train[train["date"] >= val_cut]

    model = lgb.LGBMRegressor(
        n_estimators=5000, learning_rate=0.03, num_leaves=127,
        min_child_samples=40, subsample=0.8, subsample_freq=1,
        colsample_bytree=0.8, random_state=RANDOM_STATE, verbose=-1,
    )
    model.fit(tr[features], tr["log_price"],
              eval_set=[(va[features], va["log_price"])],
              callbacks=[lgb.early_stopping(200), lgb.log_evaluation(500)])

    pred = np.exp(model.predict(test[features]))
    # Baseline: previous-6-month sector median
    base = np.exp(test["postcode_sector_lag6m_log_price"]
                  .fillna(test["outward_code_lag6m_log_price"])
                  .fillna(train["log_price"].median()))

    results = {"model": evaluate(test["price"].values, pred),
               "baseline_sector_median": evaluate(test["price"].values, base.values),
               "n_train": len(train), "n_test": len(test), "test_from": str(cutoff),
               "best_iteration": int(model.best_iteration_)}
    print(json.dumps(results, indent=2))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "metrics.json").write_text(json.dumps(results, indent=2))
    model.booster_.save_model(str(OUTPUT_DIR / "lgbm_model.txt"))
    (pd.Series(model.feature_importances_, index=features, name="importance")
       .sort_values(ascending=False).to_csv(OUTPUT_DIR / "feature_importance.csv"))
    test.assign(pred_price=pred)[["transaction_id", "date", "postcode", "borough",
                                  "property_type", "price", "pred_price"]] \
        .to_csv(OUTPUT_DIR / "test_predictions.csv", index=False)
    print(f"Artifacts saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
