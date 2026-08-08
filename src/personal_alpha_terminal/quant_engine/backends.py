from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec

from personal_alpha_terminal.quant_engine.factors.qlib_adapter import QlibFactorResearchAdapter


@dataclass(frozen=True, slots=True)
class BackendStatus:
    name: str
    available: bool
    version: str | None
    role: str
    limitation: str


def quant_backend_statuses() -> tuple[BackendStatus, ...]:
    qlib = QlibFactorResearchAdapter().status()
    return (
        _package_status(
            "VectorBT",
            "vectorbt",
            "高速研究回测与参数扫描",
            "仅研究；最终验证仍使用统一审计回测引擎",
        ),
        _package_status(
            "Backtrader",
            "backtrader",
            "事件驱动策略与逐笔交易日志",
            "日线成交是假设模型，不代表盘口精确成交",
        ),
        BackendStatus(
            "Microsoft Qlib",
            qlib.available,
            _installed_version("pyqlib") if qlib.available else None,
            "隔离的因子研究运行时",
            qlib.reason or qlib.permitted_use,
        ),
    )


def _package_status(name: str, package: str, role: str, limitation: str) -> BackendStatus:
    available = find_spec(package) is not None
    return BackendStatus(
        name,
        available,
        _installed_version(package) if available else None,
        role,
        limitation if available else f"未安装；使用 quant-backends extra 启用 {name}",
    )


def _installed_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None
