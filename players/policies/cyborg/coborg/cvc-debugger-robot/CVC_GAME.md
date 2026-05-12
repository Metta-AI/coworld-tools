# CvC Game Mechanics

## Overview

Cogs vs Clips (CvC) is a grid-based multi-agent game on MettaGrid. Two teams ("cogs" and "clips") compete on an NxN grid (88x88, 100x100, 150x150, etc.) over 10,000 ticks.

Objective: capture and hold junctions (territory control nodes). Reward per tick = `junctions_held / max_steps`.

## Teams

- **Cogs** — player-controlled team, 1+ cog agents
- **Clips** — automated opponents that expand territory at a configurable rate

## Resources

Four resource types: **carbon**, **oxygen**, **germanium**, **silicon**.

Gathered at **extractors** and deposited at **hubs**. Resources fund gear acquisition and heart production.

## Roles (Gear)

Acquired at gear stations by spending hub resources. One role at a time.

| Role | Ability | Key Stats |
|------|---------|-----------|
| **Miner** | 10x resource extraction | +40 cargo capacity |
| **Aligner** | Capture neutral junctions (costs 1 heart) | — |
| **Scrambler** | Neutralize enemy junctions (costs 1 heart) | +200 HP |
| **Scout** | Mobile recon | +100 energy, +400 HP |

## Hearts

Special items obtained from hubs. Required for territory operations:
- Aligners spend 1 heart to capture a neutral junction
- Scramblers spend 1 heart to scramble an enemy junction
- 10-tick cooldown after using a heart before getting another

## Territory & Area-of-Effect

Hubs and junctions project AOE (default radius 10 cells):
- **Friendly territory**: full HP and energy restoration
- **Hostile territory**: -1 HP per tick, energy drain

## Entities

| Type | Description |
|------|-------------|
| `hub` | Team base, deposit resources, get hearts |
| `extractor` | Resource mining node |
| `converter` | Processes resources |
| `altar` | Special structure |
| `generator` | Power source |
| `junction` | Territory control node (capturable) |
| `agent` | Player character (own or enemy) |

## Game Phases

| Phase | Tick Range | Focus |
|-------|-----------|-------|
| `OPENING` | 0–499 | Exploration and setup |
| `EARLY` | 500–2499 | Resource gathering ramp-up |
| `MID` | 2500–4999 | Territory control |
| `LATE` | 5000–7499 | Optimization and defense |
| `ENDGAME` | 7500+ | Final push |

## Actions

5 discrete actions: `noop`, `move_north`, `move_south`, `move_east`, `move_west`.

All interaction happens by moving INTO things — walk into an extractor to mine, into a hub to deposit, into a junction to capture.

## Scoring

Reward per tick = `junctions_held / max_steps`. Total reward is cumulative across all ticks.

## Clips Expansion

Clips automatically:
- Neutralize enemy junctions adjacent to Clips territory
- Capture neutral junctions adjacent to Clips territory

Creates constant territorial pressure requiring active defense.
