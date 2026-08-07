from players.player_sdk.worldmodel.relay import RelayPolicy


def test_admit_new_fix_and_preage():
    p = RelayPolicy(age=6, dup_radius=70)
    assert p.admit((400, 400), [])
    assert p.effective_last_seen(100) == 94       # own eyes outrank hearsay


def test_dup_gate_blocks_nearby_relays():
    p = RelayPolicy(dup_radius=70)
    existing = [(400, 400)]
    assert not p.admit((430, 430), existing)      # within the gate: drop
    assert p.admit((480, 400), existing)          # outside: new contact


def test_phantom_echo_never_refreshes():
    """The echo-loop property: replaying the same relay against a store
    that already ingested it must keep admitting False forever — a relay
    can create a contact once, never keep one alive."""
    p = RelayPolicy()
    store: list[tuple[float, float]] = []
    fix = (200.0, 200.0)
    admitted = 0
    for _ in range(10):
        if p.admit(fix, store):
            store.append(fix)
            admitted += 1
    assert admitted == 1 and len(store) == 1
