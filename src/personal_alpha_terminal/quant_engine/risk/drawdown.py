import pandas as pd


def drawdown_series(equity: pd.Series) -> pd.Series:
    clean = equity.astype(float)
    if clean.empty or bool((clean <= 0).any()):
        raise ValueError("drawdown requires positive portfolio values")
    return clean / clean.cummax() - 1


def maximum_drawdown(equity: pd.Series) -> float:
    return float(drawdown_series(equity).min())
