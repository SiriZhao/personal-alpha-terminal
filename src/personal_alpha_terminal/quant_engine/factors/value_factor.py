import pandas as pd


def value_score(frame: pd.DataFrame) -> pd.Series:
    components: list[pd.Series] = []
    for field in ("pe", "pb", "ps"):
        if field not in frame:
            continue
        valid = frame[field].where(frame[field] > 0)
        components.append((1 - valid.rank(pct=True, method="average")) * 100)
    return _mean_components(components, frame.index)


def _mean_components(components: list[pd.Series], index: pd.Index) -> pd.Series:
    if not components:
        return pd.Series(float("nan"), index=index, dtype=float)
    return pd.concat(components, axis=1).mean(axis=1, skipna=True)
