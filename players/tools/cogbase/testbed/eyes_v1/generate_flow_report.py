#!/usr/bin/env python3
"""eyes_v1: deprecated multi-stage pipeline for game perception analysis.

Runs a 5-stage pipeline to produce:
  1. Visual/UI reports (3 runners + synthesis)
  2. State machine / flow reports (3 runners + synthesis)
  3. View-exploring agent design document
  4. Generated game-specific explorer implementation
  5. Captured frames and metadata

Usage:
    python generate_flow_report.py <path_or_url> [--output-dir <dir>]

Examples:
    python generate_flow_report.py ~/coding/bitworld/among_them
    python generate_flow_report.py ~/coding/bitworld/among_them --output-dir ./output/among_them
    python generate_flow_report.py ~/coding/bitworld/among_them --stage flow
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
import time
from pathlib import Path


DEPRECATION_NOTICE = (
    "eyes_v1 is deprecated as a primary Cogbase pipeline stage. "
    "Use testbed/guide_v1 first for canonical game understanding; run eyes_v1 "
    "only for legacy regeneration or targeted visual-artifact experiments."
)


# =============================================================================
# Prompt templates
# =============================================================================

UI_ANALYSIS_PROMPT = textwrap.dedent("""\
    You are an expert game UI/UX analyst and graphics cataloger. Your task is to
    perform a complete and comprehensive audit of the visuals, graphics, sprites,
    UI views, and UI elements of the game whose source code is located at:

        {source_location}

    Examine every relevant source file: rendering code, UI definitions, asset
    manifests, sprite sheets, scene definitions, view controllers, HTML/CSS
    templates, config files referencing visuals, and anything else that defines
    what a player *sees*.

    Produce a detailed Markdown report with the following structure:

    # Visual & UI Report: [Game Name]

    ## Overview
    A brief summary of the game's visual/graphical architecture (rendering
    engine, UI framework, asset pipeline, resolution, coordinate system, etc.)

    ## UI Views

    For EVERY distinct view/screen/scene in the game (e.g. main menu, lobby,
    settings, in-game HUD, chat overlay, inventory, game-over screen, loading
    screen, etc.), create a section:

    ### [View Name]

    **Description:** What this view is, when the player sees it, how they
    navigate to/from it.

    **Summary Table:**

    | Element | Type | Visual Description | Source Location |
    |---------|------|-------------------|-----------------|
    | ... | ... | ... | ... |

    The table must include EVERY graphical element that could appear in this
    view: buttons, labels, text fields, icons, sprites, animated elements,
    background layers, particle effects, overlays, progress bars, avatars,
    health bars, score displays, chat bubbles, tooltips, etc.

    **Element Details:**

    For each element in the table, provide a detailed paragraph covering:
    - Exact visual appearance (colors, dimensions, font, shape, animation)
    - States/variants (hover, active, disabled, selected, error)
    - Position/layout within the view
    - Source file(s) and line numbers where it is defined
    - Any relevant asset file paths (images, sprite sheets, fonts)

    ## Asset Inventory
    A summary of all graphical assets (images, sprite sheets, fonts, shaders,
    animations) with file paths and where they are used.

    ## Visual Constants & Theming
    Colors, fonts, spacing values, breakpoints, and any theming/skin system.

    ---

    Be exhaustive. Do not skip elements because they seem minor. Include every
    single visual element you can identify from the source code. If something is
    ambiguous, note the ambiguity rather than omitting it.

    IMPORTANT: Return the full report as your text response. Do NOT write it
    to a file. Output only the Markdown report content.
""")

UI_SYNTHESIS_PROMPT = textwrap.dedent("""\
    You are an expert technical editor and game UI analyst. You have been given
    three independently-generated visual/UI reports for the same game, each
    produced by a different AI coding agent. Your job is to synthesize these
    into a single, definitive, validated report.

    ## Source Material

    The three input reports are located at:

    1. {report_path_1}
    2. {report_path_2}
    3. {report_path_3}

    The game source code they analyze is located at:

        {source_location}

    ## Your Task

    Produce a single comprehensive synthesized report that:

    1. **Merges the best content from all three reports.** Combine element
       tables, asset inventories, and theming details into one complete
       document that is strictly better than any individual report.

    2. **Resolves contradictions.** Where reports disagree (dimensions, colors,
       palette values, source locations), check the actual source code to
       determine which is correct.

    3. **Validates completeness.** Ensure every UI view and every graphical
       element discoverable from the source code is documented.

    4. **Validates correctness.** Verify source locations, pixel dimensions,
       palette values, and asset paths against the actual code.

    5. **Fills gaps.** Add anything the source code reveals that none of the
       three reports mention.

    ## Output Format

    # Visual & UI Report: [Game Name] (Synthesized)

    ## Validation Summary
    - Claims verified, corrections made, gaps filled

    ## Overview
    [Merged overview]

    ## UI Views
    [Complete per-view documentation with element tables]

    ## Asset Inventory
    [Complete asset listing]

    ## Visual Constants & Theming
    [Complete constants and palette]

    ---

    IMPORTANT: Return the full synthesized report as your text response. Do
    NOT write it to a file. Output only the Markdown report content.
