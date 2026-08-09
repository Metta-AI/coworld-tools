from platform_migrations.contracts import (
    validate_nomic_fable,
    validate_proxywar,
    validate_retirement,
)


def test_nomic_fable_platform_contract() -> None:
    validate_nomic_fable()


def test_proxywar_platform_contract() -> None:
    validate_proxywar()


def test_shared_commissioner_retirement_contract() -> None:
    validate_retirement()
