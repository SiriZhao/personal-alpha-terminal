from typing import Any

import plotly.graph_objects as go
import plotly.io as pio

from personal_alpha_terminal.analysis.conditional_probability.schemas import (
    ProbabilityEstimate,
)
from personal_alpha_terminal.analysis.event_study.schemas import EventStatistic
from personal_alpha_terminal.analysis.factors.schemas import (
    FactorBacktestPeriodResult,
    FactorStockScore,
)
from personal_alpha_terminal.analysis.lead_lag.schemas import PairEvidence
from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphEdgeMetric,
    GraphNodeMetric,
)
from personal_alpha_terminal.analysis.market_regime.schemas import (
    MarketRegimePoint,
    RegimeCalibrationReport,
    RegimeName,
)
from personal_alpha_terminal.analysis.relationships.schemas import (
    CorrelationObservation,
    EntityOption,
)
from personal_alpha_terminal.dashboard.schemas import (
    Exposure,
    MarketIndexSnapshot,
    PricePoint,
    SeriesPoint,
)
from personal_alpha_terminal.portfolio.schemas import (
    RiskSeriesPoint,
    StressTestResult,
)
from personal_alpha_terminal.scenario_simulator.schemas import (
    ScenarioComparison,
    ScenarioResult,
)

ACCENT = "#6C8CFF"
POSITIVE = "#30D6A3"
VOLUME = "#71809D"
NEGATIVE = "#FF617D"
PURPLE = "#A78BFA"
PANEL = "rgba(13, 19, 34, 0)"
GRID = "rgba(148, 163, 184, .10)"
TEXT = "#E9EEF8"
MUTED = "#8D9AB2"

pio.templates["pat_terminal"] = go.layout.Template(
    layout=go.Layout(
        paper_bgcolor=PANEL,
        plot_bgcolor=PANEL,
        font={"family": "Inter, ui-sans-serif, system-ui", "color": TEXT, "size": 12},
        colorway=[ACCENT, POSITIVE, PURPLE, "#F6C85F", NEGATIVE],
        hoverlabel={"bgcolor": "#11192B", "bordercolor": "#26334D", "font_color": TEXT},
        xaxis={"gridcolor": GRID, "zerolinecolor": GRID, "tickfont_color": MUTED},
        yaxis={"gridcolor": GRID, "zerolinecolor": GRID, "tickfont_color": MUTED},
    )
)
pio.templates.default = "pat_terminal"


def market_change_chart(snapshots: tuple[MarketIndexSnapshot, ...]) -> Any:
    figure = go.Figure(
        data=[
            go.Bar(
                x=[item.instrument.symbol for item in snapshots],
                y=[item.change_pct if item.change_pct is not None else 0 for item in snapshots],
                marker={
                    "color": [
                        POSITIVE
                        if (item.change_pct or 0) >= 0
                        else NEGATIVE
                        for item in snapshots
                    ],
                    "line": {"width": 0},
                },
                customdata=[
                    [
                        item.instrument.name,
                        float(item.close),
                        item.currency,
                        item.volume,
                        item.date.isoformat(),
                        item.source,
                    ]
                    for item in snapshots
                ],
                hovertemplate=(
                    "%{customdata[0]}<br>%{customdata[2]} %{customdata[1]:,.2f}"
                    "<br>日涨跌 %{y:+.2%}<br>成交量 %{customdata[3]:,.0f}"
                    "<br>%{customdata[4]} · %{customdata[5]}<extra></extra>"
                ),
            )
        ]
    )
    figure.add_hline(y=0, line_color=GRID, line_width=1)
    figure.update_yaxes(tickformat="+.1%", title=None)
    return _layout(figure, "全球指数 · 日涨跌", y_title="", height=300)


def regime_distribution_chart(
    values: dict[str, float],
    *,
    calibrated: bool,
) -> Any:
    ordered = ("Risk-On", "Neutral", "Risk-Off")
    figure = go.Figure(
        data=[
            go.Bar(
                x=[values.get(item, 0.0) for item in ordered],
                y=list(ordered),
                orientation="h",
                marker_color=[POSITIVE, ACCENT, NEGATIVE],
                text=[f"{values.get(item, 0.0):.0%}" for item in ordered],
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{y}<br>%{x:.1%}<extra></extra>",
            )
        ]
    )
    figure.update_xaxes(range=[0, 1], tickformat=".0%", visible=False)
    figure.update_yaxes(categoryorder="array", categoryarray=list(reversed(ordered)))
    title = "Calibrated Regime Probability" if calibrated else "Market Regime Score"
    return _layout(figure, title, y_title="", height=235)


