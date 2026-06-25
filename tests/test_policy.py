def test_loads_front_matter(policy):
    assert policy.name == "minimal"
    assert "src/**" in policy.scope.writable_paths
    assert "schema_migration" in policy.always_escalate
    assert policy.prose.startswith("# Mandate")


def test_path_writable(policy):
    assert policy.path_writable("src/calc.py")
    assert policy.path_writable("tests/test_calc.py")
    assert not policy.path_writable("infra/deploy.tf")
    assert not policy.path_writable("policy/profiles/minimal.md")
    assert not policy.path_writable("README.md")  # not in writable globs


def test_tool_allowed(policy):
    assert policy.tool_allowed("write")
    assert not policy.tool_allowed("network")


def test_change_size_tiers(policy):
    assert policy.change_size_tier(10) == "standard"
    assert policy.change_size_tier(120) == "extended"
    assert policy.change_size_tier(500) == "human"


def test_category_escalation(policy):
    assert policy.category_always_escalates("schema_migration")
    assert not policy.category_always_escalates("bugfix")
    assert not policy.category_always_escalates(None)


def test_strict_is_tighter(strict_policy, policy):
    assert strict_policy.confidence.autonomous_min > policy.confidence.autonomous_min
    assert strict_policy.change_size.standard_max_lines < policy.change_size.standard_max_lines