""")

FLOW_ANALYSIS_PROMPT = textwrap.dedent("""\
    You are an expert game systems analyst specializing in state machines,
    game flow, and agent automation. Your task is to reverse-engineer the
    complete game state machine from the source code located at:

        {source_location}

    The purpose of this report is to enable the design of a scripted agent (or
    set of agents) that can deterministically navigate to EVERY screen and view
    in the game. These agents will be used to run the game and capture frames
    of each view for developing and testing perception/vision systems.

    Examine all relevant source code: game loop logic, phase/state enums,
    transition functions, input handling, timer logic, event dispatching,
    network message handlers, and anything that governs what state the game is
    in and how it moves between states.

    Produce a detailed Markdown report with the following structure:

    # Game State Machine Report: [Game Name]

    ## Overview

    A brief summary of the game's state management architecture:
    - Where is game state defined? (enums, variables, classes)
    - What is the top-level state machine structure?
    - How are transitions triggered (timers, player actions, server events)?
    - What is the tick/frame rate and how does timing relate to state changes?

    ## State Diagram

    A text-based state diagram (Mermaid syntax preferred) showing ALL states
    and ALL transitions between them. Label each transition edge with its
    trigger condition.

    ## States

    For EVERY distinct game state/phase/screen, create a section:

    ### [State Name]

    **State identifier:** The enum value, variable state, or condition that
    defines this state in code (with source location).

    **Description:** What happens in this state, what the player/spectator
    sees, and how long it lasts.

    **Entry conditions:** Every way this state can be entered. For each:
    - Previous state
    - Trigger (timer expiry, player action, server event, player count, etc.)
    - Any required preconditions (e.g. "at least N players connected")
    - Source location of the transition logic

    **Exit conditions:** Every way this state can be exited. For each:
    - Next state
    - Trigger
    - Source location

    **Agent inputs available:** What inputs/actions an agent can perform
    while in this state. For each input:
    - Input type (button press, direction, chat message, etc.)
    - What it does / what state change it can cause
    - Protocol encoding (key codes, message format, etc.)
    - Source location of the input handler

    **Timing:** Any timers, countdowns, or tick-based durations that affect
    this state (values, source locations).

    **Multiplayer considerations:** How other players' actions affect
    transitions from this state. What happens if players join/leave during it.

    ## Transition Summary Table

    A single table listing every transition in the game:

    | From State | To State | Trigger | Agent-Controllable? | Timing | Source |
    |------------|----------|---------|---------------------|--------|--------|
    | ... | ... | ... | Yes/No/Partial | ... | ... |

    The "Agent-Controllable?" column indicates whether a scripted agent can
    force this transition through its own actions alone (Yes), whether it
    requires external conditions like other players (Partial), or whether it
    is purely automatic/timer-based (No).

    ## Agent Scripting Guide

    For each state/view that needs to be reached for frame capture, provide a
    concrete scripting recipe:

    ### Reaching [State Name]

    **Prerequisites:** What must be true before attempting (server config,
    player count, game phase, etc.)

    **Script steps:**
    1. [Specific action with timing]
    2. [Wait for condition / send input]
    3. ...

    **Verification:** How the agent can confirm it has arrived (frame content,
    protocol messages, timing).

    **Minimum players required:** How many connected agents/players are needed.

    ## Input Protocol Reference

    A complete reference of all inputs the game accepts:

    | Input | Encoding | Available In States | Effect | Source |
    |-------|----------|--------------------|---------| --------|
    | ... | ... | ... | ... | ... |

    Include button masks, directional inputs, chat/text inputs, and any
    special commands or admin inputs.

    ## Configuration & Setup

    Server configuration options that affect the state machine:
    - Player count thresholds
    - Timer durations
    - Feature toggles that enable/disable states
    - How to configure for fastest/easiest scripted traversal

    ---

    Be exhaustive. The goal is a report complete enough that someone could
    implement a scripted agent to reach every single game state without
    needing to read the source code themselves. If transitions have edge cases
    or race conditions, document them. If some states require specific server
    configurations, say so explicitly.

    IMPORTANT: Return the full report as your text response. Do NOT write it
    to a file. Output only the Markdown report content.
""")

FLOW_SYNTHESIS_PROMPT = textwrap.dedent("""\
    You are an expert technical editor and game systems analyst. You have been
    given three independently-generated state machine reports for the same game,
    each produced by a different AI coding agent. Your job is to synthesize
    these into a single, definitive, validated report.

    ## Source Material

    The three input reports are located at:

    1. {report_path_1}
    2. {report_path_2}
    3. {report_path_3}

    The game source code they analyze is located at:

        {source_location}

    ## Your Task

    Produce a single comprehensive synthesized report that:

    1. **Merges the best content from all three reports.** Each report has
       unique strengths -- one may document substates the others miss, another
       may have more precise protocol encodings, another may have better
       scripting recipes. Combine them into a unified whole that is strictly
       better than any individual report.

    2. **Resolves contradictions.** Where the reports disagree on specifics
       (line numbers, default values, transition conditions, encoding formats),
       check the actual source code at {source_location} to determine which is
       correct. Always prefer ground truth from the code.

    3. **Validates completeness.** Cross-reference the synthesized report
       against the source code to ensure:
       - Every game state/phase is documented (including substates like
         "Lobby Waiting" vs "Lobby Starting" if they produce distinct frames)
       - Every transition is accounted for (including edge cases like
         disconnect, admin reset, max ticks)
       - Every input protocol is correctly documented (byte encodings, bit
         masks, packet formats)
       - Every configuration option that affects the state machine is listed
       - All scripting recipes are actually achievable with the described
         inputs and configs

    4. **Validates correctness.** For every factual claim in the synthesized
       report (source locations, default values, protocol formats, transition
       conditions), verify it against the actual source code. If you cannot
       verify a claim, mark it with [UNVERIFIED] and explain what you checked.

    5. **Fills gaps.** If you discover states, transitions, inputs, or
       configuration options in the source code that NONE of the three reports
       mention, add them to the synthesized report.

    ## Output Format

    Produce the synthesized report in Markdown with this structure:

    # Game State Machine Report: [Game Name] (Synthesized)

    ## Validation Summary

    A brief section noting:
    - How many claims were verified against source
    - Any corrections made (what was wrong in the input reports)
    - Any gaps filled (what was missing from all input reports)
    - Any items marked [UNVERIFIED]

    ## Overview
    [Merged and validated overview]

    ## State Diagram
    [Single authoritative Mermaid diagram incorporating all states and
    transitions from all three reports, validated against source]

    ## States
    [Complete per-state documentation, merged from all three reports,
    with verified source locations]

    ## Transition Summary Table
    [Single authoritative table]

    ## Agent Scripting Guide
    [Merged recipes taking the best/most-detailed version of each,
    with corrections applied]

    ## Input Protocol Reference
    [Complete and verified protocol documentation]

    ## Configuration & Setup
    [Merged configuration reference with verified defaults and
    recommended configs for scripted traversal]

    ---

    Quality standards:
    - Every source location reference must be verified (file:line exists and
      contains what is claimed)
    - Every default value must match the actual code
    - Every protocol encoding must be byte-accurate
    - Scripting recipes must be actually executable given the documented
      inputs and configs
    - The report must be self-contained: a developer should be able to
      implement a complete frame-capture agent using only this document

    IMPORTANT: Return the full synthesized report as your text response. Do
    NOT write it to a file. Output only the Markdown report content.