def price_chart(prices: tuple[PricePoint, ...], title: str) -> Any:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[point.date for point in prices],
            y=[float(point.close) for point in prices],
            mode="lines",
            name="收盘价",
            line={"color": ACCENT, "width": 2},
            hovertemplate="%{x|%Y-%m-%d}<br>收盘 %{y:,.2f}<extra></extra>",
        )
    )
    return _layout(figure, title, y_title="价格")


def volume_chart(prices: tuple[PricePoint, ...]) -> Any:
    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=[point.date for point in prices],
            y=[point.volume or 0 for point in prices],
            name="成交量",
            marker_color=VOLUME,
            hovertemplate="%{x|%Y-%m-%d}<br>成交量 %{y:,.0f}<extra></extra>",
        )
    )
    return _layout(figure, "成交量", y_title="成交量", height=260)


def line_chart(
    points: tuple[SeriesPoint, ...],
    *,
    title: str,
    y_title: str,
    percent: bool = False,
) -> Any:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=[point.date for point in points],
            y=[point.value for point in points],
            mode="lines",
            line={"color": NEGATIVE if percent else ACCENT, "width": 2},
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>%{y:.2%}<extra></extra>"
                if percent
                else "%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>"
            ),
        )
    )
    if percent:
        figure.update_yaxes(tickformat=".1%")
    return _layout(figure, title, y_title=y_title)


def exposure_chart(exposures: tuple[Exposure, ...], title: str) -> Any:
    figure = go.Figure(
        data=[
            go.Bar(
                x=[exposure.weight for exposure in exposures],
                y=[exposure.name for exposure in exposures],
                orientation="h",
                marker_color=ACCENT,
                hovertemplate="%{y}<br>%{x:.1%}<extra></extra>",
            )
        ]
    )
    figure.update_xaxes(tickformat=".0%")
    return _layout(figure, title, y_title="", height=300)


def portfolio_risk_line_chart(
    points: tuple[RiskSeriesPoint, ...],
    *,
    title: str,
    y_title: str,
    percent: bool = False,
) -> Any:
    figure = go.Figure(
        data=[
            go.Scatter(
                x=[point.date for point in points],
                y=[point.value for point in points],
                mode="lines",
                line={"color": NEGATIVE if percent else ACCENT, "width": 2},
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>%{y:.2%}<extra></extra>"
                    if percent
                    else "%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>"
                ),
            )
        ]
    )
    if percent:
        figure.update_yaxes(tickformat=".1%")
    return _layout(figure, title, y_title=y_title)


def stress_contribution_chart(result: StressTestResult) -> Any:
    impacts = tuple(reversed(result.impacts))
    figure = go.Figure(
        data=[
            go.Bar(
                x=[item.contribution for item in impacts],
                y=[item.instrument.symbol for item in impacts],
                orientation="h",
                marker_color=[NEGATIVE if item.contribution < 0 else ACCENT for item in impacts],
                customdata=[
                    [item.market_return, item.currency_return, item.combined_return]
                    for item in impacts
                ],
                hovertemplate=(
                    "%{y}<br>组合贡献 %{x:.2%}"
                    "<br>市场冲击 %{customdata[0]:.2%}"
                    "<br>汇率冲击 %{customdata[1]:.2%}"
                    "<br>合并冲击 %{customdata[2]:.2%}<extra></extra>"
                ),
            )
        ]
    )
    figure.update_xaxes(tickformat=".1%", title="组合收益贡献")
    return _layout(
        figure,
        f"压力贡献 · {result.scenario.name}",
        y_title="",
        height=max(320, len(impacts) * 36 + 100),
    )


def allocation_chart(labels: list[str], values: list[float]) -> Any:
    figure = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.55,
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:,.2f}<extra></extra>",
            )
        ]
    )
    figure.update_layout(
        title={"text": "持仓分布", "x": 0},
        height=360,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        legend={"orientation": "h"},
    )
    return figure


