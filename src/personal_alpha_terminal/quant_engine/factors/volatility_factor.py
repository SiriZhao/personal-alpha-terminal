import pandas as pd


def low_risk_score(frame: pd.DataFrame) -> pd.Series:
    components: list[pd.Series] = []
    if "volatility" in frame:
        valid = frame["volatility"].where(frame["volatility"] >= 0)
        components.append((1 - valid.rank(pct=True, method="average")) * 100)
    if "max_drawdown" in frame:
        # Drawdowns are negative; a less-negative value is safer and should rank higher.
        components.append(frame["max_drawdown"].rank(pct=True, method="average") * 100)
    if not components:
        return pd.Series(float("nan"), index=frame.index, dtype=float)
    return pd.concat(components, axis=1).mean(axis=1, skipna=True)