""")

AGENT_DESIGN_PROMPT = textwrap.dedent("""\
    You are an expert agent systems architect. Your task is to design a
    view-exploring agent system for automated frame capture of every UI view
    in a game.

    ## Context

    You have two authoritative reference documents:

    1. **Synthesized Visual/UI Report** (what the agent will see):
       {ui_report_path}

    2. **Synthesized State Machine Report** (how the agent navigates):
       {flow_report_path}

    The game source code is at:
        {source_location}

    ## Design Requirements

    Design a **primitive FSM-based agent** (or set of cooperating agents, if
    the game requires multi-agent interaction like multiplayer games) with the
    following properties:

    ### Core Architecture

    - The agent(s) must be runnable via a **single script**. One script
      launches ALL agents needed for a given configuration, not one script per
      agent. The script accepts a "target view" argument (or "all" to cycle
      through every view).
    - Each run targets a specific game view/state. The script manages whatever
      agent constellation is required to reach that state (e.g., if reaching
      the voting screen requires 4 players, the script launches 4 agents with
      appropriate roles).
    - The agent FSM states should map to the game states documented in the
      flow report, with transitions driven by tick counting, frame analysis,
      or protocol-level signals.

    ### Frame Capture

    The agent(s) must capture and store frames as they run:

    1. **Periodic capture:** Store frames at a configurable interval (e.g.,
       every N ticks or every M seconds). Default to something reasonable
       like every 24 ticks (1 second at 24 FPS).

    2. **Change-detection capture:** Additionally store a frame whenever it
       differs from the previous frame by more than a threshold amount. Use a
       LOW threshold -- false positives (capturing redundant frames) are
       strongly preferred over false negatives (missing view transitions).
       Suggested approach: compute pixel-level difference ratio between
       consecutive frames; if more than ~5% of pixels changed, capture.

    3. **Frame metadata:** Each captured frame should be stored with metadata:
       - Timestamp (tick number)
       - Agent's current FSM state
       - Target view being explored
       - Capture reason (periodic / change-detected / state-transition)
       - Configuration used

    4. **Storage format:** Frames stored as PNG images in a structured
       directory layout organized by target view and capture session.

    ### Target Views

    The agent must be able to reach EVERY view documented in the UI report.
    For each view, the design must specify:
    - Which agents are needed (count, roles)
    - Server configuration required
    - The FSM state sequence to reach the target
    - Expected frame characteristics for verification

    ### Script Interface

    The single launcher script should accept:
    - `--target <view_name | all>` -- which view(s) to explore
    - `--output-dir <path>` -- where to store captured frames
    - `--server-address <host:port>` -- game server to connect to
    - `--capture-interval <ticks>` -- periodic capture rate
    - `--change-threshold <float>` -- pixel difference ratio for change capture
    - `--duration <ticks>` -- how long to run per view before moving on
    - Any other parameters you deem necessary

    ### Design for Downstream Use

    The ultimate consumer of this agent's output is another agent that will:
    - Use captured frames as test fixtures for perception system development
    - Use the frame metadata to understand what view each frame represents
    - Potentially re-run the explorer agent to generate fresh data on demand

    ## Output Format

    Produce a detailed Markdown design document:

    # View-Exploring Agent Design Document

    ## Overview
    High-level architecture summary.

    ## Agent Architecture
    - FSM states and transitions
    - How agents coordinate (if multi-agent)
    - Communication protocol with game server

    ## Frame Capture System
    - Capture logic (periodic + change-detection)
    - Storage layout and metadata format
    - Threshold tuning rationale

    ## View Exploration Configurations
    For EACH target view:
    ### [View Name]
    - Agents required (count, roles, config)
    - Server config JSON
    - FSM sequence to reach view
    - Expected duration
    - Verification criteria

    ## Script Interface
    - CLI arguments
    - Example invocations for each view
    - "Run all" behavior

    ## Implementation Plan
    - Recommended language/framework
    - Key dependencies
    - File structure
    - Implementation order (what to build first)

    ## Data Format Specification
    - Frame file naming convention
    - Metadata JSON schema
    - Directory structure

    ---

    Be specific and concrete. The design should be detailed enough that a
    developer (or coding agent) could implement it without further design
    decisions. Include actual protocol bytes, actual config JSONs, actual
    file paths. Reference the source reports for any details you rely on.

    IMPORTANT: Return the full design document as your text response. Do NOT
    write it to a file. Output only the Markdown document content.
