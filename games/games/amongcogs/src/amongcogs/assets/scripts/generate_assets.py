#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import os
import time
from pathlib import Path

from PIL import Image

from amongcogs.assets.scripts.asset_postprocess import postprocess_to_target, tmp_path_for
from amongcogs.assets.scripts.asset_prompt_rows import (
    FLIP_ORIENTATIONS,
    OrientedOutput,
    iter_oriented_rows,
    iter_rows,
    load_oriented_rows,
    load_prompts,
)
from amongcogs.assets.scripts.script_paths import METTASCOPE_AMONGUS_DATA_DIR, PROMPTS_DIR
from amongcogs.assets.scripts.sprite_transforms import apply_transform

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

DEFAULT_MODEL = "gemini-3-pro-image-preview"
ALLOWED_MODELS = {
    "gemini-2.5-flash-image",
    "publishers/google/models/gemini-2.5-flash-image",
    "gemini-3-pro-image-preview",
    "publishers/google/models/gemini-3-pro-image-preview",
}
MAX_SIZE_BY_PREFIX = {
    "terrain/": 256,
    "objects/": 64,
    "vibe/": 32,
}


def _load_genai():
    if genai is None or genai_types is None:
        raise ImportError("generate_assets.py requires the Google GenAI SDK: pip install google-genai")
    return genai, genai_types


def make_client(project: str | None, location: str | None):
    genai, _ = _load_genai()
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


def build_config(seed: int):
    _, types = _load_genai()
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
    client,
    model: str,
    prompt: str,
    seed: int,
    *,
    max_retries: int = 0,
    retry_delay: float = 5.0,
) -> Image.Image:
    config = build_config(seed)
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            image_bytes = extract_inline_image(response)
            return Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except Exception as exc:  # pragma: no cover - depends on external API behavior
            if attempt >= max_retries or not _is_retryable_generation_error(exc):
                raise
            delay_s = retry_delay * (2**attempt)
            print(f"[retry] generate_image failed ({exc}); sleeping {delay_s:.1f}s")
            time.sleep(delay_s)


def generate_oriented_image(
    client,
    model: str,
    prompt: str,
    seed: int,
    reference_path: Path,
    *,
    max_retries: int = 0,
    retry_delay: float = 5.0,
) -> Image.Image:
    _, types = _load_genai()
    config = build_config(seed)
    reference_bytes = reference_path.read_bytes()
    parts = [
        types.Part.from_bytes(data=reference_bytes, mime_type="image/png"),
        types.Part.from_text(text=prompt),
    ]
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(model=model, contents=parts, config=config)
            image_bytes = extract_inline_image(response)
            return Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        except Exception as exc:  # pragma: no cover - depends on external API behavior
            if attempt >= max_retries or not _is_retryable_generation_error(exc):
                raise
            delay_s = retry_delay * (2**attempt)
            print(f"[retry] generate_oriented_image failed ({exc}); sleeping {delay_s:.1f}s")
            time.sleep(delay_s)


def _is_retryable_generation_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in ("resource_exhausted", "429", "quota", "rate limit"))


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
    return output.orientation_set in {"unit"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Among Us image assets from TSV prompts.")
    parser.add_argument("--prompts", default=(PROMPTS_DIR / "assets.tsv").as_posix())
    parser.add_argument("--out-dir", default=METTASCOPE_AMONGUS_DATA_DIR.as_posix())
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Gemini image model (global endpoint only).",
    )
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    parser.add_argument("--location", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"))
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--size", type=int, default=200, help="Output square size.")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retries for transient/quota generation failures (per asset).",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=8.0,
        help="Base retry delay in seconds (exponential backoff).",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip generation if target image already exists (useful for resume).",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep processing remaining assets if one generation fails.",
    )
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
    return parser.parse_args()


def _parse_only(raw_only: str) -> set[str] | None:
    parsed = {p.strip() for p in raw_only.split(",") if p.strip()}
    return parsed or None


def _target_path(name: str, out_dir: Path) -> Path:
    target = Path(name)
    if not target.is_absolute():
        target = out_dir / target
    return target


