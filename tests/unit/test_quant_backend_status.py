from personal_alpha_terminal.quant_engine.backends import quant_backend_statuses


def test_quant_backend_status_is_lazy_and_explicit() -> None:
    statuses = {item.name: item for item in quant_backend_statuses()}

    assert statuses["VectorBT"].available
    assert statuses["Backtrader"].available
    assert not statuses["Microsoft Qlib"].available
    assert "Python 3.8-3.12" in statuses["Microsoft Qlib"].limitation
