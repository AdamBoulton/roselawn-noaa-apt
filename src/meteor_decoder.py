#!/usr/bin/env python3
"""Decode a recorded HackRF IQ file using SatDump's Meteor-M LRPT pipeline."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline Meteor-M LRPT decoder for raw HackRF IQ recordings."
    )
    parser.add_argument("input", type=Path, help="Raw complex IQ input file (HackRF signed 8-bit: .cs8).")
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="Output directory (default: <input-stem>_decoded).",
    )
    parser.add_argument("--satdump", default="satdump")
    parser.add_argument("--pipeline", default="meteor_m2-x_lrpt")
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument(
        "--baseband-format",
        default="cs8",
        choices=("cs8", "cs16", "cf32", "cu8"),
    )
    parser.add_argument(
        "--satellite-number",
        choices=("M2", "M2-2", "M2-3", "M2-4"),
        help="Optional override if the recorded satellite cannot be identified automatically.",
    )
    args = parser.parse_args()

    if not args.input.is_file():
        raise SystemExit(f"Input file does not exist: {args.input}")
    satdump = shutil.which(args.satdump)
    if satdump is None:
        raise SystemExit(f"SatDump executable not found: {args.satdump}")

    output_dir = args.output or args.input.with_name(args.input.stem + "_decoded")
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        satdump,
        "pipeline",
        args.pipeline,
        "baseband",
        str(args.input),
        str(output_dir),
        "--samplerate",
        str(args.sample_rate),
        "--baseband_format",
        args.baseband_format,
    ]
    if args.satellite_number:
        command.extend(["--satellite_number", args.satellite_number])

    print("Running:", " ".join(command))
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise SystemExit(result.returncode)
    print(f"SatDump processing finished. Output: {output_dir}")


if __name__ == "__main__":
    main()