def _target_size(name: str, requested_size: int) -> int:
    if requested_size <= 0:
        return requested_size
    for prefix, max_size in MAX_SIZE_BY_PREFIX.items():
        if name.startswith(prefix):
            return min(requested_size, max_size)
    return requested_size


def _maybe_postprocess_only(
    *,
    target: Path,
    raw_target: Path,
    size: int,
    tol: int,
    purple_to_white: bool,
    purple_bg: bool,
) -> bool:
    source = raw_target if raw_target.exists() else target
    print(f"[postprocess] {target}")
    if not source.exists():
        print(f"[skip] missing {source}")
        return True
    postprocess_to_target(source, target, size, tol, purple_to_white, purple_bg)
    return True


def _save_generated_image(
    *,
    img: Image.Image,
    target: Path,
    raw_target: Path,
    size: int,
    tol: int,
    purple_to_white: bool,
    purple_bg: bool,
    do_postprocess: bool,
) -> None:
    if do_postprocess:
        raw_target.parent.mkdir(parents=True, exist_ok=True)
        img.save(raw_target)
        postprocess_to_target(raw_target, target, size, tol, purple_to_white, purple_bg)
        return
    if size and img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    img.save(target)


def _generate_oriented_non_flip(
    *,
    outputs: list[OrientedOutput],
    args: argparse.Namespace,
    out_dir: Path,
    tmp_dir: Path,
    client,
) -> None:
    for idx, output in enumerate(outputs):
        if output.dir_key == args.reference_dir and not args.include_reference and not args.postprocess_only:
            continue

        target = _target_path(output.filename, out_dir)
        raw_target = tmp_path_for(target, out_dir, tmp_dir)

        reference = _target_path(output.reference_filename, out_dir)
        raw_reference = tmp_path_for(reference, out_dir, tmp_dir)
        if raw_reference.exists():
            reference = raw_reference

        if args.dry_run:
            print(f"[dry-run] {target} <- {output.prompt[:80]}... (ref {reference})")
            continue

        use_purple = oriented_uses_purple_bg(output)
        use_purple_bg = use_purple or args.postprocess_purple_bg
        size = _target_size(output.filename, args.size)
        if args.postprocess_only:
            _maybe_postprocess_only(
                target=target,
                raw_target=raw_target,
                size=size,
                tol=args.postprocess_tol,
                purple_to_white=args.postprocess_purple_to_white,
                purple_bg=use_purple_bg,
            )
            continue

        if args.skip_existing and target.exists():
            print(f"[skip] existing {target}")
            continue

        if not reference.exists():
            raise SystemExit(f"Missing reference image: {reference}")
        if client is None:
            raise SystemExit("Client not initialized for image generation.")

        prompt = build_oriented_prompt(output.prompt)
        print(f"[generate] {target}")
        try:
            img = generate_oriented_image(
                client,
                args.model,
                prompt,
                args.seed + idx,
                reference,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
            )
        except Exception as exc:
            if args.continue_on_error:
                print(f"[error] {target}: {exc}")
                continue
            raise
        _save_generated_image(
            img=img,
            target=target,
            raw_target=raw_target,
            size=size,
            tol=args.postprocess_tol,
            purple_to_white=args.postprocess_purple_to_white,
            purple_bg=use_purple_bg,
            do_postprocess=args.postprocess or use_purple,
        )