def relationship_heatmap(
    entities: tuple[EntityOption, ...],
    observations: tuple[CorrelationObservation, ...],
    *,
    title: str,
) -> Any:
    labels = [entity.label for entity in entities]
    index_by_key = {entity.key: index for index, entity in enumerate(entities)}
    matrix: list[list[float | None]] = [
        [1.0 if row == column else None for column in range(len(entities))]
        for row in range(len(entities))
    ]
    samples: list[list[str]] = [["—" for _ in entities] for _ in entities]
    for observation in observations:
        left_index = index_by_key.get(observation.left.key)
        right_index = index_by_key.get(observation.right.key)
        if left_index is None or right_index is None:
            continue
        matrix[left_index][right_index] = observation.correlation
        matrix[right_index][left_index] = observation.correlation
        sample_text = str(observation.sample_size)
        samples[left_index][right_index] = sample_text
        samples[right_index][left_index] = sample_text

    figure = go.Figure(
        data=[
            go.Heatmap(
                z=matrix,
                x=labels,
                y=labels,
                zmin=-1,
                zmax=1,
                zmid=0,
                colorscale=[
                    [0.0, "#B91C1C"],
                    [0.5, "#F8FAFC"],
                    [1.0, "#1D4ED8"],
                ],
                colorbar={"title": "相关系数"},
                customdata=samples,
                hovertemplate=(
                    "%{y}<br>%{x}<br>相关系数 %{z:.3f}<br>共同样本 %{customdata}<extra></extra>"
                ),
            )
        ]
    )
    figure.update_layout(
        title={"text": title, "x": 0},
        height=max(460, 42 * len(entities)),
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
    )
    figure.update_xaxes(side="top")
    return figure


def rolling_correlation_chart(
    observations: tuple[CorrelationObservation, ...],
    *,
    title: str,
) -> Any:
    figure = go.Figure()
    windows = sorted(
        {
            observation.window_days
            for observation in observations
            if observation.window_days is not None
        }
    )
    for window in windows:
        points = [observation for observation in observations if observation.window_days == window]
        figure.add_trace(
            go.Scatter(
                x=[point.as_of_date for point in points],
                y=[point.correlation for point in points],
                mode="lines",
                name=f"{window}日",
                hovertemplate=(
                    f"%{{x|%Y-%m-%d}}<br>相关系数 %{{y:.3f}}<br>窗口 {window}日<extra></extra>"
                ),
            )
        )
    figure.add_hline(y=0, line_dash="dot", line_color=VOLUME)
    figure.update_yaxes(range=[-1, 1])
    figure.update_layout(
        title={"text": title, "x": 0},
        height=360,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        hovermode="x unified",
        legend={"orientation": "h"},
        yaxis_title="相关系数",
    )
    return figure


def event_probability_chart(
    statistics: tuple[EventStatistic, ...],
    *,
    title: str,
) -> Any:
    figure = go.Figure()
    target_labels = tuple(dict.fromkeys(item.target.label for item in statistics))
    for target_label in target_labels:
        points = sorted(
            (item for item in statistics if item.target.label == target_label),
            key=lambda item: item.horizon_days,
        )
        figure.add_trace(
            go.Scatter(
                x=[item.horizon_days for item in points],
                y=[item.positive_probability for item in points],
                mode="lines+markers",
                name=target_label,
                customdata=[item.sample_size for item in points],
                hovertemplate=(
                    "期限 %{x}日<br>上涨概率 %{y:.1%}"
                    "<br>有效样本 %{customdata}<extra>%{fullData.name}</extra>"
                ),
            )
        )
    figure.update_yaxes(range=[0, 1], tickformat=".0%")
    figure.update_xaxes(
        title="后续交易日",
        tickmode="array",
        tickvals=sorted({item.horizon_days for item in statistics}),
    )
    figure.update_layout(
        title={"text": title, "x": 0},
        height=380,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        hovermode="x unified",
        legend={"orientation": "h"},
        yaxis_title="上涨概率",
    )
    return figure


