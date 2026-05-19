import re
from pathlib import Path


def test_every_listed_rule_has_a_test_reference() -> None:
    rules_text = Path("RULES.md").read_text()
    rule_lines = [line for line in rules_text.splitlines() if line.startswith("- R-")]

    assert len(rule_lines) >= 30
    assert len(rule_lines) == len({line.split(":", 1)[0] for line in rule_lines})
    assert "TODO" not in rules_text
    for line in rule_lines:
        assert "Tests: " in line
        for reference in line.split("Tests: ", 1)[1].split(", "):
            path_text, test_name = reference.split("::", 1)
            test_text = Path(path_text).read_text()
            assert re.search(rf"def {re.escape(test_name)}\(", test_text), reference