def _generate_oriented_flip(
    *,
    outputs: list[OrientedOutput],
    args: argparse.Namespace,
    out_dir: Path,
    tmp_dir: Path,
) -> None:
    for output in outputs:
        target = _target_path(output.filename, out_dir)
        raw_target = tmp_path_for(target, out_dir, tmp_dir)

        flip_map = FLIP_ORIENTATIONS[output.orientation_set]
        source_dir = flip_map[output.dir_key]
        source_name = swap_orientation_token(output.filename, output.dir_key, source_dir)
        source = _target_path(source_name, out_dir)

        if args.dry_run:
            print(f"[dry-run] {target} <- flip {source}")
            continue

        use_purple = oriented_uses_purple_bg(output)
        use_purple_bg = use_purple or args.postprocess_purple_bg
        size = _target_size(output.filename, args.size)
        if args.postprocess_only:
            _maybe_postprocess_only(
                target=target,
                raw_target=raw_target,
                size=size,
                tol=args.postprocess_tol,
                purple_to_white=args.postprocess_purple_to_white,
                purple_bg=use_purple_bg,
            )
            continue

        raw_source = tmp_path_for(source, out_dir, tmp_dir)
        if raw_source.exists():
            source = raw_source
        if not source.exists():
            raise SystemExit(f"Missing flip source image: {source}")

        print(f"[transform] {target} <- flip_x {source}")
        with Image.open(source) as existing:
            img = existing.convert("RGBA")
        img = apply_transform(img, "flip_x")
        _save_generated_image(
            img=img,
            target=target,
            raw_target=raw_target,
            size=size,
            tol=args.postprocess_tol,
            purple_to_white=args.postprocess_purple_to_white,
            purple_bg=use_purple_bg,
            do_postprocess=args.postprocess or use_purple,
        )


def _run_oriented_generation(
    *,
    args: argparse.Namespace,
    prompt_path: Path,
    out_dir: Path,
    tmp_dir: Path,
    only: set[str] | None,
    client,
) -> None:
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

    _generate_oriented_non_flip(outputs=non_flip, args=args, out_dir=out_dir, tmp_dir=tmp_dir, client=client)
    _generate_oriented_flip(outputs=flip, args=args, out_dir=out_dir, tmp_dir=tmp_dir)


def _run_flat_generation(
    *,
    args: argparse.Namespace,
    prompt_path: Path,
    out_dir: Path,
    tmp_dir: Path,
    only: set[str] | None,
    client,
) -> None:
    rows = load_prompts(prompt_path)
    for idx, (filename, prompt) in enumerate(iter_rows(rows, only)):
        target = _target_path(filename, out_dir)
        raw_target = tmp_path_for(target, out_dir, tmp_dir)
        size = _target_size(filename, args.size)

        if args.dry_run:
            print(f"[dry-run] {target} <- {prompt[:80]}...")
            continue

        if args.postprocess_only:
            _maybe_postprocess_only(
                target=target,
                raw_target=raw_target,
                size=size,
                tol=args.postprocess_tol,
                purple_to_white=args.postprocess_purple_to_white,
                purple_bg=args.postprocess_purple_bg,
            )
            continue

        if args.skip_existing and target.exists():
            print(f"[skip] existing {target}")
            continue

        if client is None:
            raise SystemExit("Client not initialized for image generation.")

        print(f"[generate] {target}")
        try:
            img = generate_image(
                client,
                args.model,
                prompt,
                args.seed + idx,
                max_retries=args.max_retries,
                retry_delay=args.retry_delay,
            )
        except Exception as exc:
            if args.continue_on_error:
                print(f"[error] {target}: {exc}")
                continue
            raise
        _save_generated_image(
            img=img,
            target=target,
            raw_target=raw_target,
            size=size,
            tol=args.postprocess_tol,
            purple_to_white=args.postprocess_purple_to_white,
            purple_bg=args.postprocess_purple_bg,
            do_postprocess=args.postprocess,
        )


def _build_client(args: argparse.Namespace):
    if args.dry_run or args.postprocess_only:
        return None
    if args.location != "global":
        raise SystemExit("Only the global endpoint is supported for image generation.")
    if args.model not in ALLOWED_MODELS:
        raise SystemExit("Only supported Gemini image models are allowed.")
    return make_client(args.project, args.location)


def main() -> None:
    args = _parse_args()

    prompt_path = Path(args.prompts)
    only = _parse_only(args.only)
    client = _build_client(args)

    out_dir = Path(args.out_dir)
    tmp_dir = out_dir / "tmp"

    if args.oriented:
        _run_oriented_generation(
            args=args,
            prompt_path=prompt_path,
            out_dir=out_dir,
            tmp_dir=tmp_dir,
            only=only,
            client=client,
        )
        return

    _run_flat_generation(
        args=args,
        prompt_path=prompt_path,
        out_dir=out_dir,
        tmp_dir=tmp_dir,
        only=only,
        client=client,
    )


if __name__ == "__main__":
    main()