""")

IMPL_PLAN_PROMPT = textwrap.dedent("""\
    You are an expert Python developer. You have been given a detailed design
    document for a view-exploring agent system. Your task is to produce a
    comprehensive implementation plan that another coding agent will follow to
    build the system.

    ## Design Document

    Read the full design document at:

        {design_doc_path}

    The game source code (which the agents will connect to) is at:

        {source_location}

    The implementation will live in:

        {impl_dir}

    ## Your Task

    Produce a detailed implementation plan as a Markdown file. The plan must
    cover:

    ### 1. File-by-File Implementation Specification

    For each file in the implementation (following the file structure from the
    design doc), specify:
    - Exact file path
    - All classes/functions to implement with signatures and docstrings
    - Key logic and algorithms (pseudocode where helpful)
    - Dependencies on other files in the project
    - Any tricky edge cases to handle

    ### 2. Testing Strategy

    Design a thorough test suite covering:

    **Unit tests** (per-module):
    - `test_protocol.py` — packet encoding/decoding, mask constants, edge cases
    - `test_frame_codec.py` — 4bpp unpacking, palette mapping, PNG round-trip,
      malformed input handling
    - `test_capture.py` — periodic trigger logic, change-detection math,
      metadata generation, directory creation, threshold edge cases
    - `test_agent.py` — FSM state transitions, input scheduling, fresh-edge
      logic, connection error handling
    - `test_orchestrator.py` — multi-agent coordination, tick synchronization,
      action dispatch timing
    - `test_view_configs.py` — config validity (all required keys present,
      agent counts match, durations are positive)

    **Integration tests:**
    - End-to-end test with a mock WebSocket server that sends canned frames
    - Test that frame capture produces correct PNGs for known inputs
    - Test "run all" mode completes without error against mock server
    - Test graceful shutdown (server dies mid-session, agent disconnects)

    **Failure mode tests:**
    - Server unreachable (connection refused)
    - Server sends malformed frames (wrong size, truncated)
    - Server drops connection mid-session
    - Port already in use
    - Output directory not writable
    - Invalid --target argument
    - Zero-length frames / empty responses

    **Property-based / edge-case tests:**
    - Threshold boundary: exactly 5% pixels changed → should capture
    - Threshold boundary: 4.99% pixels changed → should NOT capture
    - All-black frame vs all-white frame (maximum diff)
    - Identical consecutive frames (zero diff)
    - Frame at tick 0 (no previous frame for diff)
    - Very long session (tick counter overflow? probably not at 32-bit, but document)

    ### 3. Documentation Plan

    After implementation, document the generated tool inside the implementation
    root:
    - `README.md` — usage docs for the generated explorer
    - `DEVELOPMENT.md` — setup, running tests, architecture overview
    - Inline docstrings on all public functions/classes

    Do not edit the eyes_v1 toolkit README as part of generated explorer
    implementation. The explorer is an artifact produced by eyes_v1, not part
    of the reusable eyes_v1 toolkit.

    ### 4. Implementation Order

    Specify the exact order to implement files, with rationale. Each step
    should be independently testable before moving to the next.

    ### 5. Dependency Setup

    Exact commands to set up the Python environment, install dependencies,
    and verify the setup works.

    ---

    Be extremely specific. The implementation plan should be unambiguous enough
    that a coding agent can follow it step-by-step without making design
    decisions. Include concrete types, exact function signatures, actual byte
    values, and real file paths.

    Write the plan to a file at: {plan_output_path}
""")

IMPL_REVIEW_PROMPT = textwrap.dedent("""\
    You are a senior software architect conducting a design and implementation
    plan review. You are reviewing a plan for building a view-exploring agent
    system for a game.

    ## Documents to Review

    1. **Design document** (the specification the plan should implement):
       {design_doc_path}

    2. **Implementation plan** (what you are reviewing):
       {plan_path}

    3. **Game source code** (for validating protocol/config claims):
       {source_location}

    ## Review Criteria

    Evaluate the implementation plan on:

    1. **Completeness:** Does it cover every requirement from the design doc?
       Are there features in the design that the plan doesn't address?

    2. **Correctness:** Are the protocol encodings, config values, and game
       mechanics referenced in the plan consistent with the actual source code?

    3. **Test coverage:** Are the tests thorough enough? Do they cover:
       - All happy paths (every view config works)
       - Error handling (connection failures, malformed data, timeouts)
       - Edge cases (threshold boundaries, empty frames, tick 0)
       - Integration (end-to-end with mock server)

    4. **Implementation order:** Is the proposed build order correct? Are there
       dependency issues where a later module is needed by an earlier one?

    5. **Risks and gaps:** What could go wrong? What's underspecified? What
       might a coding agent struggle with or get wrong?

    ## Output Format

    Produce a structured review:

    # Implementation Plan Review

    ## Verdict
    APPROVED / APPROVED WITH CHANGES / NEEDS REVISION

    ## Strengths
    - What the plan does well

    ## Required Changes
    - Things that MUST be fixed before implementation (blocking issues)

    ## Recommended Changes
    - Things that SHOULD be improved (non-blocking but valuable)

    ## Risks
    - Things to watch for during implementation

    ## Additional Test Cases
    - Any tests the plan is missing

    ## Notes for the Implementer
    - Clarifications, warnings, or tips for the coding agent that will
      execute this plan

    ---

    Be rigorous. The plan will be executed by an AI coding agent that follows
    instructions literally. Ambiguities or gaps in the plan will result in
    incorrect implementation.

    IMPORTANT: Return the full review as your text response. Do NOT write it
    to a file. Output only the Markdown review content.
""")

IMPL_EXECUTE_PROMPT = textwrap.dedent("""\
    You previously generated an implementation plan. A senior architect has
    reviewed that plan and provided feedback. Your task is now to IMPLEMENT
    the plan, incorporating the review feedback.

    ## Review Feedback

    The review is at: {review_path}

    Read it carefully. Pay special attention to:
    - "Required Changes" — these MUST be addressed in your implementation
    - "Recommended Changes" — incorporate these where feasible
    - "Notes for the Implementer" — heed these warnings

    ## Design Document

    The authoritative design specification is at: {design_doc_path}

    ## Implementation Location

    Implement everything under: {impl_dir}

    ## Instructions

    1. Follow your implementation plan step by step, in the order specified.
    2. For each file, write the complete implementation (not stubs).
    3. Write all tests as specified in the plan.
    4. Address every "Required Change" from the review.
    5. After implementation, update documentation as specified.
    6. Run the tests to verify they pass. Fix any failures.

    Do not skip steps. Do not leave TODOs. Implement everything completely.
