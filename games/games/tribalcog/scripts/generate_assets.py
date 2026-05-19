#!/usr/bin/env python
from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    raise ImportError(
        "generate_assets.py requires the Google GenAI SDK: pip install google-genai"
    )
from PIL import Image

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
from script_paths import DATA_DIR
from sprite_transforms import apply_transform

# Setup notes:
# - Option A (API key): export GOOGLE_API_KEY=...
# - Option B (gcloud ADC): install gcloud and run
#   `gcloud auth application-default login`, then set the project via
#   `gcloud config set project <id>` or pass `--project <id>` (location must be "global").


def make_client(project: str | None, location: str | None) -> genai.Client:
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


def build_config(seed: int) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(output_mime_type="image/png", aspect_ratio="1:1"),
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
    client: genai.Client,
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


def generate_oriented_image(
    client: genai.Client,
    model: str,
    prompt: str,
    seed: int,
    size: int,
    reference_path: Path,
) -> Image.Image:
    config = build_config(seed)
    reference_bytes = reference_path.read_bytes()
    parts = [
        types.Part.from_bytes(data=reference_bytes, mime_type="image/png"),
        types.Part.from_text(text=prompt),
    ]
    response = client.models.generate_content(model=model, contents=parts, config=config)
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
        "Keep lighting consistent and preserve the background described in the prompt. "
        + prompt
    )


def oriented_uses_purple_bg(output: OrientedOutput) -> bool:
    return output.orientation_set in {"unit", "edge"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate image assets from TSV prompts.")
    parser.add_argument("--prompts", default=(DATA_DIR / "prompts" / "assets.tsv").as_posix())
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
    args = parser.parse_args()

    prompt_path = Path(args.prompts)
    only = {p.strip() for p in args.only.split(",") if p.strip()} or None

    client = None
    if not args.dry_run and not args.postprocess_only:
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
            if (
                output.dir_key == args.reference_dir
                and not args.include_reference
                and not args.postprocess_only
            ):
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
            img = generate_oriented_image(
                client, args.model, prompt, args.seed + idx, args.size, reference
            )
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
                    img = img.resize((args.size, args.size), Image.LANCZOS)
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
                    img = img.resize((args.size, args.size), Image.LANCZOS)
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
            if client is None:
                raise SystemExit("Client not initialized for image generation.")
            img = generate_image(client, args.model, prompt, args.seed + idx, args.size)
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
                    img = img.resize((args.size, args.size), Image.LANCZOS)
                target.parent.mkdir(parents=True, exist_ok=True)
                img.save(target)
                maybe_derive_cliff_variants(target, out_dir)


if __name__ == "__main__":
    main()
