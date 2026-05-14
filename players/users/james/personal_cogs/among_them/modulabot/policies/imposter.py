"""Imposter decision tree.

Port of modulabot's ``policy_imp.nim``. Same priority order, with
simplifications where screen-space cogames observations make the Nim bot's
bookkeeping redundant:

1. Body in view → self-report if it's our recent kill, else flee.
2. Lone visible non-teammate + kill ready + in range → press A (kill).
3. Lone visible non-teammate + kill ready + out of range → hunt.
4. Active fake-task timer → continue pressing A at the fake station.
5. Followee visible → tail, maybe roll the fake-task die while adjacent.
6. Wander toward a random fake target.

Every RNG-using branch pulls from a per-bot :class:`random.Random` seeded
from ``bot.rng_seed``. The streams are not split per-consumer as in Nim
(Q6) — we found the complexity not worth it for a scripted-only Python
port, but the hook is there: swap in per-consumer ``random.Random`` objects
on ``Bot`` if parity testing later demands it.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .. import actions, chat, diag
from ..state import Bot, PlayerSighting
from ..tuning import (
    CLOSE_DISTANCE,
    IMPOSTER_FAKE_TASK_APPROACH_RADIUS,
    IMPOSTER_FAKE_TASK_CHANCE,
    IMPOSTER_FAKE_TASK_CHANCE_DENOM,
    IMPOSTER_FAKE_TASK_COOLDOWN_TICKS,
    IMPOSTER_FAKE_TASK_MAX_TICKS,
    IMPOSTER_FAKE_TASK_MIN_TICKS,
    IMPOSTER_FAKE_TASK_NEAR_RADIUS,
    IMPOSTER_FOLLOW_SWAP_MIN_TICKS,
    IMPOSTER_SELF_REPORT_RADIUS,
    IMPOSTER_SELF_REPORT_RECENT_TICKS,
    KILL_RANGE,
)
from . import base
from .base import Policy

if TYPE_CHECKING:  # pragma: no cover
    from ..data import GameMap


class ImposterPolicy(Policy):
    """Imposter play: fake tasks, kill when safe, flee bodies."""

    def __init__(self) -> None:
        # One Random stream per agent, lazily created. The Nim version uses
        # per-consumer streams (Q6); Python scripted mode doesn't need that
        # level of determinism yet. If a test harness ever demands parity
        # across code changes, split these out.
        self._rng_by_agent: dict[int, random.Random] = {}

    # ------------------------------------------------------------------

    def decide(self, bot: Bot, game_map: "GameMap | None" = None) -> int:
        rng = self._rng(bot)

        # 1. Body in view.
        body = base.choose_body(bot)
        if body is not None:
            if self._is_our_recent_kill(bot, body):
                self._clear_fake_task(bot, cooldown=True)
                bot.imposter.last_kill_tick = -1
                base.clear_goal(bot)
                bot.fired("imp.body.self_report", "self-reporting kill")
                return actions.press_a_while(actions.NOOP)  # A = report body
            # Not our kill → flee (screen-space away-from: no path
            # involved, we just want to put distance between us and
            # the corpse).
            chat.queue_kill_defense(bot)
            diag.thought(bot, "fleeing body")
            flee_action = base.move_away_from(body.x, body.y, deadband=CLOSE_DISTANCE)
            self._clear_fake_task(bot)
            base.clear_goal(bot)
            bot.fired("imp.body.flee", "fleeing body")
            return base.anti_stuck_nudge(bot, flee_action or self._patrol(bot, rng))

        # 2/3. Hunt or kill.
        target = base.lone_non_teammate(bot)
        if target is not None and bot.imposter.kill_ready:
            if base.manhattan_from_center(target.x, target.y) <= KILL_RANGE:
                self._record_kill(bot, target)
                base.clear_goal(bot)
                bot.fired("imp.kill.in_range", f"kill {target.color}")
                return actions.A
            # Out of range → hunt. Path through the walk mask so we
            # don't ram the wall between us and the target.
            self._set_player_goal(bot, target, name=f"kill_{target.color}")
            intent = base.navigate_to_world_goal(bot, game_map, deadband=KILL_RANGE)
            bot.fired("imp.kill.hunt", "hunting lone crewmate")
            return base.anti_stuck_nudge(bot, intent)

        # 4. Continue an active fake-task.
        if self._fake_task_active(bot):
            task_info = self._fake_task_info(bot)
            if task_info is None:
                # Fake target vanished — wander.
                self._clear_fake_task(bot)
            else:
                if base.manhattan_from_center(task_info.x, task_info.y) <= IMPOSTER_FAKE_TASK_APPROACH_RADIUS:
                    base.clear_goal(bot)
                    bot.fired("imp.fake_task.holding", "holding fake task")
                    return actions.A
                self._set_task_goal(bot, task_info, game_map, name_prefix="fake_task")
                intent = base.navigate_to_world_goal(bot, game_map)
                bot.fired("imp.fake_task.setup", "approaching fake task")
                return base.anti_stuck_nudge(bot, intent)

        # 5. Followee mode.
        followee = self._pick_followee(bot, rng)
        if followee is not None:
            self._maybe_start_fake_task(bot, rng)
            if self._fake_task_active(bot):
                task_info = self._fake_task_info(bot)
                if task_info is not None:
                    self._set_task_goal(bot, task_info, game_map, name_prefix="fake_task")
                    intent = base.navigate_to_world_goal(bot, game_map)
                    bot.fired("imp.fake_task.setup_in_tail", "fake task while tailing")
                    return base.anti_stuck_nudge(bot, intent)
            self._set_player_goal(bot, followee, name=f"follow_{followee.color}")
            intent = base.navigate_to_world_goal(bot, game_map)
            bot.fired("imp.follow.tail", f"tailing {followee.color}")
            return base.anti_stuck_nudge(bot, intent)

        # 6. Wander.
        self._maybe_start_fake_task(bot, rng)
        if self._fake_task_active(bot):
            task_info = self._fake_task_info(bot)
            if task_info is not None:
                self._set_task_goal(bot, task_info, game_map, name_prefix="fake_task")
                intent = base.navigate_to_world_goal(bot, game_map)
                bot.fired("imp.fake_task.setup_in_wander", "fake task while wandering")
                return base.anti_stuck_nudge(bot, intent)

        base.clear_goal(bot)
        bot.fired("imp.wander.patrol", "wandering")
        return self._patrol(bot, rng)

    # ------------------------------------------------------------------
    # Goal setup helpers
    # ------------------------------------------------------------------

    def _set_player_goal(self, bot: Bot, player, *, name: str) -> None:
        """Record a screen-space player target as a world-space goal.

        Projects the player's on-screen sprite centre through the
        current camera to get a world coord, so A\\* can route to it.
        Fallback to screen-as-world when we can't project (state-obs
        mode or lost lock).
        """
        wx, wy = base.world_pos_from_screen(bot.percep, player.x, player.y)
        if wx < 0:
            wx, wy = player.x, player.y
        base.set_world_goal(
            bot, wx, wy, name=name, index=-1, screen_x=player.x, screen_y=player.y
        )

    def _set_task_goal(
        self,
        bot: Bot,
        task_info,
        game_map: "GameMap | None",
        *,
        name_prefix: str,
    ) -> None:
        """Record a task-station goal in world + screen coords.

        When the game map is available we look up the authoritative
        world rect centre so the pathfinder steers to the same point
        the sim considers "on the task". Missing game map falls back
        to the adapter's screen-projected ``task_info.x / y``.
        """
        screen_x = task_info.x if task_info.icon_visible else task_info.arrow_x
        screen_y = task_info.y if task_info.icon_visible else task_info.arrow_y
        if (
            game_map is not None
            and bot.percep.localized
            and 0 <= task_info.index < len(game_map.tasks)
        ):
            station = game_map.tasks[task_info.index]
            base.set_world_goal(
                bot,
                station.cx,
                station.cy,
                name=f"{name_prefix}_{task_info.index}",
                index=task_info.index,
                screen_x=screen_x,
                screen_y=screen_y,
            )
        else:
            base.set_world_goal(
                bot,
                screen_x,
                screen_y,
                name=f"{name_prefix}_{task_info.index}",
                index=task_info.index,
                screen_x=screen_x,
                screen_y=screen_y,
            )

    # ------------------------------------------------------------------
    # Fake-task die roll
    # ------------------------------------------------------------------

    def _maybe_start_fake_task(self, bot: Bot, rng: random.Random) -> None:
        imposter = bot.imposter
        if bot.percep.tick < imposter.fake_task_cooldown_tick:
            return
        if imposter.fake_task_until_tick > bot.percep.tick:
            return
        near = self._nearest_task_within(bot, IMPOSTER_FAKE_TASK_NEAR_RADIUS)
        if near is None:
            imposter.prev_near_task_index = -1
            return
        if near.index == imposter.prev_near_task_index:
            return
        imposter.prev_near_task_index = near.index
        if rng.randint(0, IMPOSTER_FAKE_TASK_CHANCE_DENOM - 1) >= IMPOSTER_FAKE_TASK_CHANCE:
            return
        span = IMPOSTER_FAKE_TASK_MAX_TICKS - IMPOSTER_FAKE_TASK_MIN_TICKS
        duration = IMPOSTER_FAKE_TASK_MIN_TICKS + rng.randint(0, span)
        imposter.fake_task_index = near.index
        imposter.fake_task_until_tick = bot.percep.tick + duration

    def _nearest_task_within(self, bot: Bot, radius: int):
        tasks = [
            t
            for t in bot.percep.tasks
            if t.icon_visible and t.index >= 0 and not bot.tasks.resolved[t.index]
            if t.index < len(bot.tasks.resolved)
        ]
        if not tasks:
            return None
        best = min(tasks, key=lambda t: base.manhattan_from_center(t.x, t.y))
        if base.manhattan_from_center(best.x, best.y) <= radius:
            return best
        return None

    def _fake_task_active(self, bot: Bot) -> bool:
        imposter = bot.imposter
        return (
            imposter.fake_task_until_tick > bot.percep.tick
            and imposter.fake_task_index >= 0
        )

    def _fake_task_info(self, bot: Bot):
        imposter = bot.imposter
        target = None
        for t in bot.percep.tasks:
            if t.index == imposter.fake_task_index:
                target = t
                break
        if target is None or (not target.icon_visible and not target.arrow_visible):
            return None
        return target

    def _clear_fake_task(self, bot: Bot, cooldown: bool = False) -> None:
        bot.imposter.fake_task_until_tick = 0
        bot.imposter.fake_task_index = -1
        if cooldown:
            bot.imposter.fake_task_cooldown_tick = (
                bot.percep.tick + IMPOSTER_FAKE_TASK_COOLDOWN_TICKS
            )

    # ------------------------------------------------------------------
    # Followee selection
    # ------------------------------------------------------------------

    def _pick_followee(self, bot: Bot, rng: random.Random) -> PlayerSighting | None:
        imposter = bot.imposter
        visible = base.visible_non_teammates(bot)
        if not visible:
            return None

        current = next(
            (p for p in visible if p.color == imposter.followee_color),
            None,
        )
        if (
            current is not None
            and len(visible) >= 2
            and bot.percep.tick - imposter.followee_since_tick >= IMPOSTER_FOLLOW_SWAP_MIN_TICKS
        ):
            alternatives = [p for p in visible if p.color != imposter.followee_color]
            if alternatives:
                pick = rng.choice(alternatives)
                imposter.followee_color = pick.color
                imposter.followee_since_tick = bot.percep.tick
                return pick
        if current is not None:
            return current
        pick = rng.choice(visible)
        imposter.followee_color = pick.color
        imposter.followee_since_tick = bot.percep.tick
        return pick

    # ------------------------------------------------------------------
    # Kill bookkeeping
    # ------------------------------------------------------------------

    def _record_kill(self, bot: Bot, target: PlayerSighting) -> None:
        bot.imposter.last_kill_tick = bot.percep.tick
        bot.imposter.last_kill_x = target.x
        bot.imposter.last_kill_y = target.y
        self._clear_fake_task(bot, cooldown=True)

    def _is_our_recent_kill(self, bot: Bot, body) -> bool:
        imposter = bot.imposter
        if imposter.last_kill_tick < 0:
            return False
        if bot.percep.tick - imposter.last_kill_tick > IMPOSTER_SELF_REPORT_RECENT_TICKS:
            return False
        dx = body.x - imposter.last_kill_x
        dy = body.y - imposter.last_kill_y
        return abs(dx) + abs(dy) <= IMPOSTER_SELF_REPORT_RADIUS

    # ------------------------------------------------------------------
    # Patrol fallback
    # ------------------------------------------------------------------

    def _patrol(self, bot: Bot, rng: random.Random) -> int:
        phase = ((bot.percep.tick // 36) + bot.rng_seed + bot.agent_id * 7) % 4
        del rng  # deterministic patrol; RNG arg is reserved for future use
        return (actions.RIGHT, actions.DOWN, actions.LEFT, actions.UP)[phase]

    # ------------------------------------------------------------------
    # RNG management
    # ------------------------------------------------------------------

    def _rng(self, bot: Bot) -> random.Random:
        rng = self._rng_by_agent.get(bot.agent_id)
        if rng is None:
            rng = random.Random(bot.rng_seed * 17 + bot.agent_id)
            self._rng_by_agent[bot.agent_id] = rng
        return rng