""")

CAPTURE_CHECKLIST_PROMPT = textwrap.dedent("""\
    You are a QA engineer preparing a comprehensive frame-capture test plan.
    You have a synthesized UI report that documents every visual view/screen
    in a game, and you have a view-exploring tool that can capture frames from
    specific views.

    ## UI Report

    Read the synthesized UI report at:

        {ui_report_path}

    ## Available Tool

    The view-exploring tool is at:

        {explore_script}

    It accepts `--target <view_name>` where valid view names can be listed
    by running `python {explore_script} --help` or inspecting its view
    config registry.

    ## Your Task

    1. Read the UI report to identify EVERY distinct visual view/screen/state
       that exists in the game.

    2. For each view, determine:
       - Whether the explore_views tool has a matching target name for it
       - If not, what the closest available target is (or note it as a gap)

    3. Produce a checklist as a JSON array with this schema:

    ```json
    [
      {{
        "view_name": "human-readable name of the view",
        "target": "explore_views --target value (or null if no match)",
        "description": "brief description of what this view shows",
        "capturable": true/false,
        "notes": "any caveats or issues"
      }}
    ]
    ```

    Include ALL views from the UI report, even if they can't be captured by
    the current tool (mark those as `capturable: false` with an explanation
    in notes).

    IMPORTANT: Return ONLY the JSON array. No commentary, no markdown fencing,
    no explanation before or after. Just the raw JSON.
""")

CAPTURE_EXECUTE_PROMPT = textwrap.dedent("""\
    You are an automation engineer running a frame-capture tool to collect
    screenshots of every view in a game. You have a checklist of views to
    capture and a tool to do it.

    ## Checklist

    The capture checklist (JSON) is at:

        {checklist_path}

    Read it. For every entry where `capturable` is `true`, you will run the
    tool to capture frames for that view.

    ## Tool

    The view-exploring script is at:

        {explore_script}

    Run it like this for each capturable view:

        python {explore_script} \\
            --target <target_from_checklist> \\
            --output-dir {output_dir} \\
            --among-them-dir {source_location} \\
            --server-port {server_port} \\
            --duration 120

    Use a DIFFERENT port for each run to avoid conflicts (increment from
    {server_port}).

    ## Instructions

    1. Read the checklist.
    2. For each capturable view, run the tool with the appropriate --target.
    3. Wait for each run to complete before starting the next.
    4. After all runs complete, produce a Markdown summary file listing:
       - Each view attempted
       - Whether it succeeded or failed
       - How many frames were captured
       - The path to the session directory containing the frames

    Write this summary to: {manifest_path}

    The summary should be a Markdown file with this structure:

    # Frame Capture Results

    ## Summary
    - Total views attempted: N
    - Successful: N
    - Failed: N
    - Total frames captured: N

    ## Results

    | View | Target | Status | Frames | Session Path |
    |------|--------|--------|--------|--------------|
    | ... | ... | ... | ... | ... |

    ## Failures
    For each failed view, include the error output.

    ## Notes
    Any observations about the captures (views that produced unexpected
    results, views that need different configs, etc.)

    Run every capturable view. Do not skip any. If a view fails, log the
    failure and continue to the next one.
""")

# =============================================================================
# Prompt builders
# =============================================================================

def build_ui_analysis_prompt(source_location: str) -> str:
    """Fill the UI analysis prompt template."""
    return UI_ANALYSIS_PROMPT.format(source_location=source_location)


def build_ui_synthesis_prompt(
    report_paths: list[str],
    source_location: str,
) -> str:
    """Fill the UI synthesis prompt template."""
    paths = report_paths + ["(not available)"] * (3 - len(report_paths))
    return UI_SYNTHESIS_PROMPT.format(
        report_path_1=paths[0],
        report_path_2=paths[1],
        report_path_3=paths[2],
        source_location=source_location,
    )


def build_flow_analysis_prompt(source_location: str) -> str:
    """Fill the flow analysis prompt template."""
    return FLOW_ANALYSIS_PROMPT.format(source_location=source_location)


def build_flow_synthesis_prompt(
    report_paths: list[str],
    source_location: str,
) -> str:
    """Fill the flow synthesis prompt template."""
    paths = report_paths + ["(not available)"] * (3 - len(report_paths))
    return FLOW_SYNTHESIS_PROMPT.format(
        report_path_1=paths[0],
        report_path_2=paths[1],
        report_path_3=paths[2],
        source_location=source_location,
    )


def build_agent_design_prompt(
    ui_report_path: str,
    flow_report_path: str,
    source_location: str,
) -> str:
    """Fill the agent design prompt template."""
    return AGENT_DESIGN_PROMPT.format(
        ui_report_path=ui_report_path,
        flow_report_path=flow_report_path,
        source_location=source_location,
    )


def build_impl_plan_prompt(
    design_doc_path: str,
    source_location: str,
    impl_dir: str,
    plan_output_path: str,
) -> str:
    """Fill the implementation plan prompt template."""
    return IMPL_PLAN_PROMPT.format(
        design_doc_path=design_doc_path,
        source_location=source_location,
        impl_dir=impl_dir,
        plan_output_path=plan_output_path,
    )


def build_impl_review_prompt(
    design_doc_path: str,
    plan_path: str,
    source_location: str,
) -> str:
    """Fill the implementation review prompt template."""
    return IMPL_REVIEW_PROMPT.format(
        design_doc_path=design_doc_path,
        plan_path=plan_path,
        source_location=source_location,
    )


def build_impl_execute_prompt(
    review_path: str,
    design_doc_path: str,
    impl_dir: str,
) -> str:
    """Fill the implementation execution prompt template."""
    return IMPL_EXECUTE_PROMPT.format(
        review_path=review_path,
        design_doc_path=design_doc_path,
        impl_dir=impl_dir,
    )


def build_capture_checklist_prompt(
    ui_report_path: str,
    explore_script: str,
) -> str:
    """Fill the capture checklist prompt template."""
    return CAPTURE_CHECKLIST_PROMPT.format(
        ui_report_path=ui_report_path,
        explore_script=explore_script,
    )


def build_capture_execute_prompt(
    checklist_path: str,
    explore_script: str,
    output_dir: str,
    source_location: str,
    server_port: int,
    manifest_path: str,
) -> str:
    """Fill the capture execution prompt template."""
    return CAPTURE_EXECUTE_PROMPT.format(
        checklist_path=checklist_path,
        explore_script=explore_script,
        output_dir=output_dir,
        source_location=source_location,
        server_port=server_port,
        manifest_path=manifest_path,
    )


# =============================================================================
# Runner functions
# =============================================================================

RUNNER_TIMEOUT = 1800  # 30 minutes per runner (default)


def run_opencode(
    prompt: str,
    working_dir: str | None,
    timeout: int,
    *,
    skip_permissions: bool = False,
) -> str:
    """Run the prompt through opencode's headless CLI."""
    cmd = ["opencode", "run"]
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    cmd.append(prompt)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=working_dir,
        timeout=timeout,
    )
    return result.stdout or result.stderr


