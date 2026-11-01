#!/usr/bin/env python3
"""Decode a recorded HackRF IQ or CADU file using SatDump's Meteor-M LRPT pipeline."""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


def uses_pipeline_subcommand(satdump: str) -> bool:
    """Check whether the installed SatDump build expects a 'pipeline' subcommand."""
    try:
        result = subprocess.run(
            [satdump, "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        help_text = (result.stdout or "") + "\n" + (result.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(re.search(r"\bsatdump\s+(?:legacy\s+)?pipeline\b", help_text, flags=re.IGNORECASE))


def find_images(output_dir: Path) -> list[Path]:
    return sorted(
        path for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline Meteor-M LRPT decoder for raw HackRF IQ (.cs8) or .cadu recordings."
    )
    parser.add_argument("input", type=Path, help="Input file (e.g. .cs8 baseband or .cadu frame file).")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="Output directory (default: <input-stem>_decoded).",
    )
    parser.add_argument("--satdump", default="satdump")
    parser.add_argument("--pipeline", default="meteor_m2-x_lrpt")
    parser.add_argument(
        "--input-level",
        choices=("auto", "baseband", "soft", "cadu"),
        default="auto",
        help="Pipeline input level (default: auto-detected from file extension).",
    )
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument(
        "--baseband-format",
        default="cs8",
        choices=("cs8", "cs16", "cf32", "cu8"),
    )
    parser.add_argument(
        "--dc-block",
        action="store_true",
        default=True,
        help="Enable DC spike blocking for baseband input (default: enabled).",
    )
    parser.add_argument(
        "--fill-missing",
        action="store_true",
        help="Ask SatDump to generate filled MSU-MR images correcting short dropouts.",
    )
    parser.add_argument(
        "--satellite-number",
        choices=("M2", "M2-2", "M2-3", "M2-4"),
        help="Optional override if the recorded satellite cannot be identified automatically.",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"Input file does not exist: {args.input}")
    if args.input.stat().st_size == 0:
        raise SystemExit(f"Input file is empty (0 bytes): {args.input}")

    satdump = shutil.which(args.satdump)
    if satdump is None:
        raise SystemExit(f"SatDump executable not found: {args.satdump}")

    input_level = args.input_level
    if input_level == "auto":
        suffix = args.input.suffix.lower()
        if suffix == ".cadu":
            input_level = "cadu"
        elif suffix == ".soft":
            input_level = "soft"
        else:
            input_level = "baseband"

    output_dir = args.output or args.input.with_name(args.input.stem + "_decoded")
    output_dir.mkdir(parents=True, exist_ok=True)

    command = [satdump]
    if uses_pipeline_subcommand(satdump):
        command.append("pipeline")
    command.extend([
        args.pipeline,
        input_level,
        str(args.input),
        str(output_dir),
    ])
    if input_level == "baseband":
        command.extend([
            "--samplerate",
            str(args.sample_rate),
            "--baseband_format",
            args.baseband_format,
        ])
        if args.dc_block:
            command.append("--dc_block")
    if args.fill_missing:
        command.append("--fill_missing")
    if args.satellite_number:
        command.extend(["--satellite_number", args.satellite_number])

    print("Running:", " ".join(command))
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)

    images = find_images(output_dir)
    if images:
        print(f"\nSatDump processing finished. Found {len(images)} image file(s):")
        for image in images:
            print(f"  {image}")
    else:
        print(
            f"\nSatDump processing finished (output: {output_dir}), "
            "but no image files were produced."
        )


if __name__ == "__main__":
    main()
