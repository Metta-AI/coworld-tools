# Suspicion — Bayesian P(imposter)

**Status:** living document. This is the canonical, durable home for crewborg's
suspicion model and especially its **likelihood-ratio table** — the place where we
record, justify, and improve the evidence weights as we learn them from games.

- **Code:** [`strategy/suspicion.py`](../../strategy/suspicion.py) — the table is
  `LIKELIHOOD_RATIOS`; the update is `update_suspicion(belief)`.
- **Spec summary:** [`design.md` §10.1](../../design.md).
- **Inputs:** the perception tape (§5.1) and per-player event log (§5.2), both in
  `design.md`.

If a value here and in the code ever disagree, **the code is what runs** — but a
change should land in both, with the rationale recorded here.

---

## 1. What we compute

For a **crewmate** observer, for every *other* player, the posterior probability
they are an imposter:

```
belief.suspicion[color] = P(imposter | everything we have observed)   ∈ [0, 1]
```

`believed_imposters` (which gates the Flee mode) is every **alive** player whose
posterior is at or above `FLEE_PROBABILITY` (0.9). Suspicion is **crewmate-only**:
an imposter already knows who its teammates are (it accrues no suspicion and never
flees a crewmate), and a ghost does not flee.

This is a real probability with units, so the threshold means something concrete —
"flee only when ≥90% sure" — rather than an arbitrary score.

---

## 2. The model

### 2.1 Prior — combinatorics

With `P` players total and `K` imposters, a crewmate knows all `K` imposters are
among the other `P − 1` players. By symmetry, each other player's marginal prior
is:

```
prior = K / (P − 1)
```

- `P` = `belief.total_player_count` (estimated early from distinct colors seen;
  authoritative once the meeting census arrives, §4.3).
- `K` = `belief.imposter_count` if set, else **derived** from the player count via
  Crewrift's own auto-imposter formula `(P − 3) // 2` (`sim.nim` `ratioImposterCount`
  / `effectiveImposterCount`; default `autoImposterCount = true`). Override
  `belief.imposter_count` if a game is known to use a fixed count.

The prior is clamped to `[PRIOR_MIN, PRIOR_MAX]` = `[1e-3, 0.99]` so its log-odds
stays finite.

### 2.2 Update — log-odds Bayes

Each piece of evidence is incorporated by a **likelihood ratio**

```
LR_e = P(observe e | player is imposter) / P(observe e | player is crewmate)
```

In log-odds form, evidence is additive (this is just Bayes' rule for independent
evidence):

```
logit(P) = logit(prior) + Σ_e log(LR_e)
P        = sigmoid(logit(P))
```

where `logit(p) = ln(p / (1 − p))` and `sigmoid(x) = 1 / (1 + e^−x)`.

- `LR > 1` ⇒ evidence raises suspicion; `LR = 1` ⇒ neutral; `LR < 1` ⇒ lowers it
  (we have no `LR < 1` evidence yet — see §5, positive-evidence-only).
- Evidence is a **set of types** per player — each type contributes its `log(LR)`
  **at most once**. So repeated logging of the same behaviour can't inflate the
  posterior, and an unbounded event log (§5.2) is safe.
- Because a player's role is a **fixed latent variable**, evidence does not decay:
  observing someone vent at minute 1 is permanent evidence about their (unchanging)
  role. There is no time-decay term, by design.

### 2.3 Worked example

8 players ⇒ `K = (8 − 3) // 2 = 2`, so `prior = 2 / 7 ≈ 0.286`, `logit ≈ −0.916`.

| Evidence observed | logit | P(imposter) | Flee (≥0.9)? |
|---|---|---|---|
| none (the prior) | −0.916 | 0.286 | no |
| `vent_dwell` (LR 15) | −0.916 + 2.708 = 1.79 | 0.857 | no |
| `vent_dwell` + `body_linger` (×3) | 1.79 + 1.099 = 2.89 | 0.947 | **yes** |
| `witnessed_vent` (LR 1e6) | −0.916 + 13.82 = 12.9 | 0.99999 | **yes** |

So a single graded cue is suspicious but not flee-worthy; corroboration crosses the
bar; a witnessed catch is effectively certain regardless of the prior.

---

## 3. The evidence catalogue + likelihood-ratio table

This is the load-bearing table. **The LR values are the learnable surface** — the
initial values below are hand-estimated priors (no games analysed yet) and are
expected to be *replaced* by values learned from replays (§6). Record every change
in the provenance log (§7).

