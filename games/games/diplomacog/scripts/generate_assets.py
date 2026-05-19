#!/usr/bin/env python
from __future__ import annotations

import argparse
import colorsys
import importlib
import io
import math
import os
import random
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from asset_postprocess import postprocess_to_target, tmp_path_for
from asset_prompt_rows import (
    FLIP_ORIENTATIONS,
    OrientedOutput,
    iter_oriented_rows,
    iter_rows,
    load_oriented_rows,
    load_prompts,
)
from cliff_assets import maybe_derive_cliff_variants
from PIL import Image, ImageDraw, ImageFilter
from script_paths import DATA_DIR
from sprite_transforms import apply_transform

RESAMPLE_LANCZOS = Image.Resampling.LANCZOS

# Setup notes:
# - Option A (API key): export GOOGLE_API_KEY=...
# - Option B (gcloud ADC): install gcloud and run
#   `gcloud auth application-default login`, then set the project via
#   `gcloud config set project <id>` or pass `--project <id>` (location must be "global").


def _load_genai_sdk() -> tuple[Any, Any]:
    try:
        genai = importlib.import_module("google.genai")
        types = importlib.import_module("google.genai.types")
    except ImportError as exc:
        raise ImportError("generate_assets.py requires the Google GenAI SDK: pip install google-genai") from exc
    return genai, types


def make_client(project: str | None, location: str | None) -> Any:
    genai, _types = _load_genai_sdk()
    api_key = os.environ.get("GOOGLE_API_KEY")
    if api_key:
        return genai.Client(api_key=api_key)
    return genai.Client(vertexai=True, project=project, location=location)


def extract_inline_image(response) -> bytes:
    if not response.candidates:
        raise RuntimeError("No candidates returned from API.")
    for part in response.candidates[0].content.parts:
        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            return inline.data
    raise RuntimeError("No inline image data found in response.")


DEFAULT_MODEL = "gemini-3-pro-image-preview"
ALLOWED_MODELS = {
    "gemini-2.5-flash-image",
    "publishers/google/models/gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
    "publishers/google/models/gemini-3-pro-image-preview",
}


def build_config(seed: int) -> Any:
    _genai, types = _load_genai_sdk()
    return types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="1:1"),
        seed=seed,
        safety_settings=[
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_ONLY_HIGH,
            ),
        ],
    )


def generate_image(
    client: Any,
    model: str,
    prompt: str,
    seed: int,
    size: int,
) -> Image.Image:
    config = build_config(seed)
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    image_bytes = extract_inline_image(response)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    return img


def _seed_from_key(seed: int, key: str) -> int:
    digest = sha256(key.encode("utf-8")).digest()
    return (seed + int.from_bytes(digest[:8], "big")) % (2**32)


def _palette_for_key(lower: str) -> dict[str, tuple[int, int, int] | tuple[tuple[int, int, int], ...]]:
    neutral = {
        "primary": (214, 198, 150),
        "secondary": (120, 138, 147),
        "accent": (243, 236, 217),
        "dark": (69, 77, 89),
        "fills": ((214, 198, 150), (188, 173, 136), (167, 183, 187), (128, 147, 165)),
    }
    if "country_a" in lower:
        return {
            "primary": (62, 182, 190),
            "secondary": (110, 208, 182),
            "accent": (223, 245, 238),
            "dark": (31, 88, 103),
            "fills": ((62, 182, 190), (110, 208, 182), (124, 170, 210), (226, 245, 239)),
        }
    if "country_b" in lower:
        return {
            "primary": (214, 166, 66),
            "secondary": (237, 204, 103),
            "accent": (247, 241, 214),
            "dark": (115, 83, 34),
            "fills": ((214, 166, 66), (237, 204, 103), (204, 138, 76), (247, 241, 214)),
        }
    if "country_c" in lower:
        return {
            "primary": (196, 82, 88),
            "secondary": (225, 130, 120),
            "accent": (247, 225, 215),
            "dark": (108, 39, 49),
            "fills": ((196, 82, 88), (225, 130, 120), (172, 114, 146), (247, 225, 215)),
        }
    if "reactor" in lower:
        return {
            "primary": (100, 171, 214),
            "secondary": (151, 219, 232),
            "accent": (236, 248, 252),
            "dark": (35, 60, 95),
            "fills": ((100, 171, 214), (151, 219, 232), (219, 236, 240), (68, 98, 144)),
        }
    if "comms" in lower:
        return {
            "primary": (97, 177, 150),
            "secondary": (144, 223, 199),
            "accent": (232, 249, 241),
            "dark": (42, 86, 78),
            "fills": ((97, 177, 150), (144, 223, 199), (213, 239, 231), (71, 122, 110)),
        }
    if "sabotage" in lower:
        return {
            "primary": (144, 92, 173),
            "secondary": (216, 109, 120),
            "accent": (250, 234, 239),
            "dark": (74, 35, 91),
            "fills": ((144, 92, 173), (216, 109, 120), (110, 72, 147), (250, 234, 239)),
        }
    if "border" in lower:
        return {
            "primary": (242, 232, 206),
            "secondary": (196, 188, 170),
            "accent": (255, 250, 240),
            "dark": (84, 74, 61),
            "fills": ((242, 232, 206), (222, 210, 183), (196, 188, 170), (150, 141, 125)),
        }
    return neutral


