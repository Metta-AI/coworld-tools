# Retired ruleset configs (test fixtures only)

These configs are **not shipped**. Their leagues moved to the platform ladder
service (`commissioner_key=platform`), so no commissioner container reads them
any more and they were removed from
`commissioners/ruleset_strategy_commissioner/configs/`.

They are kept here because they are the only fixtures that exercise several
strategies the engine still ships:

| Fixture | Retired because | Still the only test coverage for |
| --- | --- | --- |
| `ctf.yaml` | Ctf league is `platform` | `leader_slot_config` (board-leader seat decoration), adaptive scheduling under a settled field |
| `ctf_doubles.yaml` | Paintbot league is `platform` | `leader_slot_config` on `team_interleaved` with `policies_per_team` |
| `agricogla.yaml` | Agricogla league is `platform` | `mmr_neighbors` seating, late-champion seating |
| `four_score.yaml` | Four Score league is `platform` | `team_blocks` seating, qualifier self-play filling every slot |
| `cogs_vs_clips.yaml` | Cogs vs Clips league is `platform` | qualifier-stage transitions and private self-play restore |

Do not add to this directory. A config belongs here only if its league has
migrated away and deleting it would silently drop engine coverage; anything
genuinely dead should just be deleted along with the code it covered.

If a future league needs one of these rulesets, move the file back into
`configs/` and add its CATALOG entry rather than copying it.