def run_codex(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Run the prompt through codex's non-interactive exec mode (read-only)."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "codex", "exec",
                "-s", "read-only",
                "-o", tmp_path,
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=timeout,
        )
        output_path = Path(tmp_path)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path.read_text(encoding="utf-8")
        return result.stdout or result.stderr
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_codex_writable(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Run codex with workspace-write permissions (for implementation).

    Sets cwd to working_dir so that directory is the writable workspace.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "codex", "exec",
                "-s", "workspace-write",
                "-o", tmp_path,
                "-",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=timeout,
        )
        output_path = Path(tmp_path)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path.read_text(encoding="utf-8")
        return result.stdout or result.stderr
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_codex_resume(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Resume the most recent codex session with a new prompt.

    Uses workspace-write sandbox since this is used for implementation.
    Note: codex exec resume doesn't accept -s; sandbox is inherited from
    the original session.
    """
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "codex", "exec", "resume", "--last",
                "-o", tmp_path,
                prompt,
            ],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=timeout,
        )
        output_path = Path(tmp_path)
        if output_path.exists() and output_path.stat().st_size > 0:
            return output_path.read_text(encoding="utf-8")
        return result.stdout or result.stderr
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def run_claude(prompt: str, working_dir: str | None, timeout: int) -> str:
    """Run the prompt through claude's print (non-interactive) mode."""
    cmd = ["claude", "--print", prompt]
    if working_dir:
        cmd.extend(["--add-dir", working_dir])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=working_dir,
        timeout=timeout,
    )
    return result.stdout or result.stderr


RUNNERS = {
    "opencode": run_opencode,
    "codex": run_codex,
    "claude": run_claude,
}


# =============================================================================
# Pipeline helpers
# =============================================================================

def resolve_source_location(path_or_url: str) -> tuple[str, str | None]:
    """Resolve input to a (location_string, working_dir_or_none) tuple."""
    if path_or_url.startswith(("http://", "https://", "git@")):
        return path_or_url, None
    resolved = Path(path_or_url).expanduser().resolve()
    if not resolved.exists():
        print(f"Error: path does not exist: {resolved}", file=sys.stderr)
        sys.exit(1)
    return str(resolved), str(resolved)