def _palette_color(
    palette: Mapping[str, tuple[int, int, int] | tuple[tuple[int, int, int], ...]],
    key: str,
) -> tuple[int, int, int]:
    return cast(tuple[int, int, int], palette[key])


def _palette_fills(
    palette: Mapping[str, tuple[int, int, int] | tuple[tuple[int, int, int], ...]],
) -> tuple[tuple[int, int, int], ...]:
    return cast(tuple[tuple[int, int, int], ...], palette["fills"])


def _draw_blob(draw: ImageDraw.ImageDraw, rng: random.Random, center: tuple[int, int], radius: int, color) -> None:
    cx, cy = center
    points: list[tuple[int, int]] = []
    verts = rng.randint(9, 15)
    for idx in range(verts):
        angle = (idx / verts) * math.tau
        wobble = radius * rng.uniform(0.68, 1.18)
        x = int(cx + math.cos(angle) * wobble)
        y = int(cy + math.sin(angle) * wobble)
        points.append((x, y))
    draw.polygon(points, fill=color)


def _draw_radial_stamp(
    draw: ImageDraw.ImageDraw,
    size: int,
    palette: Mapping[str, tuple[int, int, int] | tuple[tuple[int, int, int], ...]],
    lower: str,
) -> None:
    center = size // 2
    outer = int(size * 0.34)
    inner = int(size * 0.24)
    core = int(size * 0.16)
    dark = _palette_color(palette, "dark")
    primary = _palette_color(palette, "primary")
    secondary = _palette_color(palette, "secondary")
    accent = _palette_color(palette, "accent")
    draw.ellipse(
        (center - outer, center - outer, center + outer, center + outer),
        fill=(*dark, 180),
    )
    draw.ellipse(
        (center - outer + 12, center - outer + 12, center + outer - 12, center + outer - 12),
        fill=(*primary, 236),
    )
    draw.ellipse(
        (center - inner, center - inner, center + inner, center + inner),
        fill=(*accent, 244),
    )
    for idx in range(6):
        angle = (idx / 6.0) * math.tau
        x = int(center + math.cos(angle) * (outer * 0.82))
        y = int(center + math.sin(angle) * (outer * 0.82))
        r = max(7, size // 34)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*secondary, 216))

    if "reactor" in lower:
        draw.polygon(
            [
                (center, int(size * 0.28)),
                (int(size * 0.7), center),
                (center, int(size * 0.72)),
                (int(size * 0.3), center),
            ],
            fill=(*secondary, 248),
        )
        draw.ellipse((center - core, center - core, center + core, center + core), fill=(*accent, 255))
    elif "comms" in lower:
        for width in (core + 10, core + 42, core + 74):
            draw.arc(
                (center - width, center - width, center + width, center + width),
                start=210,
                end=330,
                fill=(*dark, 255),
                width=max(5, size // 72),
            )
        mast_w = max(10, size // 46)
        draw.rounded_rectangle(
            (center - mast_w, center - core, center + mast_w, center + core + 36),
            radius=6,
            fill=(*secondary, 248),
        )
    elif "sabotage" in lower:
        width = max(10, size // 32)
        draw.line(
            (int(size * 0.34), int(size * 0.34), int(size * 0.66), int(size * 0.66)),
            fill=(*secondary, 248),
            width=width,
        )
        draw.line(
            (int(size * 0.66), int(size * 0.34), int(size * 0.34), int(size * 0.66)),
            fill=(*accent, 248),
            width=width,
        )
    elif "supply_center" in lower:
        points = []
        outer_r = int(size * 0.15)
        inner_r = int(size * 0.07)
        for idx in range(10):
            angle = -math.pi / 2 + idx * math.pi / 5
            radius = outer_r if idx % 2 == 0 else inner_r
            points.append((int(center + math.cos(angle) * radius), int(center + math.sin(angle) * radius)))
        draw.polygon(points, fill=(*secondary, 252))
    elif "_hub" in lower:
        hub = int(size * 0.22)
        draw.rounded_rectangle(
            (center - hub, center - hub, center + hub, center + hub),
            radius=max(16, size // 18),
            fill=(*secondary, 248),
        )
        draw.rounded_rectangle(
            (center - hub + 18, center - hub + 18, center + hub - 18, center + hub - 18),
            radius=max(12, size // 24),
            fill=(*accent, 244),
        )
    elif "country_" in lower:
        draw.polygon(
            [
                (center, int(size * 0.28)),
                (int(size * 0.68), int(size * 0.38)),
                (int(size * 0.62), int(size * 0.66)),
                (center, int(size * 0.76)),
                (int(size * 0.38), int(size * 0.66)),
                (int(size * 0.32), int(size * 0.38)),
            ],
            fill=(*secondary, 250),
        )
        draw.line(
            (center, int(size * 0.34), center, int(size * 0.72)),
            fill=(*dark, 255),
            width=max(5, size // 80),
        )
    else:
        scroll_h = int(size * 0.11)
        draw.rounded_rectangle(
            (int(size * 0.32), center - scroll_h, int(size * 0.68), center + scroll_h),
            radius=max(12, size // 22),
            fill=(*secondary, 246),
        )
        draw.arc(
            (int(size * 0.26), center - scroll_h, int(size * 0.38), center + scroll_h),
            start=90,
            end=270,
            fill=(*dark, 255),
            width=max(4, size // 88),
        )
        draw.arc(
            (int(size * 0.62), center - scroll_h, int(size * 0.74), center + scroll_h),
            start=-90,
            end=90,
            fill=(*dark, 255),
            width=max(4, size // 88),
        )


def generate_placeholder_image(key: str, prompt: str, seed: int, size: int) -> Image.Image:
    # Deterministic local fallback used when remote generation is unavailable/quota-limited.
    rng_seed = _seed_from_key(seed, f"{key}|{prompt}")
    rng = random.Random(rng_seed)
    lower = key.lower()
    palette = _palette_for_key(lower)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    def hsv_to_rgb(h: int, s: int, v: int) -> tuple[int, int, int]:
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 100.0, v / 100.0)
        return int(r * 255), int(g * 255), int(b * 255)

    if lower.startswith("diplomacy/") and "splat." in lower:
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer, "RGBA")
        fills = _palette_fills(palette)
        dark = _palette_color(palette, "dark")
        accent = _palette_color(palette, "accent")
        for _ in range(32):
            radius = rng.randint(max(22, size // 10), max(48, size // 4))
            cx = rng.randint(radius // 2, size - radius // 2)
            cy = rng.randint(radius // 2, size - radius // 2)
            fill = fills[rng.randrange(len(fills))]
            alpha = rng.randint(72, 156)
            _draw_blob(layer_draw, rng, (cx, cy), radius, (*fill, alpha))
        if "border" in lower:
            for _ in range(4):
                x0 = rng.randint(size // 8, size // 3)
                y0 = rng.randint(size // 8, size - size // 8)
                x1 = rng.randint(size * 2 // 3, size - size // 8)
                y1 = rng.randint(size // 8, size - size // 8)
                layer_draw.line(
                    (x0, y0, x1, y1),
                    fill=(*dark, 210),
                    width=max(10, size // 32),
                )
                layer_draw.line(
                    (x0, y0, x1, y1),
                    fill=(*accent, 148),
                    width=max(4, size // 72),
                )
        return layer.filter(ImageFilter.GaussianBlur(radius=max(2, size // 70)))

    if lower.startswith("diplomacy/"):
        shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow, "RGBA")
        shadow_draw.ellipse(
            (int(size * 0.22), int(size * 0.22), int(size * 0.78), int(size * 0.78)),
            fill=(0, 0, 0, 80),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(4, size // 60)))
        img = Image.alpha_composite(img, shadow)
        draw = ImageDraw.Draw(img, "RGBA")
        _draw_radial_stamp(draw, size, palette, lower)
        return img

    base_hue = rng.randint(0, 359)
    if "splat." in key:
        for _ in range(240):
            x = rng.randint(0, size - 1)
            y = rng.randint(0, size - 1)
            radius = rng.randint(max(2, size // 90), max(8, size // 18))
            hue = (base_hue + rng.randint(-35, 35)) % 360
            sat = rng.randint(25, 65)
            val = rng.randint(45, 90)
            alpha = rng.randint(50, 130)
            color = (*hsv_to_rgb(hue, sat, val), alpha)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        return img.filter(ImageFilter.GaussianBlur(radius=max(1, size // 120)))

    center = size // 2
    ring_outer = int(size * 0.34)
    ring_inner = int(size * 0.24)
    color_a = (*hsv_to_rgb(base_hue, 55, 82), 236)
    color_b = (*hsv_to_rgb((base_hue + 48) % 360, 60, 72), 216)
    color_c = (*hsv_to_rgb((base_hue + 180) % 360, 30, 92), 208)

    draw.ellipse((center - ring_outer, center - ring_outer, center + ring_outer, center + ring_outer), fill=color_a)
    draw.ellipse((center - ring_inner, center - ring_inner, center + ring_inner, center + ring_inner), fill=color_c)
    for i in range(6):
        angle = (i / 6.0) * 360.0
        x = int(center + math.cos(math.radians(angle)) * ring_outer * 0.78)
        y = int(center + math.sin(math.radians(angle)) * ring_outer * 0.78)
        r = max(6, size // 30)
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color_b)

    if "reactor" in lower:
        draw.polygon(
            [
                (center, int(size * 0.26)),
                (int(size * 0.72), center),
                (center, int(size * 0.74)),
                (int(size * 0.28), center),
            ],
            fill=color_c,
        )
    elif "comms" in lower:
        for width in (4, 8, 12):
            draw.arc(
                (center - width * 8, center - width * 8, center + width * 8, center + width * 8),
                start=210,
                end=330,
                fill=color_c,
                width=max(2, size // 90),
            )
    elif "sabotage" in lower:
        draw.line(
            (int(size * 0.32), int(size * 0.32), int(size * 0.68), int(size * 0.68)),
            fill=color_c,
            width=max(8, size // 30),
        )
        draw.line(
            (int(size * 0.68), int(size * 0.32), int(size * 0.32), int(size * 0.68)),
            fill=color_c,
            width=max(8, size // 30),
        )
    else:
        draw.rounded_rectangle(
            (int(size * 0.34), int(size * 0.34), int(size * 0.66), int(size * 0.66)),
            radius=max(6, size // 18),
            fill=color_c,
        )
    return img


def generate_oriented_image(
    client: Any,
    model: str,
    prompt: str,
    seed: int,
    size: int,
    reference_path: Path,
) -> Image.Image:
    _genai, types = _load_genai_sdk()
    config = build_config(seed)
    reference_bytes = reference_path.read_bytes()
    parts = [
        types.Part.from_bytes(data=reference_bytes, mime_type="image/png"),
        types.Part.from_text(text=prompt),
    ]
    response = client.models.generate_content(model=model, contents=cast(Any, parts), config=config)
    image_bytes = extract_inline_image(response)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    return img


def swap_orientation_token(filename: str, old: str, new: str) -> str:
    replacements = [
        (f".{old}.", f".{new}."),
        (f"_{old}.", f"_{new}."),
        (f"_{old}_", f"_{new}_"),
        (f"/{old}.", f"/{new}."),
    ]
    for src, dst in replacements:
        if src in filename:
            return filename.replace(src, dst)
    return filename.replace(old, new, 1)


def build_oriented_prompt(prompt: str) -> str:
    return (
        "Use the provided reference image as the same unit. "
        "Match palette, silhouette, proportions, and line weight. "
        "Keep lighting consistent and preserve the background described in the prompt. " + prompt
    )


def oriented_uses_purple_bg(output: OrientedOutput) -> bool:
    return output.orientation_set in {"unit", "edge"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate image assets from TSV prompts.")
    parser.add_argument("--prompts", default=(DATA_DIR / "prompts" / "diplomacy_assets.tsv").as_posix())
    parser.add_argument("--out-dir", default=DATA_DIR.as_posix())
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Gemini image model (global endpoint only).",
    )
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--size", type=int, default=200, help="Output square size.")
    parser.add_argument("--postprocess", action="store_true")
    parser.add_argument("--postprocess-only", action="store_true")
    parser.add_argument("--postprocess-tol", type=int, default=35, help="Background keying tolerance.")
    parser.add_argument(
        "--postprocess-purple-to-white",
        action="store_true",
        help="Replace bright purple pixels with white for team tinting.",
    )
    parser.add_argument(
        "--postprocess-purple-bg",
        action="store_true",
        help="Key out solid royal purple backgrounds before other postprocessing.",
    )
    parser.add_argument(
        "--oriented",
        action="store_true",
        help="Generate oriented sprites using reference images (rows with {dir}).",
    )
    parser.add_argument(
        "--reference-dir",
        default="s",
        help="Orientation to use as the reference image (default: s).",
    )
    parser.add_argument(
        "--include-reference",
        dest="include_reference",
        action="store_true",
        default=True,
        help="Generate the reference orientation too (enabled by default).",
    )
    parser.add_argument(
        "--no-include-reference",
        dest="include_reference",
        action="store_false",
        help="Skip the reference orientation.",
    )
    parser.add_argument("--only", default="", help="Comma-separated filenames to generate.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--placeholder",
        action="store_true",
        help="Generate deterministic local placeholder assets without calling Gemini.",
    )
    parser.add_argument(
        "--fallback-placeholder",
        action="store_true",
        help="If Gemini generation fails for an asset, generate a deterministic placeholder for that asset instead.",
    )
    args = parser.parse_args()

    prompt_path = Path(args.prompts)
    only = {p.strip() for p in args.only.split(",") if p.strip()} or None

    client = None
    if not args.dry_run and not args.postprocess_only and not args.placeholder:
        if args.location != "global":
            raise SystemExit("Only the global endpoint is supported for image generation.")
        if args.model not in ALLOWED_MODELS:
            raise SystemExit("Only supported Gemini image models are allowed.")
        client = make_client(args.project, args.location)
    out_dir = Path(args.out_dir)
    tmp_dir = out_dir / "tmp"

    if args.oriented:
        oriented_rows = load_oriented_rows(prompt_path)
        if not oriented_rows:
            raise SystemExit("No oriented rows found (filenames containing {dir}).")
        outputs = list(iter_oriented_rows(oriented_rows, args.reference_dir, only))
        non_flip: list[OrientedOutput] = []
        flip: list[OrientedOutput] = []
        for output in outputs:
            flip_map = FLIP_ORIENTATIONS.get(output.orientation_set, {})
            if output.dir_key in flip_map:
                flip.append(output)
            else:
                non_flip.append(output)

        for idx, output in enumerate(non_flip):
            if output.dir_key == args.reference_dir and not args.include_reference and not args.postprocess_only:
                continue
            target = Path(output.filename)
            if not target.is_absolute():
                target = out_dir / target
            raw_target = tmp_path_for(target, out_dir, tmp_dir)
            reference = Path(output.reference_filename)
            if not reference.is_absolute():
                reference = out_dir / reference
            raw_reference = tmp_path_for(reference, out_dir, tmp_dir)
            if raw_reference.exists():
                reference = raw_reference
            if args.dry_run:
                print(f"[dry-run] {target} <- {output.prompt[:80]}... (ref {reference})")
                continue
            if args.postprocess_only:
                source = raw_target if raw_target.exists() else target
                if not source.exists():
                    print(f"[skip] missing {source}")
                    continue
                postprocess_to_target(
                    source,
                    target,
                    args.size,
                    args.postprocess_tol,
                    args.postprocess_purple_to_white,
                    oriented_uses_purple_bg(output) or args.postprocess_purple_bg,
                )
                continue
            if not reference.exists():
                raise SystemExit(f"Missing reference image: {reference}")
            if client is None:
                raise SystemExit("Client not initialized for image generation.")
            prompt = build_oriented_prompt(output.prompt)
            img = generate_oriented_image(client, args.model, prompt, args.seed + idx, args.size, reference)
            use_purple = oriented_uses_purple_bg(output)
            do_postprocess = args.postprocess or use_purple
            if do_postprocess:
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                img.save(raw_target)
                postprocess_to_target(
                    raw_target,
                    target,
                    args.size,
                    args.postprocess_tol,
                    args.postprocess_purple_to_white,
                    use_purple or args.postprocess_purple_bg,
                )
            else:
                if args.size and img.size != (args.size, args.size):
                    img = img.resize((args.size, args.size), RESAMPLE_LANCZOS)
                target.parent.mkdir(parents=True, exist_ok=True)
                img.save(target)

        for output in flip:
            target = Path(output.filename)
            if not target.is_absolute():
                target = out_dir / target
            raw_target = tmp_path_for(target, out_dir, tmp_dir)
            flip_map = FLIP_ORIENTATIONS.get(output.orientation_set, {})
            source_dir = flip_map[output.dir_key]
            source_name = swap_orientation_token(output.filename, output.dir_key, source_dir)
            source = Path(source_name)
            if not source.is_absolute():
                source = out_dir / source
            if args.dry_run:
                print(f"[dry-run] {target} <- flip {source}")
                continue
            if args.postprocess_only:
                source = raw_target if raw_target.exists() else target
                if not source.exists():
                    print(f"[skip] missing {source}")
                    continue
                postprocess_to_target(
                    source,
                    target,
                    args.size,
                    args.postprocess_tol,
                    args.postprocess_purple_to_white,
                    oriented_uses_purple_bg(output) or args.postprocess_purple_bg,
                )
                continue
            raw_source = tmp_path_for(source, out_dir, tmp_dir)
            if raw_source.exists():
                source = raw_source
            if not source.exists():
                raise SystemExit(f"Missing flip source image: {source}")
            with Image.open(source) as existing:
                img = existing.convert("RGBA")
            img = apply_transform(img, "flip_x")
            use_purple = oriented_uses_purple_bg(output)
            do_postprocess = args.postprocess or use_purple
            if do_postprocess:
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                img.save(raw_target)
                postprocess_to_target(
                    raw_target,
                    target,
                    args.size,
                    args.postprocess_tol,
                    args.postprocess_purple_to_white,
                    use_purple or args.postprocess_purple_bg,
                )
            else:
                if args.size and img.size != (args.size, args.size):
                    img = img.resize((args.size, args.size), RESAMPLE_LANCZOS)
                target.parent.mkdir(parents=True, exist_ok=True)
                img.save(target)
    else:
        rows = load_prompts(prompt_path)
        for idx, (filename, prompt) in enumerate(iter_rows(rows, only)):
            target = Path(filename)
            if not target.is_absolute():
                target = out_dir / target
            raw_target = tmp_path_for(target, out_dir, tmp_dir)
            if args.dry_run:
                print(f"[dry-run] {target} <- {prompt[:80]}...")
                continue
            if args.postprocess_only:
                source = raw_target if raw_target.exists() else target
                if not source.exists():
                    print(f"[skip] missing {source}")
                    continue
                postprocess_to_target(
                    source,
                    target,
                    args.size,
                    args.postprocess_tol,
                    args.postprocess_purple_to_white,
                    args.postprocess_purple_bg,
                )
                maybe_derive_cliff_variants(target, out_dir)
                continue
            if args.placeholder:
                img = generate_placeholder_image(filename, prompt, args.seed + idx, args.size)
            else:
                if client is None:
                    raise SystemExit("Client not initialized for image generation.")
                try:
                    img = generate_image(client, args.model, prompt, args.seed + idx, args.size)
                except Exception:
                    if not args.fallback_placeholder:
                        raise
                    img = generate_placeholder_image(filename, prompt, args.seed + idx, args.size)
            if args.postprocess:
                raw_target.parent.mkdir(parents=True, exist_ok=True)
                img.save(raw_target)
                postprocess_to_target(
                    raw_target,
                    target,
                    args.size,
                    args.postprocess_tol,
                    args.postprocess_purple_to_white,
                    args.postprocess_purple_bg,
                )
                maybe_derive_cliff_variants(target, out_dir)
            else:
                if args.size and img.size != (args.size, args.size):
                    img = img.resize((args.size, args.size), RESAMPLE_LANCZOS)
                target.parent.mkdir(parents=True, exist_ok=True)
                img.save(target)
                maybe_derive_cliff_variants(target, out_dir)


if __name__ == "__main__":
    main()