| Evidence type | Source | Detected when | LR (current) | Rationale |
|---|---|---|---|---|
| `witnessed_kill` | tape transition (§5.1) | victim alive last frame, body now, exactly **one** other player within `KILL_RANGE_SQ` of the victim last frame (the lone neighbour) | **1e6** | Definitional: we saw the kill. Near-certain; LR is "effectively infinite". |
| `witnessed_vent` | tape transition (§5.1) | *emergence* (vent + `VENT_WALK_MARGIN` was in line of sight & clear last frame, occupied now) or *submersion* (player in the vent last frame, gone while it stays in sight). LoS via the `shadow` mask (§4.4). | **1e6** | Only imposters can vent. Near-certain. |
| `vent_dwell` | event log (§5.2) | a `vent` event with `duration_ticks ≥ VENT_DWELL_MIN_TICKS` (≈1 s) | **15** | Crewmates cross vent tiles but ~never loiter on them; strong but not certain (odd pathing exists). |
| `body_linger` | event log (§5.2) | a `near_body` event with `duration ≥ BODY_LINGER_MIN_TICKS` (≈1 s) and `min_dist ≤ BODY_LINGER_MAX_DIST` (16 px) | **3** | Hovering right at a corpse is suspicious, but innocent reporters do it too — modest. |
| `follow_to_death` | event log (§5.2) | a `proximity` event to player V with `duration ≥ FOLLOW_MIN_TICKS` (≈2 s), V now dead, and the proximity ended within `FOLLOW_DEATH_WINDOW_TICKS` (≈3 s) of finding V's body | **6** | Sustained stalking of someone who then died. Noisier (loose kill-timing) but meaningful. |

### Detection gates (in `suspicion.py`)

These thresholds shape *when* an evidence type fires; tuning them changes the
event's selectivity (and therefore the right LR). At 24 Hz:

| Constant | Value | Meaning |
|---|---|---|
| `VENT_DWELL_MIN_TICKS` | 24 | min loiter on a vent to count |
| `BODY_LINGER_MIN_TICKS` | 24 | min dwell next to a body |
| `BODY_LINGER_MAX_DIST` | 16 px | "right next to it" |
| `FOLLOW_MIN_TICKS` | 48 | min sustained proximity to count as following |
| `FOLLOW_DEATH_WINDOW_TICKS` | 72 | how close the following must end to the death |
| `VENT_WALK_MARGIN` | 3 px | one tick of walking (vent-emergence guard) |

### Deliberately **excluded** (too noisy to be evidence)

- **Brief proximity** — crew constantly pass within kill range while tasking.
- **Single-body passing / distant near-body** — the innocent who finds and reports
  a body is right next to it.
- **`task` dwell as exculpation** — would lower suspicion for "looking busy", but
  imposters fake tasks (the Pretend mode does exactly this), so it is not reliable
  evidence of innocence.

These are logged in the event log regardless (they may feed the LLM later), they
just don't carry an LR.

---

## 4. Thresholds & tuning knobs

| Knob | Value | Effect |
|---|---|---|
| `FLEE_PROBABILITY` | 0.9 | posterior at/above which we flee a player. Higher = more conservative reactive behaviour. |
| `PRIOR_MIN` / `PRIOR_MAX` | 1e-3 / 0.99 | clamp the prior so log-odds is finite. |
| the LR values | §3 | how much each observation moves belief. **The main thing to learn.** |
| the detection gates | §3 | how selective each evidence type is. |

---

## 5. Assumptions and their consequences

These are v1 simplifications. Each is sound enough to ship and clearly documented so
we know what to revisit.

1. **Naive Bayes (conditional independence).** We treat evidence types as
   independent given role and sum their `log(LR)`. Correlated evidence (e.g. two
   cues that tend to co-occur) is over-counted → over-confidence. Mitigated for now
   by counting each *type* once and by conservative weights. A joint model is the
   eventual fix.
2. **Positive-evidence-only.** We only have `LR ≥ 1` evidence; absence of suspicious
   behaviour never lowers a player below the prior. A true model would also use
   exculpatory/absence likelihoods (e.g. "watched them a long time, never vented").
   Until then the prior is the floor.
