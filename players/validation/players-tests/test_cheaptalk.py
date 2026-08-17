from players.player_sdk.cheaptalk import PersistenceLatch, TalkBudget


def test_budget_priority_and_offer_order():
    b = TalkBudget(spacing=26)
    b.offer("routine", 10, key="a")
    b.offer("urgent", 40, key="b")
    b.offer("also-urgent", 40, key="c")
    assert b.arbitrate(100) == "urgent"          # priority, then offer order


def test_budget_global_spacing_and_key_cooldowns():
    b = TalkBudget(spacing=26)
    b.offer("one", 10, key="k", cooldown=50)
    assert b.arbitrate(100) == "one"
    b.offer("two", 10, key="k", cooldown=50)
    assert b.arbitrate(110) is None              # global spacing
    b.offer("three", 10, key="k", cooldown=50)
    b.offer("other", 5, key="j")
    assert b.arbitrate(130) == "other"           # key cooled down -> next prio


def test_budget_offers_never_queue_across_decisions():
    b = TalkBudget(spacing=26)
    b.offer("stale", 40, key="k")
    assert b.arbitrate(10) == "stale"
    assert b.arbitrate(100) is None              # nothing re-offered


def test_budget_truncates_then_strips():
    b = TalkBudget(spacing=0, max_len=10)
    b.offer("0123456789ABC", 1, key="k")
    assert b.arbitrate(0) == "0123456789"
    b.offer("cover 3   trailing", 1, key="k2")
    assert b.arbitrate(1) == "cover 3"           # kept tail was whitespace
    b.offer("   ", 1, key="k3")
    assert b.arbitrate(2) is None                # empty after strip: dropped


def test_latch_admits_once_per_lifetime():
    l = PersistenceLatch(lifetime=72)
    assert l.fresh("alpha", "hi", 100)
    assert not l.fresh("alpha", "hi", 110)       # persistence, not a resend
    assert l.fresh("alpha", "bye", 120)          # text changed: new message
    assert l.fresh("alpha", "bye", 200)          # lifetime passed: resend
    assert l.fresh("beta", "hi", 100 + 5)        # speakers independent


def test_latch_prune_bounds_memory():
    l = PersistenceLatch(lifetime=10)
    for i in range(50):
        l.fresh(f"s{i}", "x", 0)
    l.prune(100)
    assert not l._live