def run_analysis_stage(
    prompt: str,
    runners: list[str],
    working_dir: str | None,
    output_dir: Path,
    prefix: str,
    timestamp: str,
    timeout: int,
) -> list[str]:
    """Run an analysis prompt through multiple runners, return output paths."""
    report_paths: list[str] = []

    for runner_name in runners:
        print(f"  [{runner_name}] Running...", flush=True)
        runner_fn = RUNNERS[runner_name]
        try:
            output = runner_fn(prompt, working_dir, timeout)
        except subprocess.TimeoutExpired:
            output = f"# Error\n\nRunner `{runner_name}` timed out after {timeout} seconds."
            print(f"  [{runner_name}] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            output = f"# Error\n\n`{runner_name}` CLI not found on PATH."
            print(f"  [{runner_name}] CLI NOT FOUND", file=sys.stderr)

        filename = f"{prefix}_{runner_name}_{timestamp}.md"
        out_path = output_dir / filename
        out_path.write_text(output, encoding="utf-8")
        report_paths.append(str(out_path))
        print(f"  [{runner_name}] Done -> {out_path}")

    return report_paths


def run_synthesis_stage(
    prompt: str,
    working_dir: str | None,
    output_dir: Path,
    prefix: str,
    timestamp: str,
    timeout: int,
) -> str | None:
    """Run a synthesis prompt through opencode, return output path or None."""
    try:
        output = run_opencode(
            prompt, working_dir, timeout,
            skip_permissions=True,
        )
    except subprocess.TimeoutExpired:
        output = f"# Error\n\nSynthesis timed out after {timeout} seconds."
        print("  [synthesis] TIMED OUT", file=sys.stderr)
    except FileNotFoundError:
        output = "# Error\n\n`opencode` CLI not found on PATH."
        print("  [synthesis] CLI NOT FOUND", file=sys.stderr)

    filename = f"{prefix}_synthesized_{timestamp}.md"
    out_path = output_dir / filename
    out_path.write_text(output, encoding="utf-8")
    print(f"  [synthesis] Done -> {out_path}")

    # Return path only if output is substantial
    if out_path.stat().st_size > 500:
        return str(out_path)
    return None


def filter_valid_reports(report_paths: list[str], min_size: int = 500) -> list[str]:
    """Filter out reports that are too short to be useful."""
    return [p for p in report_paths if Path(p).stat().st_size > min_size]


# =============================================================================
# Main pipeline
# =============================================================================

STAGES = ["ui", "flow", "design", "implement", "capture"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Deprecated multi-stage pipeline for game perception analysis. "
            "Generates UI reports, flow reports, agent design, implementation, "
            "and capture artifacts. Use guide_v1 first for canonical docs."
        ),
    )
    parser.add_argument(
        "source",
        help="Directory path or URL to the game's source code.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to write generated artifacts into (default: ./output).",
    )
    parser.add_argument(
        "--runners",
        nargs="+",
        choices=list(RUNNERS.keys()),
        default=list(RUNNERS.keys()),
        help="Which CLI runners to use for analysis stages (default: all three).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=RUNNER_TIMEOUT,
        help=f"Timeout in seconds per runner (default: {RUNNER_TIMEOUT}).",
    )
    parser.add_argument(
        "--stage",
        nargs="+",
        choices=STAGES + ["all"],
        default=["all"],
        help="Which stages to run (default: all).",
    )
    parser.add_argument(
        "--ui-report",
        help="Path to existing synthesized UI report (skip UI stage).",
    )
    parser.add_argument(
        "--flow-report",
        help="Path to existing synthesized flow report (skip flow stage).",
    )
    parser.add_argument(
        "--design-doc",
        help="Path to existing agent design document (skip design stage).",
    )
    parser.add_argument(
        "--capture-port",
        type=int,
        default=9800,
        help="Starting port for capture runs (default: 9800).",
    )
    args = parser.parse_args()

    print(f"DEPRECATED: {DEPRECATION_NOTICE}", file=sys.stderr)

    source_location, working_dir = resolve_source_location(args.source)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runner_timeout = args.timeout
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Determine which stages to run
    stages_to_run = set(STAGES) if "all" in args.stage else set(args.stage)

    print(f"Source: {source_location}")
    print(f"Output: {output_dir}")
    print(f"Stages: {', '.join(sorted(stages_to_run))}")
    print(f"Runners: {', '.join(args.runners)}")
    print()

    # Track synthesized report paths for the design stage
    ui_synth_path: str | None = args.ui_report
    flow_synth_path: str | None = args.flow_report
    design_doc_path: str | None = args.design_doc

    # --- UI Stage ---

    if "ui" in stages_to_run and not ui_synth_path:
        print("=" * 60)
        print("STAGE: UI/Visual Analysis")
        print("=" * 60)
        print()

        # Analysis
        print("Phase 1: Individual analyses")
        ui_prompt = build_ui_analysis_prompt(source_location)
        ui_reports = run_analysis_stage(
            ui_prompt, args.runners, working_dir, output_dir,
            "ui_report", timestamp, runner_timeout,
        )
        print()

        # Synthesis
        valid_ui = filter_valid_reports(ui_reports)
        if len(valid_ui) >= 2:
            print("Phase 2: Synthesis and validation")
            synth_prompt = build_ui_synthesis_prompt(valid_ui, source_location)
            ui_synth_path = run_synthesis_stage(
                synth_prompt, working_dir, output_dir,
                "ui_report", timestamp, runner_timeout,
            )
        else:
            print(f"Skipping UI synthesis: need >=2 valid reports, got {len(valid_ui)}")
            # Use the best individual report as fallback
            if valid_ui:
                ui_synth_path = valid_ui[0]

        print()

    # --- Flow Stage ---

    if "flow" in stages_to_run and not flow_synth_path:
        print("=" * 60)
        print("STAGE: State Machine / Flow Analysis")
        print("=" * 60)
        print()

        # Analysis
        print("Phase 1: Individual analyses")
        flow_prompt = build_flow_analysis_prompt(source_location)
        flow_reports = run_analysis_stage(
            flow_prompt, args.runners, working_dir, output_dir,
            "flow_report", timestamp, runner_timeout,
        )
        print()

        # Synthesis
        valid_flow = filter_valid_reports(flow_reports)
        if len(valid_flow) >= 2:
            print("Phase 2: Synthesis and validation")
            synth_prompt = build_flow_synthesis_prompt(valid_flow, source_location)
            flow_synth_path = run_synthesis_stage(
                synth_prompt, working_dir, output_dir,
                "flow_report", timestamp, runner_timeout,
            )
        else:
            print(f"Skipping flow synthesis: need >=2 valid reports, got {len(valid_flow)}")
            if valid_flow:
                flow_synth_path = valid_flow[0]

        print()

    # --- Design Stage ---

    if "design" in stages_to_run and not design_doc_path:
        print("=" * 60)
        print("STAGE: View-Exploring Agent Design")
        print("=" * 60)
        print()

        if not ui_synth_path:
            print("ERROR: No UI report available. Run the 'ui' stage first or")
            print("       provide one via --ui-report.")
            sys.exit(1)
        if not flow_synth_path:
            print("ERROR: No flow report available. Run the 'flow' stage first or")
            print("       provide one via --flow-report.")
            sys.exit(1)

        print(f"UI report: {Path(ui_synth_path).name}")
        print(f"Flow report: {Path(flow_synth_path).name}")
        print()

        design_prompt = build_agent_design_prompt(
            ui_synth_path, flow_synth_path, source_location,
        )

        print("Generating agent design document via opencode...")
        try:
            design_output = run_opencode(
                design_prompt, working_dir, runner_timeout,
                skip_permissions=True,
            )
        except subprocess.TimeoutExpired:
            design_output = (
                f"# Error\n\nDesign generation timed out after {runner_timeout} seconds."
            )
            print("  [design] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            design_output = "# Error\n\n`opencode` CLI not found on PATH."
            print("  [design] CLI NOT FOUND", file=sys.stderr)

        design_filename = f"agent_design_{timestamp}.md"
        design_doc_path = str(output_dir / design_filename)
        Path(design_doc_path).write_text(design_output, encoding="utf-8")
        print(f"  [design] Done -> {design_doc_path}")
        print()

    # --- Implementation Stage ---

    if "implement" in stages_to_run:
        print("=" * 60)
        print("STAGE: Implementation (Plan → Review → Execute)")
        print("=" * 60)
        print()

        if not design_doc_path:
            print("ERROR: No design document available. Run the 'design' stage")
            print("       first or provide one via --design-doc.")
            sys.exit(1)

        # Implementation directory lives alongside the reports
        impl_dir = str(output_dir / "explore_views")
        Path(impl_dir).mkdir(parents=True, exist_ok=True)

        plan_filename = f"implementation_plan_{timestamp}.md"
        plan_path = str(output_dir / plan_filename)

        # Phase 1: Codex generates implementation plan
        print("Phase 1: Generating implementation plan (codex)...")
        print(f"  Design doc: {Path(design_doc_path).name}")
        print(f"  Impl dir: {impl_dir}")
        print()

        plan_prompt = build_impl_plan_prompt(
            design_doc_path, source_location, impl_dir, plan_path,
        )

        # Run codex from the output dir so it can write the plan there
        try:
            plan_output = run_codex_writable(plan_prompt, str(output_dir), runner_timeout)
        except subprocess.TimeoutExpired:
            plan_output = f"# Error\n\nPlan generation timed out after {runner_timeout} seconds."
            print("  [plan] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            plan_output = "# Error\n\n`codex` CLI not found on PATH."
            print("  [plan] CLI NOT FOUND", file=sys.stderr)

        # Write plan (codex may have written it to plan_path, or returned it)
        if not Path(plan_path).exists() or Path(plan_path).stat().st_size < 500:
            Path(plan_path).write_text(plan_output, encoding="utf-8")
        print(f"  [plan] Done -> {plan_path}")
        print()

        # Phase 2: OpenCode reviews the plan
        print("Phase 2: Reviewing implementation plan (opencode)...")

        review_prompt = build_impl_review_prompt(
            design_doc_path, plan_path, source_location,
        )

        try:
            review_output = run_opencode(
                review_prompt, working_dir, runner_timeout,
                skip_permissions=True,
            )
        except subprocess.TimeoutExpired:
            review_output = (
                "# Implementation Plan Review\n\n## Verdict\nAPPROVED\n\n"
                "(Review timed out — proceeding with plan as-is.)"
            )
            print("  [review] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            review_output = (
                "# Implementation Plan Review\n\n## Verdict\nAPPROVED\n\n"
                "(opencode not found — proceeding with plan as-is.)"
            )
            print("  [review] CLI NOT FOUND", file=sys.stderr)

        review_filename = f"implementation_review_{timestamp}.md"
        review_path = str(output_dir / review_filename)
        Path(review_path).write_text(review_output, encoding="utf-8")
        print(f"  [review] Done -> {review_path}")
        print()

        # Phase 3: Codex implements (resumed session with review feedback)
        print("Phase 3: Implementing plan with review feedback (codex, resumed)...")
        print(f"  Review: {Path(review_path).name}")
        print()

        execute_prompt = build_impl_execute_prompt(
            review_path, design_doc_path, impl_dir,
        )

        # Run from impl_dir so codex can write implementation files there
        try:
            impl_output = run_codex_resume(execute_prompt, impl_dir, runner_timeout)
        except subprocess.TimeoutExpired:
            impl_output = "# Error\n\nImplementation timed out."
            print("  [implement] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            impl_output = "# Error\n\n`codex` CLI not found on PATH."
            print("  [implement] CLI NOT FOUND", file=sys.stderr)

        impl_log_filename = f"implementation_log_{timestamp}.md"
        impl_log_path = output_dir / impl_log_filename
        impl_log_path.write_text(impl_output, encoding="utf-8")
        print(f"  [implement] Done -> {impl_log_path}")
        print(f"  Implementation directory: {impl_dir}")
        print()

    # --- Capture Stage ---

    if "capture" in stages_to_run:
        print("=" * 60)
        print("STAGE: Frame Capture (Checklist → Execute → Manifest)")
        print("=" * 60)
        print()

        # Locate the explore_views script
        explore_script = str(output_dir / "explore_views" / "explore_views.py")
        if not Path(explore_script).exists():
            print("ERROR: explore_views.py not found at expected location:")
            print(f"       {explore_script}")
            print("       Run the 'implement' stage first.")
            sys.exit(1)

        if not ui_synth_path:
            print("ERROR: No UI report available. Run the 'ui' stage first or")
            print("       provide one via --ui-report.")
            sys.exit(1)

        capture_output_dir = str(output_dir / "captured_frames")
        Path(capture_output_dir).mkdir(parents=True, exist_ok=True)

        # Phase 1: Generate checklist of all views to capture
        print("Phase 1: Generating capture checklist (opencode)...")

        checklist_prompt = build_capture_checklist_prompt(
            ui_synth_path, explore_script,
        )

        try:
            checklist_output = run_opencode(
                checklist_prompt, working_dir, runner_timeout,
                skip_permissions=True,
            )
        except subprocess.TimeoutExpired:
            checklist_output = "[]"
            print("  [checklist] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            checklist_output = "[]"
            print("  [checklist] CLI NOT FOUND", file=sys.stderr)

        checklist_filename = f"capture_checklist_{timestamp}.json"
        checklist_path = str(output_dir / checklist_filename)
        Path(checklist_path).write_text(checklist_output, encoding="utf-8")
        print(f"  [checklist] Done -> {checklist_path}")
        print()

        # Phase 2: Execute captures for all views
        print("Phase 2: Running frame capture for all views (opencode)...")

        manifest_filename = f"capture_results_{timestamp}.md"
        manifest_path = str(output_dir / manifest_filename)

        execute_prompt = build_capture_execute_prompt(
            checklist_path=checklist_path,
            explore_script=explore_script,
            output_dir=capture_output_dir,
            source_location=source_location,
            server_port=args.capture_port,
            manifest_path=manifest_path,
        )

        try:
            capture_log = run_opencode(
                execute_prompt, str(output_dir), runner_timeout,
                skip_permissions=True,
            )
        except subprocess.TimeoutExpired:
            capture_log = "# Error\n\nCapture execution timed out."
            print("  [capture] TIMED OUT", file=sys.stderr)
        except FileNotFoundError:
            capture_log = "# Error\n\n`opencode` CLI not found on PATH."
            print("  [capture] CLI NOT FOUND", file=sys.stderr)

        # If opencode didn't write the manifest, save its output as the manifest
        if not Path(manifest_path).exists() or Path(manifest_path).stat().st_size < 100:
            Path(manifest_path).write_text(capture_log, encoding="utf-8")

        print(f"  [capture] Done -> {manifest_path}")
        print(f"  Frames directory: {capture_output_dir}")
        print()

    print("Pipeline complete.")


if __name__ == "__main__":
    main()
