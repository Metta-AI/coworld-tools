#!/usr/bin/env python3
"""Asset pipeline audit tool for tribal_village.

Run this script to audit PNG assets in the data/ directory and identify:
- Unused assets that can be safely removed
- Missing assets that are referenced but don't exist
- Asset size statistics

Usage:
    python scripts/asset_audit.py [--remove-unused] [--verbose]
"""

import sys
import argparse

from cliff_assets import CLIFF_REQUIRED_KEYS
from script_paths import DATA_DIR

def get_used_asset_keys():
    """Return set of asset keys that are actually used by the game.

    Note: The game has fallback logic (e.g., oriented/archer.s is used if
    oriented/archer.e doesn't exist). This function returns the REQUIRED
    assets - those that must exist for the game to work properly.
    """
    used = set()

    # Core rendering sprites (always loaded)
    used.update([
        "floor", "grid", "selection", "frozen", "heart", "cave", "dungeon"
    ])

    # Terrain types (TerrainType enum -> toSnakeCase)
    # Note: Ramp terrain types return "" for sprite key, so no sprites needed
    used.update([
        "water", "shallow_water", "bridge", "fertile", "road",
        "grass", "dune", "sand", "snow", "mud"
    ])

    # Building sprites (from BuildingRegistry in registry.nim)
    used.update([
        "altar", "town_center", "house", "door", "clay_oven", "weaving_loom",
        "outpost", "guard_tower", "barrel", "mill", "granary", "lumber_camp",
        "quarry", "mining_camp", "barracks", "archery_range", "stable",
        "siege_workshop", "mangonel_workshop", "trebuchet_workshop",
        "blacksmith", "market", "dock", "monastery", "university",
        "castle", "wonder", "goblin_hive", "goblin_hut", "goblin_totem"
    ])

    # Thing sprites (from ThingCatalog in registry.nim)
    used.update([
        "tree", "wheat", "fish", "stone", "gold", "bush", "cactus",
        "stalagmite", "magma", "spawner", "corpse", "skeleton", "stump",
        "stubble", "lantern", "temple", "control_point",
        "goblet"  # Relic sprite
    ])
    used.update(CLIFF_REQUIRED_KEYS)

    # Item sprites (from ItemCatalog in registry.nim)
    used.update([
        "bar", "droplet", "bushel", "wood", "spear", "shield", "bread",
        "plant", "meat"
    ])

    # Craft recipe items (from items.nim) - these may not have sprites yet
    # used.update(["bucket", "box", "bin", "cabinet", "cage"])

    # UI sprites
    used.update([
        "ui/play", "ui/pause", "ui/stepForward", "ui/turtle",
        "ui/speed", "ui/rabbit"
    ])

    # Oriented unit sprites (from UnitClassSpriteKeys in renderer.nim)
    # The game falls back to .s variant if specific direction doesn't exist
    # So we only REQUIRE the .s variants; other directions are optional enhancements
    unit_bases = [
        "gatherer", "builder", "fighter", "man_at_arms", "archer", "scout",
        "knight", "monk", "battering_ram", "mangonel", "trebuchet_packed",
        "trebuchet_unpacked", "goblin", "boat", "trade_cog", "samurai",
        "longbowman", "cataphract", "woad_raider", "teutonic_knight",
        "huskarl", "mameluke", "janissary", "king", "cow", "bear", "wolf"
    ]
    # Only the .s fallback is required; other directions are nice-to-have
    for base in unit_bases:
        used.add(f"oriented/{base}.s")  # Required fallback

    # Wall sprites (all 16 combinations generated in renderer.nim)
    for i in range(16):
        suffix = ""
        if i & 8:
            suffix += "n"
        if i & 4:
            suffix += "w"
        if i & 2:
            suffix += "s"
        if i & 1:
            suffix += "e"
        used.add(f"oriented/wall.{suffix}" if suffix else "oriented/wall")
    used.add("oriented/wall.fill")

    # Tumor sprites (from renderer.nim drawThings(Tumor))
    for prefix in ["oriented/tumor", "oriented/tumor.expired"]:
        for d in ["n", "s", "e", "w"]:
            used.add(f"{prefix}.{d}")

    # Ramps (registry.nim TerrainThingCatalog)
    for direction in ["up", "down"]:
        for d in ["n", "s", "e", "w"]:
            used.add(f"oriented/ramp_{direction}_{d}")

    # Waterfalls (registry.nim ThingCatalog)
    for d in ["n", "e", "s", "w"]:
        used.add(f"waterfall_{d}")

    return used


