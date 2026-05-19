#!/usr/bin/env python3
"""Generate and slice a sprite sheet from a markdown art spec."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "public" / "assets" / "cogshambo" / "sprite-sheets"
DEFAULT_MODEL = "rd-animation"
DEFAULT_STYLE = "four_angle_walking"
DEFAULT_SIZE = (48, 48)


@dataclass(frozen=True)
class SpriteSpec:
    name: str
    prompt: str
    category: str
    model: str
    style: str
    size: tuple[int, int]
    frame_size: tuple[int, int]
    columns: int | None
    rows: int | None
    seed: int | None
    output_dir: Path
    preview_scale: int
    variants: int
    append_defaults: bool


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            os.environ.setdefault(key, value)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip(".-_")
    return slug or "sprite"


def parse_size(value: Any, default: tuple[int, int] | None = None) -> tuple[int, int]:
    if value is None:
        if default is None:
            raise ValueError("missing size")
        return default
    match = re.fullmatch(r"(\d+)x(\d+)", str(value).strip().lower())
    if not match:
        raise ValueError(f"expected size as WxH, got {value!r}")
    return int(match.group(1)), int(match.group(2))


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"expected boolean, got {value!r}")


def parse_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    return int(str(value).strip())


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---", 4)
    if end == -1:
        return {}, text

    frontmatter = text[4:end].strip()
    body = text[end + len("\n---") :].lstrip("\r\n")
    data: dict[str, str] = {}
    for raw_line in frontmatter.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"frontmatter line must be 'key: value': {raw_line!r}")
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data, body


def markdown_section(body: str, heading: str) -> str | None:
    lines = body.splitlines()
    in_section = False
    captured: list[str] = []
    heading_re = re.compile(r"^#{1,6}\s+(.+?)\s*$")

    for line in lines:
        match = heading_re.match(line)
        if match:
            normalized = match.group(1).strip().lower()
            if in_section and normalized != heading.lower():
                break
            in_section = normalized == heading.lower()
            continue
        if in_section:
            captured.append(line)

    value = "\n".join(captured).strip()
    return value or None


def body_as_prompt(body: str) -> str:
    section_prompt = markdown_section(body, "prompt")
    if section_prompt:
        return section_prompt

    prompt_lines = []
    in_fence = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or line.startswith("#"):
            continue
        if line.startswith("<!--") and line.endswith("-->"):
            continue
        prompt_lines.append(raw_line)
    return "\n".join(prompt_lines).strip()


def default_prompt_suffix(spec: SpriteSpec) -> str:
    width, height = spec.frame_size
    if spec.model == "rd-animation":
        return (
            "Generate one complete sprite sheet in a single image. "
            f"Use transparent background, exact {width}x{height} frame slots, consistent character identity, "
            "same palette family, same silhouette family, readable face and key features, no scenery, no labels, "
            "no poster composition, crisp production pixel-art clusters for a browser game."
        )

    return (
        f"Generate each image as one transparent {width}x{height} sprite option. "
        "Use one centered solo character per image, consistent palette family, same silhouette family, "
        "readable face and key features, no scenery, no labels, no poster composition, no multi-view layout, "
        "no sprite sheet, clean anti-aliased edges, and no upscaled low-resolution pixelation."
    )


def load_spec(path: Path, output_dir_override: Path | None) -> SpriteSpec:
    meta, body = parse_frontmatter(path.read_text())
    name = slugify(meta.get("name") or path.stem)
    prompt = meta.get("prompt") or body_as_prompt(body)
    if not prompt:
        raise ValueError(f"{path} does not contain a prompt. Add body text or a '## Prompt' section.")

    size = parse_size(meta.get("size"), DEFAULT_SIZE)
    frame_width = parse_int(meta.get("frame_width"), size[0])
    frame_height = parse_int(meta.get("frame_height"), size[1])
    if frame_width is None or frame_height is None:
        raise ValueError("frame_width and frame_height are required")

    output_dir = output_dir_override
    if output_dir is None and meta.get("output_dir"):
        output_dir = Path(meta["output_dir"]).expanduser()
        if not output_dir.is_absolute():
            output_dir = REPO_ROOT / output_dir
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_ROOT / name

    return SpriteSpec(
        name=name,
        prompt=prompt,
        category=meta.get("category", "cogs"),
        model=meta.get("model", DEFAULT_MODEL),
        style=meta.get("style", DEFAULT_STYLE),
        size=size,
        frame_size=(frame_width, frame_height),
        columns=parse_int(meta.get("columns")),
        rows=parse_int(meta.get("rows")),
        seed=parse_int(meta.get("seed")),
        output_dir=output_dir,
        preview_scale=int(meta.get("preview_scale", "4")),
        variants=max(1, int(meta.get("variants", "1"))),
        append_defaults=parse_bool(meta.get("append_defaults"), True),
    )


def public_url(path: Path) -> str | None:
    try:
        return "/" + path.resolve().relative_to((REPO_ROOT / "public").resolve()).as_posix()
    except ValueError:
        return None


def manifest_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def run_generator(spec: SpriteSpec, dry_run: bool) -> tuple[Path | None, list[Path]]:
    load_dotenv(REPO_ROOT / ".env")
    prompt = spec.prompt
    if spec.append_defaults:
        prompt = f"{prompt}\n\n{default_prompt_suffix(spec)}"

    is_sheet = spec.model == "rd-animation"
    output_name = f"{spec.name}-sheet" if is_sheet else spec.name
    cmd = [
        sys.executable,
        str(REPO_ROOT / "tools" / "gen_sprite.py"),
        prompt,
        "--category",
        spec.category,
        "--model",
        spec.model,
        "--style",
        spec.style,
        "--size",
        f"{spec.size[0]}x{spec.size[1]}",
        "--name",
        output_name,
        "--output-dir",
        str(spec.output_dir),
    ]
    if not is_sheet and spec.variants > 1:
        cmd.extend(["--num", str(spec.variants)])
    if spec.seed is not None:
        cmd.extend(["--seed", str(spec.seed)])
    if dry_run:
        cmd.append("--dry-run")

    subprocess.run(cmd, cwd=REPO_ROOT, check=True)
    if is_sheet:
        return spec.output_dir / f"{output_name}.png", []

    if spec.variants == 1:
        frame_sources = [spec.output_dir / f"{output_name}.png"]
    else:
        frame_sources = [spec.output_dir / f"{output_name}_{index}.png" for index in range(1, spec.variants + 1)]

    missing = [path for path in frame_sources if not path.exists()]
    if missing and not dry_run:
        missing_names = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"generator did not write expected sprite option(s): {missing_names}")
    return None, frame_sources


def import_pillow() -> Any:
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required for slicing and previews. Run with:\n"
            "  uv run --with replicate --with pillow python tools/generate_sprite_sheet.py <spec.md>"
        ) from exc
    return Image, ImageDraw, ImageChops


def split_sheet(spec: SpriteSpec, sheet_path: Path) -> tuple[list[Path], Path, dict[str, Any]]:
    Image, ImageDraw, _ImageChops = import_pillow()
    image = Image.open(sheet_path).convert("RGBA")
    frame_width, frame_height = spec.frame_size

    if spec.columns is None:
        if image.width % frame_width != 0:
            raise ValueError(f"sheet width {image.width} is not divisible by frame_width {frame_width}")
        columns = image.width // frame_width
    else:
        columns = spec.columns
        expected_width = columns * frame_width
        if image.width < expected_width:
            raise ValueError(
                f"sheet width {image.width} is smaller than columns x frame_width ({columns} x {frame_width} = {expected_width})"
            )

    if spec.rows is None:
        if image.height % frame_height != 0:
            raise ValueError(f"sheet height {image.height} is not divisible by frame_height {frame_height}")
        rows = image.height // frame_height
    else:
        rows = spec.rows
        expected_height = rows * frame_height
        if image.height < expected_height:
            raise ValueError(
                f"sheet height {image.height} is smaller than rows x frame_height ({rows} x {frame_height} = {expected_height})"
            )

    frames_dir = spec.output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for row in range(rows):
        for column in range(columns):
            box = (
                column * frame_width,
                row * frame_height,
                (column + 1) * frame_width,
                (row + 1) * frame_height,
            )
            frame = remove_flat_background(Image, image.crop(box))
            frame_path = frames_dir / f"{spec.name}-{row * columns + column + 1:02d}.png"
            frame.save(frame_path)
            frame_paths.append(frame_path)

    preview_path = spec.output_dir / f"{spec.name}-preview.png"
    render_preview(Image, ImageDraw, frame_paths, frame_width, frame_height, columns, spec.preview_scale, preview_path)

    manifest = {
        "name": spec.name,
        "source_sheet": manifest_path(sheet_path),
        "source_sheet_url": public_url(sheet_path),
        "frame_width": frame_width,
        "frame_height": frame_height,
        "columns": columns,
        "rows": rows,
        "frame_count": len(frame_paths),
        "frames": [
            {
                "path": manifest_path(frame_path),
                "url": public_url(frame_path),
            }
            for frame_path in frame_paths
        ],
        "preview": manifest_path(preview_path),
        "preview_url": public_url(preview_path),
    }
    manifest_file = spec.output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")
    return frame_paths, preview_path, manifest


def build_frames_from_images(spec: SpriteSpec, source_paths: list[Path]) -> tuple[list[Path], Path, dict[str, Any]]:
    Image, ImageDraw, _ImageChops = import_pillow()
    frame_width, frame_height = spec.frame_size
    frames_dir = spec.output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []

    for index, source_path in enumerate(source_paths, start=1):
        frame = Image.open(source_path).convert("RGBA")
        if frame.size != spec.frame_size:
            frame = frame.resize((frame_width, frame_height), Image.Resampling.LANCZOS)
        frame = remove_flat_background(Image, frame)
        frame_path = frames_dir / f"{spec.name}-{index:02d}.png"
        frame.save(frame_path)
        frame_paths.append(frame_path)

    columns = spec.columns or min(len(frame_paths), 5) or 1
    preview_path = spec.output_dir / f"{spec.name}-preview.png"
    render_preview(Image, ImageDraw, frame_paths, frame_width, frame_height, columns, spec.preview_scale, preview_path)

    rows = (len(frame_paths) + columns - 1) // columns
    manifest = {
        "name": spec.name,
        "source_images": [manifest_path(path) for path in source_paths],
        "source_image_urls": [url for path in source_paths if (url := public_url(path))],
        "frame_width": frame_width,
        "frame_height": frame_height,
        "columns": columns,
        "rows": rows,
        "frame_count": len(frame_paths),
        "frames": [
            {
                "path": manifest_path(frame_path),
                "url": public_url(frame_path),
            }
            for frame_path in frame_paths
        ],
        "preview": manifest_path(preview_path),
        "preview_url": public_url(preview_path),
    }
    manifest_file = spec.output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2) + "\n")
    return frame_paths, preview_path, manifest


def remove_flat_background(Image: Any, frame: Any) -> Any:
    """Remove edge-connected solid model backgrounds from opaque generated sprites."""
    frame = frame.convert("RGBA")
    alpha = frame.getchannel("A")
    if alpha.getextrema()[0] < 250:
        return frame

    background = estimate_edge_background(frame)
    width, height = frame.size
    data = flattened_image_data(frame)
    background_mask = bytearray(width * height)
    stack: list[int] = []

    def enqueue(index: int) -> None:
        if background_mask[index] or not is_background_pixel(data[index], background):
            return
        background_mask[index] = 1
        stack.append(index)

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(1, height - 1):
        enqueue(y * width)
        enqueue(y * width + width - 1)

    while stack:
        index = stack.pop()
        x = index % width
        y = index // width
        if x > 0:
            enqueue(index - 1)
        if x + 1 < width:
            enqueue(index + 1)
        if y > 0:
            enqueue(index - width)
        if y + 1 < height:
            enqueue(index + width)

    if not any(background_mask):
        return frame

    cleaned = Image.new("RGBA", frame.size)
    cleaned.putdata(
        [
            (red, green, blue, 0) if background_mask[index] else (red, green, blue, original_alpha)
            for index, (red, green, blue, original_alpha) in enumerate(data)
        ]
    )
    return cleaned


def estimate_edge_background(frame: Any) -> tuple[int, int, int]:
    width, height = frame.size
    samples: list[tuple[int, int, int]] = []
    for x in range(width):
        samples.append(frame.getpixel((x, 0))[:3])
        samples.append(frame.getpixel((x, height - 1))[:3])
    for y in range(1, height - 1):
        samples.append(frame.getpixel((0, y))[:3])
        samples.append(frame.getpixel((width - 1, y))[:3])
    return tuple(channel_median(samples, index) for index in range(3))


def flattened_image_data(frame: Any) -> list[tuple[int, int, int, int]]:
    if hasattr(frame, "get_flattened_data"):
        return list(frame.get_flattened_data())

    return list(frame.getdata())


def channel_median(samples: list[tuple[int, int, int]], channel: int) -> int:
    values = sorted(sample[channel] for sample in samples)
    return values[len(values) // 2]


def is_background_pixel(pixel: tuple[int, int, int, int], background: tuple[int, int, int]) -> bool:
    red, green, blue, alpha = pixel
    if alpha < 16:
        return True

    distance = ((red - background[0]) ** 2 + (green - background[1]) ** 2 + (blue - background[2]) ** 2) ** 0.5
    return distance <= 52


def render_preview(
    Image: Any,
    ImageDraw: Any,
    frame_paths: list[Path],
    frame_width: int,
    frame_height: int,
    columns: int,
    scale: int,
    out_path: Path,
) -> None:
    rows = (len(frame_paths) + columns - 1) // columns
    pad = 8
    cell_width = frame_width * scale
    cell_height = frame_height * scale
    width = columns * cell_width + (columns + 1) * pad
    height = rows * cell_height + (rows + 1) * pad
    preview = Image.new("RGBA", (width, height), (22, 26, 30, 255))
    draw = ImageDraw.Draw(preview)
    for y in range(0, height, 12):
        for x in range(0, width, 12):
            fill = (30, 35, 40, 255) if ((x // 12 + y // 12) % 2 == 0) else (22, 26, 30, 255)
            draw.rectangle((x, y, x + 11, y + 11), fill=fill)

    for index, frame_path in enumerate(frame_paths):
        frame = Image.open(frame_path).convert("RGBA").resize((cell_width, cell_height), Image.Resampling.NEAREST)
        row = index // columns
        column = index % columns
        preview.alpha_composite(frame, (pad + column * (cell_width + pad), pad + row * (cell_height + pad)))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(out_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a sprite sheet from a markdown spec")
    parser.add_argument("spec", type=Path, help="Markdown sprite description")
    parser.add_argument("--dry-run", action="store_true", help="Print generation settings without calling Replicate")
    parser.add_argument("--skip-generate", action="store_true", help="Only slice and preview an existing sheet")
    parser.add_argument("--sheet", type=Path, default=None, help="Existing sheet path for --skip-generate")
    parser.add_argument("--source-image", type=Path, action="append", default=[], help="Existing generated sprite image to resize into a frame")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override output directory")
    parser.add_argument("--no-split", action="store_true", help="Do not slice frames or render a preview")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    spec_path = args.spec if args.spec.is_absolute() else REPO_ROOT / args.spec
    output_dir_override = args.output_dir
    if output_dir_override and not output_dir_override.is_absolute():
        output_dir_override = REPO_ROOT / output_dir_override
    spec = load_spec(spec_path, output_dir_override)
    spec.output_dir.mkdir(parents=True, exist_ok=True)

    if args.source_image:
        sheet_path = None
        source_paths = [
            source_image if source_image.is_absolute() else REPO_ROOT / source_image
            for source_image in args.source_image
        ]
    elif args.skip_generate:
        if args.sheet is None:
            raise SystemExit("--sheet is required with --skip-generate")
        sheet_path = args.sheet if args.sheet.is_absolute() else REPO_ROOT / args.sheet
        source_paths: list[Path] = []
    else:
        sheet_path, source_paths = run_generator(spec, args.dry_run)
        if args.dry_run:
            return 0

    if not args.no_split:
        if source_paths:
            frame_paths, preview_path, manifest = build_frames_from_images(spec, source_paths)
        elif sheet_path is not None:
            frame_paths, preview_path, manifest = split_sheet(spec, sheet_path)
        else:
            raise RuntimeError("generator did not provide a sheet or sprite images")
        print(f"Sliced {len(frame_paths)} frame(s)")
        if sheet_path is not None:
            print(f"  Sheet: {sheet_path}")
        if source_paths:
            print(f"  Sources: {', '.join(str(path) for path in source_paths)}")
        print(f"  Preview: {preview_path}")
        if manifest.get("preview_url"):
            print(f"  Preview URL: {manifest['preview_url']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
