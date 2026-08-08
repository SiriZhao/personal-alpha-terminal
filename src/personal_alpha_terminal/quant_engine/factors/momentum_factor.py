import pandas as pd


def momentum_score(frame: pd.DataFrame) -> pd.Series:
    components = [
        frame[field].rank(pct=True, method="average") * 100
        for field in ("momentum_12_1", "momentum_6m", "momentum_3m")
        if field in frame
    ]
    if not components:
        return pd.Series(float("nan"), index=frame.index, dtype=float)
    return pd.concat(components, axis=1).mean(axis=1, skipna=True)