def scan_data_directory():
    """Scan data directory and return dict of {asset_key: file_size}."""
    assets = {}
    for path in DATA_DIR.rglob("*.png"):
        # Skip df_view directory (optional DF tileset)
        if "df_view" in path.parts:
            continue
        key = path.relative_to(DATA_DIR).as_posix().removesuffix(".png")
        assets[key] = path.stat().st_size
    return assets


def get_optional_but_used_keys(actual_assets):
    """Return set of keys for optional sprite variants that exist on disk.

    The game has fallback logic: if oriented/unit.e doesn't exist, it uses
    oriented/unit.s. All existing direction variants are loaded and used,
    they're just not strictly required.
    """
    optional_used = set()

    # All existing oriented sprites are loaded and used
    unit_bases = [
        "gatherer", "builder", "fighter", "man_at_arms", "archer", "scout",
        "knight", "monk", "battering_ram", "mangonel", "trebuchet_packed",
        "trebuchet_unpacked", "goblin", "boat", "trade_cog", "samurai",
        "longbowman", "cataphract", "woad_raider", "teutonic_knight",
        "huskarl", "mameluke", "janissary", "king", "cow", "bear", "wolf"
    ]
    directions = ["n", "s", "e", "w", "ne", "nw", "se", "sw", "r"]
    for base in unit_bases:
        for d in directions:
            key = f"oriented/{base}.{d}"
            if key in actual_assets:
                optional_used.add(key)

    return optional_used


def main():
    parser = argparse.ArgumentParser(description="Audit tribal_village assets")
    parser.add_argument("--remove-unused", action="store_true",
                        help="Remove unused assets (use with caution)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output")
    args = parser.parse_args()

    # Get used and actual assets
    used_keys = get_used_asset_keys()
    actual_assets = scan_data_directory()

    # Add optional but existing sprite variants (they're loaded even if not required)
    optional_used = get_optional_but_used_keys(actual_assets)
    all_used_keys = used_keys | optional_used

    # Calculate statistics
    unused = {k: v for k, v in actual_assets.items() if k not in all_used_keys}
    missing = used_keys - set(actual_assets.keys())
    total_size = sum(actual_assets.values())
    unused_size = sum(unused.values())

    # Print report
    print("=" * 60)
    print("TRIBAL VILLAGE ASSET AUDIT")
    print("=" * 60)
    print()
    print(f"Total PNG files: {len(actual_assets)}")
    print(f"Total size: {total_size / 1024 / 1024:.2f} MB")
    print()
    print(f"Used assets: {len(actual_assets) - len(unused)}")
    print(f"  - Required: {len(used_keys & set(actual_assets.keys()))}")
    print(f"  - Optional variants: {len(optional_used)}")
    print(f"Unused assets: {len(unused)} ({unused_size / 1024:.1f} KB)")
    print(f"Missing required: {len(missing)}")
    print()

    if unused:
        print("Unused assets (safe to remove):")
        for key in sorted(unused.keys()):
            size_kb = unused[key] // 1024
            print(f"  - data/{key}.png ({size_kb}KB)")
        print()

    if missing and args.verbose:
        print("Missing assets (referenced but not found):")
        for key in sorted(missing):
            print(f"  - data/{key}.png")
        print()

    if args.remove_unused and unused:
        print("Removing unused assets...")
        removed_count = 0
        removed_size = 0
        for key in unused:
            path = DATA_DIR / f"{key}.png"
            if path.exists():
                path.unlink()
                removed_count += 1
                removed_size += unused[key]
                print(f"  Removed: {path}")
        print(f"\nRemoved {removed_count} files ({removed_size / 1024:.1f} KB)")

    # Exit with error if missing assets
    if missing:
        print("WARNING: Some referenced assets are missing!")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