def conditional_probability_chart(
    estimates: tuple[ProbabilityEstimate, ...],
    *,
    title: str,
) -> Any:
    reliable = tuple(
        estimate
        for estimate in estimates
        if estimate.meets_minimum
        and estimate.probability is not None
        and estimate.confidence_lower is not None
        and estimate.confidence_upper is not None
    )
    figure = go.Figure()
    horizons = sorted({estimate.horizon_days for estimate in reliable})
    for horizon in horizons:
        points = [estimate for estimate in reliable if estimate.horizon_days == horizon]
        probabilities = [
            estimate.probability for estimate in points if estimate.probability is not None
        ]
        figure.add_trace(
            go.Bar(
                x=[estimate.target.label for estimate in points],
                y=probabilities,
                name=f"{horizon}日",
                customdata=[
                    [
                        estimate.sample_size,
                        estimate.confidence_lower,
                        estimate.confidence_upper,
                    ]
                    for estimate in points
                ],
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": [
                        (estimate.confidence_upper or 0) - (estimate.probability or 0)
                        for estimate in points
                    ],
                    "arrayminus": [
                        (estimate.probability or 0) - (estimate.confidence_lower or 0)
                        for estimate in points
                    ],
                },
                hovertemplate=(
                    "%{x}<br>概率 %{y:.1%}<br>样本 %{customdata[0]}"
                    "<br>区间 [%{customdata[1]:.1%}, %{customdata[2]:.1%}]"
                    "<extra>%{fullData.name}</extra>"
                ),
            )
        )
    figure.update_yaxes(range=[0, 1], tickformat=".0%", title="条件概率")
    figure.update_layout(
        title={"text": title, "x": 0},
        height=400,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        barmode="group",
        legend={"orientation": "h"},
    )
    return figure


def market_graph_chart(
    nodes: tuple[GraphNodeMetric, ...],
    edges: tuple[GraphEdgeMetric, ...],
    *,
    title: str,
) -> Any:
    positions = {node.instrument.key: (node.position_x, node.position_y) for node in nodes}
    edge_colors = {
        "correlation": "#94A3B8",
        "lead_lag": "#2563EB",
        "capital_transmission": "#F59E0B",
    }
    edge_names = {
        "correlation": "相关性",
        "lead_lag": "领先关系",
        "capital_transmission": "资金传导代理",
    }
    figure = go.Figure()
    for relationship_type in edge_colors:
        type_edges = [edge for edge in edges if edge.relationship_type == relationship_type]
        for edge in type_edges:
            source_x, source_y = positions[edge.source.key]
            target_x, target_y = positions[edge.target.key]
            figure.add_trace(
                go.Scatter(
                    x=[source_x, target_x],
                    y=[source_y, target_y],
                    mode="lines",
                    line={
                        "color": edge_colors[relationship_type],
                        "width": 1 + 4 * edge.strength,
                    },
                    opacity=0.65,
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
            if relationship_type != "correlation":
                figure.add_annotation(
                    x=target_x,
                    y=target_y,
                    ax=source_x,
                    ay=source_y,
                    xref="x",
                    yref="y",
                    axref="x",
                    ayref="y",
                    showarrow=True,
                    arrowhead=2,
                    arrowsize=0.8,
                    arrowwidth=1 + 2 * edge.strength,
                    arrowcolor=edge_colors[relationship_type],
                    opacity=0.7,
                )

    asset_colors = {
        "stock": "#2563EB",
        "etf": "#7C3AED",
        "index": "#059669",
        "commodity": "#D97706",
    }
    for asset_type, color in asset_colors.items():
        type_nodes = [node for node in nodes if node.instrument.asset_type == asset_type]
        if not type_nodes:
            continue
        figure.add_trace(
            go.Scatter(
                x=[node.position_x for node in type_nodes],
                y=[node.position_y for node in type_nodes],
                mode="markers+text",
                name=asset_type,
                text=[node.instrument.symbol for node in type_nodes],
                textposition="top center",
                customdata=[
                    [
                        node.instrument.name,
                        node.degree_centrality,
                        node.betweenness_centrality,
                        node.influence,
                        node.association_strength,
                        node.core_score,
                    ]
                    for node in type_nodes
                ],
                marker={
                    "size": [18 + 32 * node.core_score for node in type_nodes],
                    "color": color,
                    "line": {"color": "white", "width": 1.5},
                    "opacity": 0.9,
                },
                hovertemplate=(
                    "%{text} · %{customdata[0]}"
                    "<br>度中心性 %{customdata[1]:.3f}"
                    "<br>介数中心性 %{customdata[2]:.3f}"
                    "<br>影响力 %{customdata[3]:.3f}"
                    "<br>关联强度 %{customdata[4]:.3f}"
                    "<br>核心分数 %{customdata[5]:.3f}<extra></extra>"
                ),
            )
        )
    for relationship_type, color in edge_colors.items():
        if any(edge.relationship_type == relationship_type for edge in edges):
            figure.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="lines",
                    line={"color": color, "width": 3},
                    name=edge_names[relationship_type],
                )
            )
    figure.update_layout(
        title={"text": title, "x": 0},
        height=680,
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        xaxis={"visible": False},
        yaxis={"visible": False},
        hovermode="closest",
        legend={"orientation": "h"},
        plot_bgcolor="#F8FAFC",
    )
    return figure


