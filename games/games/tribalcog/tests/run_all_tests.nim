## Combined test runner: single compilation for all unittest suites.
## Saves ~45s vs compiling each test separately.
## Run with: nim r --path:src tests/run_all_tests.nim

# Union of all imports needed by included test files
import std/[unittest, os, json, strutils, strformat, sets, times, monotimes, math]
import test_common
import balance_scorecard
import terrain
import renderer_core

# Include test suites — each has unique constant names to avoid conflicts.
# Suite blocks run at include time via unittest.
include "test_balance_scorecard"
include "test_map_determinism"
include "test_river_fill"
include "test_trading_hub"
include "test_score_tracking"
include "test_observations"
include "test_colors"
include "test_gui_assets"
include "test_renderer"
include "test_envconfig"
