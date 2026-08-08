import pandas as pd


def quality_score(frame: pd.DataFrame) -> pd.Series:
    components = [
        frame[field].rank(pct=True, method="average") * 100
        for field in ("roe", "roic", "gross_margin")
        if field in frame
    ]
    if not components:
        return pd.Series(float("nan"), index=frame.index, dtype=float)
    return pd.concat(components, axis=1).mean(axis=1, skipna=True)


def growth_score(frame: pd.DataFrame) -> pd.Series:
    components = [
        frame[field].rank(pct=True, method="average") * 100
        for field in ("revenue_growth", "eps_growth")
        if field in frame
    ]
    if not components:
        return pd.Series(float("nan"), index=frame.index, dtype=float)
    return pd.concat(components, axis=1).mean(axis=1, skipna=True)