def lead_lag_confidence_chart(
    pairs: tuple[PairEvidence, ...],
    *,
    title: str,
) -> Any:
    visible = tuple(
        sorted(
            (pair for pair in pairs if pair.is_significant),
            key=lambda item: item.confidence_score,
        )
    )
    labels = [f"{item.source.symbol} → {item.target.symbol}" for item in visible]
    figure = go.Figure(
        data=[
            go.Bar(
                x=[item.confidence_score for item in visible],
                y=labels,
                orientation="h",
                marker={
                    "color": [item.best_lag_days for item in visible],
                    "colorscale": "Blues",
                    "colorbar": {"title": "滞后"},
                },
                customdata=[
                    [
                        item.best_lag_days,
                        item.cross_correlation,
                        item.q_value,
                        item.sample_size,
                    ]
                    for item in visible
                ],
                hovertemplate=(
                    "%{y}<br>证据可信度 %{x:.1%}"
                    "<br>响应滞后 %{customdata[0]} 个交易日"
                    "<br>Cross Correlation %{customdata[1]:.3f}"
                    "<br>FDR q 值 %{customdata[2]:.4f}"
                    "<br>样本 %{customdata[3]}<extra></extra>"
                ),
            )
        ]
    )
    figure.update_xaxes(range=[0, 1], tickformat=".0%", title="证据可信度（1 - q）")
    return _layout(
        figure,
        title,
        y_title="",
        height=max(320, 42 * len(visible) + 100),
    )


def market_regime_distribution_chart(
    point: MarketRegimePoint,
    *,
    title: str,
) -> Any:
    labels = ["Risk-On", "Neutral", "Risk-Off"]
    probabilities = point.probabilities
    source = probabilities or point.scores
    values = [source["risk_on"], source["neutral"], source["risk_off"]]
    output_name = "Calibrated Probability" if probabilities is not None else "Regime Score"
    figure = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker_color=["#059669", "#94A3B8", "#DC2626"],
                text=[f"{value:.1%}" for value in values],
                textposition="outside",
                hovertemplate=f"%{{x}}<br>{output_name} %{{y:.1%}}<extra></extra>",
            )
        ]
    )
    figure.update_yaxes(range=[0, 1], tickformat=".0%")
    return _layout(figure, title, y_title=output_name, height=340)


def market_regime_history_chart(
    observations: tuple[MarketRegimePoint, ...],
    *,
    title: str,
) -> Any:
    figure = go.Figure()
    calibrated = observations[-1].probabilities is not None if observations else False
    series: tuple[tuple[str, RegimeName, str], ...] = (
        ("Risk-On", "risk_on", "#059669"),
        ("Neutral", "neutral", "#94A3B8"),
        ("Risk-Off", "risk_off", "#DC2626"),
    )
    for label, key, color in series:
        figure.add_trace(
            go.Scatter(
                x=[item.as_of_date for item in observations],
                y=[(item.probabilities or item.scores)[key] for item in observations],
                mode="lines",
                name=label,
                line={"color": color, "width": 1.5},
                stackgroup="distribution",
                hovertemplate="%{x|%Y-%m-%d}<br>%{fullData.name} %{y:.1%}<extra></extra>",
            )
        )
    output_name = "Calibrated Probability" if calibrated else "Market Regime Score"
    figure.update_yaxes(range=[0, 1], tickformat=".0%", title=output_name)
    figure.update_layout(
        title={"text": title, "x": 0},
        height=420,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        hovermode="x unified",
        legend={"orientation": "h"},
    )
    return figure


