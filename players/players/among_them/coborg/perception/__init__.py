"""Pixel-first perception pipeline for the Among Them coborg agent.

See PLAN §5 and DESIGN.md for the per-module port plan. P1 lands the
modules incrementally: baked assets (S1.4) → frame + sprite_match (S2)
→ actors + tasks (S3) → geometry/ignore/interstitial/localize/ocr/voting
(S4) → runtime wiring (S5).
"""
