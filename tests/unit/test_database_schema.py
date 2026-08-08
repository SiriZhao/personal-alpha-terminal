from personal_alpha_terminal.models import Base


def test_every_foreign_key_has_a_leading_index() -> None:
    missing: list[str] = []
    for table in Base.metadata.tables.values():
        covered = {tuple(column.name for column in index.columns) for index in table.indexes}
        covered.update(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ in {"PrimaryKeyConstraint", "UniqueConstraint"}
        )
        for column in table.columns:
            if column.foreign_keys and not any(
                indexed_columns and indexed_columns[0] == column.name
                for indexed_columns in covered
            ):
                missing.append(f"{table.name}.{column.name}")

    assert missing == []