def market_regime_calibration_curve(report: RegimeCalibrationReport) -> Any:
    """Plot out-of-sample reliability points against perfect calibration."""

    figure = go.Figure()
    colors = {"risk_on": "#059669", "neutral": "#94A3B8", "risk_off": "#DC2626"}
    labels = {"risk_on": "Risk-On", "neutral": "Neutral", "risk_off": "Risk-Off"}
    figure.add_trace(
        go.Scatter(
            x=[0, 1],
            y=[0, 1],
            mode="lines",
            name="Perfect calibration",
            line={"color": VOLUME, "dash": "dash"},
            hoverinfo="skip",
        )
    )
    for regime in ("risk_on", "neutral", "risk_off"):
        points = tuple(item for item in report.calibration_curve if item.regime == regime)
        if not points:
            continue
        figure.add_trace(
            go.Scatter(
                x=[item.mean_predicted for item in points],
                y=[item.observed_frequency for item in points],
                mode="lines+markers",
                name=labels[regime],
                line={"color": colors[regime]},
                customdata=[[item.sample_size] for item in points],
                hovertemplate=(
                    "%{fullData.name}<br>Predicted %{x:.1%}<br>Observed %{y:.1%}"
                    "<br>OOS sample %{customdata[0]}<extra></extra>"
                ),
            )
        )
    figure.update_xaxes(range=[0, 1], tickformat=".0%", title="Candidate probability")
    figure.update_yaxes(range=[0, 1], tickformat=".0%", title="Observed frequency")
    figure.update_layout(
        title={"text": "Walk-Forward Calibration Curve", "x": 0},
        height=380,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        legend={"orientation": "h"},
    )
    return figure


def factor_score_chart(
    scores: tuple[FactorStockScore, ...],
    *,
    title: str,
    maximum_stocks: int = 20,
) -> Any:
    visible = tuple(reversed(scores[:maximum_stocks]))
    figure = go.Figure(
        data=[
            go.Bar(
                x=[item.factor_score for item in visible],
                y=[item.instrument.symbol for item in visible],
                orientation="h",
                marker_color=ACCENT,
                customdata=[[item.instrument.name, item.category_coverage] for item in visible],
                hovertemplate=(
                    "%{y} · %{customdata[0]}<br>Factor Score %{x:.1f}"
                    "<br>有效类别 %{customdata[1]}/5<extra></extra>"
                ),
            )
        ]
    )
    figure.update_xaxes(range=[0, 100], title="Factor Score")
    return _layout(
        figure,
        title,
        y_title="",
        height=max(360, len(visible) * 30 + 100),
    )


def factor_backtest_chart(
    periods: tuple[FactorBacktestPeriodResult, ...],
    *,
    title: str,
) -> Any:
    portfolio = 1.0
    benchmark = 1.0
    portfolio_values: list[float] = []
    benchmark_values: list[float] = []
    dates = []
    for period in periods:
        portfolio *= 1 + period.portfolio_return
        benchmark *= 1 + period.benchmark_return
        dates.append(period.period_end_date)
        portfolio_values.append(portfolio - 1)
        benchmark_values.append(benchmark - 1)
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=portfolio_values,
            mode="lines",
            name="Top Factor Portfolio",
            line={"color": ACCENT, "width": 2},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=dates,
            y=benchmark_values,
            mode="lines",
            name="Scored Universe EW",
            line={"color": VOLUME, "width": 2},
        )
    )
    figure.update_yaxes(tickformat=".0%", title="累计收益")
    figure.update_layout(
        title={"text": title, "x": 0},
        height=420,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        hovermode="x unified",
        legend={"orientation": "h"},
    )
    return figure