3. **Static prior.** We use `K / (P − 1)` and don't redistribute the imposter
   "budget" as players are confirmed or die (e.g. with `K = 1`, confirming the
   imposter should drop everyone else toward 0; it doesn't). Confirmed players still
   read ≈1 via their overwhelming LR, so flee behaviour is unaffected; the gap is in
   the *other* players' calibration. A proper joint/sequential model is a refinement.
4. **Observer-relative evidence.** Suspicion is built only from what *this* agent
   saw. Two crewmates can hold different posteriors about the same player. That is
   correct (it mirrors real play) but matters for learning (§6): LRs must be
   estimated from an observer's vantage, not from global ground truth of what
   happened.

---

## 6. Learning the likelihood ratios from replays

This is the durable process by which the table improves. The agent never learns at
runtime — we (offline) recompute the LRs from labelled game replays and update §3 +
§7.

For each evidence type `e`:

```
LR_e = P(e | imposter) / P(e | crewmate)
     ≈ (imposters for whom we observed e) / (imposters we had a chance to observe)
       ───────────────────────────────────────────────────────────────────────────
       (crewmates for whom we observed e) / (crewmates we had a chance to observe)
```

Procedure:

1. **Replays give ground truth.** A replay records every player's true role. Load it
   with the viewer recipe in [`docs/crewrift-replays.md`](../crewrift-replays.md).
2. **Reconstruct observations from an observer's POV.** Evidence is what a crewmate
   *saw*, so re-run the detectors (`_graded_evidence`, the tape detectors) as if
   crewborg were a particular crewmate in that game — using that player's
   line-of-sight/visibility, not the global state. Do this per (observer, game).
3. **Count with an opportunity denominator.** The denominator is players the
   observer *could* have caught exhibiting `e` (were observable enough), not all
   players — otherwise unobserved players bias the estimate.
4. **Smooth.** Use Laplace/add-k smoothing so a rare or never-seen event doesn't give
   a 0 or ∞ ratio.
5. **Sanity-check independence.** If two evidence types are highly correlated,
   prefer merging them or down-weighting, since naive Bayes will double-count.
6. **Update §3 and the provenance log (§7), then mirror into
   `LIKELIHOOD_RATIOS`.** Re-run the suspicion tests; they assert *relational*
   properties (evidence raises P, one cue stays below the flee bar, corroboration
   crosses it), so they should survive re-tuning — if one breaks, the new values
   changed the qualitative behaviour and that deserves a look.

The witnessed-kill/vent LRs are **definitional** (we saw it happen) and stay at the
near-certainty value; they are not learned.

The replay-analysis tooling itself is not built yet. When it is, this section should
gain the exact command/script and its output format.

---

## 7. Provenance log

One row per value-setting event. Keep this honest — it is how we know whether a
weight is a guess or earned.

| Date | Evidence | LR | Source | Games analysed | Notes |
|---|---|---|---|---|---|
| 2026-06-01 | `witnessed_kill` | 1e6 | definitional | — | only imposters kill; not learned |
| 2026-06-01 | `witnessed_vent` | 1e6 | definitional | — | only imposters vent; not learned |
| 2026-06-01 | `vent_dwell` | 15 | hand estimate | 0 | initial guess; loitering on a vent is rare for crew |
| 2026-06-01 | `body_linger` | 3 | hand estimate | 0 | initial guess; ambiguous vs. innocent reporter |
| 2026-06-01 | `follow_to_death` | 6 | hand estimate | 0 | initial guess; noisy kill-timing |

---

## 8. Adding a new evidence type

1. **Make it observable.** If it is a durative interaction, add a `PlayerEvent`
   kind in the event log (§5.2); if it is a frame transition, add a detector on the
   tape (§5.1).
2. **Define the gate** (the `*_MIN_TICKS` / distance constant) so it fires only when
   the signal is real.
3. **Detect it** in `_graded_evidence` (or a tape detector that adds to
   `confirmed_imposters`).
4. **Add its `LR`** to `LIKELIHOOD_RATIOS` and a row to the catalogue (§3) + a
   provenance entry (§7) — initially a hand estimate, flagged for learning.
5. **Test** the relational behaviour (raises P; alone below the flee bar unless it's
   near-certain).

---

## 9. Roadmap

- **Suspicion-aware voting** — the posterior currently only gates Flee; the high-value
  next consumer is voting the highest-`P` live player (above a confidence bar) instead
  of hardcoded skip. This is where suspicion changes game *outcomes*.
- **Exculpatory evidence** (`LR < 1`) and an absence model.
- **Dynamic/joint prior** (imposter-budget redistribution; §5.3).
- **More evidence types** from the event log + `chat_log` (§4.3) and `voting.dots`.
- **The offline LR-learning pipeline** (§6).
- **LLM strategy seam** consuming the per-player view (identity + life + events +
  posterior) for chat/voting reasoning.
