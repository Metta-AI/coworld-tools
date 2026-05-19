# Asset Size Audit

Date: 2026-02-26

## Summary
- Total images scanned: 688
- Root gameplay sprites (`data/*.png`, excluding atlas): 82
- Most common dimensions:
  - `200x200`: 628
  - `1024x1024`: 41
  - `478x1100`: 6
  - `32x32`: 5
  - `256x256`: 3
  - `478x2612`: 2
  - `8192x8192`: 1
  - `478x884`: 1

## Largest Files By Pixel Area
| Asset | Size | Pixels |
|---|---:|---:|
| `data/silky.atlas.png` | 8192x8192 | 67108864 |
| `data/tmp/asset_preview.png` | 478x2612 | 1248536 |
| `data/tmp/cliff_preview.png` | 478x2612 | 1248536 |
| `data/tmp/cliff_corner_in_ne.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_corner_out_ne.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_edge_ew.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_edge_ew_s.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_edge_ns.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_edge_ns_w.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_variants/seed1001/tmp/oriented/cliff_corner_in_nw.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_variants/seed1001/tmp/oriented/cliff_corner_out_se.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_variants/seed1002/tmp/oriented/cliff_corner_in_nw.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_variants/seed1002/tmp/oriented/cliff_corner_out_se.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_variants/seed1003/tmp/oriented/cliff_corner_in_nw.png` | 1024x1024 | 1048576 |
| `data/tmp/cliff_variants/seed1003/tmp/oriented/cliff_corner_out_se.png` | 1024x1024 | 1048576 |

## Root Gameplay Sprite Footprint Outliers
Sorted by alpha bounding-box coverage (`bbox_ratio`).

| Asset | Canvas | Alpha BBox | bbox_ratio | fill_ratio |
|---|---:|---:|---:|---:|
| `bridge.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `cave.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `dungeon.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `fertile.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `floor.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `goblin_hive.png` | 200x200 | 200x200 | 1.000 | 0.703 |
| `goblin_hut.png` | 200x200 | 200x200 | 1.000 | 0.685 |
| `goblin_totem.png` | 200x200 | 200x200 | 1.000 | 0.621 |
| `grid.png` | 200x200 | 200x200 | 1.000 | 0.078 |
| `heart.png` | 200x200 | 200x200 | 1.000 | 0.726 |
| `mud.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `plant.png` | 200x200 | 200x200 | 1.000 | 0.703 |
| `road.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `sand.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `snow.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `water.png` | 200x200 | 200x200 | 1.000 | 1.000 |
| `selection.png` | 200x200 | 200x199 | 0.995 | 0.181 |
| `shallow_water.png` | 256x256 | 255x254 | 0.988 | 0.988 |
| `frozen.png` | 200x200 | 197x200 | 0.985 | 0.800 |
| `archery_range.png` | 200x200 | 196x200 | 0.980 | 0.641 |
| `town_center.png` | 200x200 | 200x196 | 0.980 | 0.555 |
| `door.png` | 200x200 | 194x200 | 0.970 | 0.968 |
| `weaving_loom.png` | 200x200 | 194x200 | 0.970 | 0.464 |
| `castle.png` | 200x200 | 200x192 | 0.960 | 0.609 |
| `siege_workshop.png` | 200x200 | 200x192 | 0.960 | 0.506 |

## Resource Sprite Baseline
| Asset | Canvas | Alpha BBox | bbox_ratio | fill_ratio |
|---|---:|---:|---:|---:|
| `wheat.png` | 200x200 | 170x180 | 0.765 | 0.496 |
| `wood.png` | 200x200 | 200x155 | 0.775 | 0.452 |
| `stone.png` | 200x200 | 168x157 | 0.659 | 0.488 |
| `gold.png` | 200x200 | 200x176 | 0.880 | 0.647 |
| `fish.png` | 200x200 | 200x154 | 0.770 | 0.496 |
| `tree.png` | 200x200 | 143x200 | 0.715 | 0.372 |
| `stump.png` | 200x200 | 200x174 | 0.870 | 0.563 |
| `stubble.png` | 200x200 | 200x146 | 0.730 | 0.400 |
| `bush.png` | 200x200 | 144x124 | 0.446 | 0.336 |
| `cactus.png` | 200x200 | 170x158 | 0.671 | 0.440 |
| `stalagmite.png` | 200x200 | 172x191 | 0.821 | 0.382 |