def scenario_risk_map_chart(result: ScenarioResult) -> Any:
    """Map position weight against conditional return and loss contribution."""

    impacts = tuple(item for item in result.impacts if item.weight > 0)
    sizes = [max(12.0, min(58.0, abs(item.contribution) * 700)) for item in impacts]
    figure = go.Figure(
        data=[
            go.Scatter(
                x=[item.weight for item in impacts],
                y=[item.combined_return for item in impacts],
                mode="markers+text",
                text=[item.instrument.symbol for item in impacts],
                textposition="top center",
                marker={
                    "size": sizes,
                    "color": [item.combined_return for item in impacts],
                    "colorscale": [
                        [0.0, "#B91C1C"],
                        [0.5, "#F8FAFC"],
                        [1.0, "#059669"],
                    ],
                    "cmid": 0,
                    "line": {"color": "#FFFFFF", "width": 1},
                    "colorbar": {"title": "资产影响"},
                },
                customdata=[
                    [
                        item.contribution,
                        item.return_low,
                        item.return_high,
                        "已映射" if item.mapped else "未映射",
                    ]
                    for item in impacts
                ],
                hovertemplate=(
                    "%{text}<br>组合权重 %{x:.1%}<br>资产影响 %{y:.1%}"
                    "<br>组合贡献 %{customdata[0]:.1%}"
                    "<br>敏感性区间 %{customdata[1]:.1%} 至 %{customdata[2]:.1%}"
                    "<br>%{customdata[3]}<extra></extra>"
                ),
            )
        ]
    )
    figure.add_hline(y=0, line_dash="dot", line_color=VOLUME)
    figure.update_xaxes(tickformat=".0%", title="组合权重")
    figure.update_yaxes(tickformat=".0%", title="情景下资产收益变化")
    figure.update_layout(
        title={"text": "风险地图", "x": 0},
        height=440,
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
        showlegend=False,
    )
    return figure


def scenario_comparison_chart(comparison: ScenarioComparison) -> Any:
    """Compare conditional portfolio impacts and sensitivity intervals."""

    results = tuple(reversed(sorted(comparison.results, key=lambda item: item.pnl_percent)))
    figure = go.Figure(
        data=[
            go.Bar(
                x=[item.pnl_percent for item in results],
                y=[item.scenario.name for item in results],
                orientation="h",
                marker_color=[NEGATIVE if item.pnl_percent < 0 else "#059669" for item in results],
                error_x={
                    "type": "data",
                    "symmetric": False,
                    "array": [item.pnl_percent_high - item.pnl_percent for item in results],
                    "arrayminus": [item.pnl_percent - item.pnl_percent_low for item in results],
                },
                customdata=[
                    [item.risk_level, item.confidence_score, item.mapped_weight] for item in results
                ],
                hovertemplate=(
                    "%{y}<br>组合影响 %{x:.1%}<br>风险等级 %{customdata[0]}"
                    "<br>证据质量 %{customdata[1]}/100"
                    "<br>映射覆盖率 %{customdata[2]:.1%}<extra></extra>"
                ),
            )
        ]
    )
    figure.add_vline(x=0, line_dash="dot", line_color=VOLUME)
    figure.update_xaxes(tickformat=".0%", title="组合变化")
    return _layout(
        figure,
        "情景比较",
        y_title="",
        height=max(340, 54 * len(results) + 120),
    )


def asset_sensitivity_heatmap(result: ScenarioResult) -> Any:
    """Show explicit factor sensitivity coefficients by asset."""

    factors = sorted(
        {factor.factor_code for impact in result.impacts for factor in impact.factor_contributions}
    )
    assets = [item.instrument.symbol for item in result.impacts]
    sensitivity_by_key = {
        (impact.instrument.symbol, factor.factor_code): factor.sensitivity
        for impact in result.impacts
        for factor in impact.factor_contributions
    }
    matrix = [[sensitivity_by_key.get((asset, factor)) for factor in factors] for asset in assets]
    figure = go.Figure(
        data=[
            go.Heatmap(
                z=matrix,
                x=factors,
                y=assets,
                zmid=0,
                colorscale=[
                    [0.0, "#B91C1C"],
                    [0.5, "#F8FAFC"],
                    [1.0, "#2563EB"],
                ],
                colorbar={"title": "敏感度"},
                hovertemplate=("%{y}<br>%{x}<br>敏感度 %{z:.3f}<extra></extra>"),
            )
        ]
    )
    figure.update_layout(
        title={"text": "资产—风险因子敏感性", "x": 0},
        height=max(340, 42 * len(assets) + 120),
        margin={"l": 20, "r": 20, "t": 60, "b": 20},
    )
    return figure


def _layout(
    figure: Any,
    title: str,
    *,
    y_title: str,
    height: int = 360,
) -> Any:
    figure.update_layout(
        title={"text": title, "x": 0},
        height=height,
        margin={"l": 20, "r": 20, "t": 55, "b": 20},
        showlegend=False,
        hovermode="x unified",
        xaxis_title=None,
        yaxis_title=y_title,
    )
    return figure
