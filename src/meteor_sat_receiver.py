#!/usr/bin/env python3
"""Schedule and receive Meteor-M LRPT passes with SatDump and HackRF One.

SatDump performs the LRPT demodulation, frame synchronisation, error correction
and image processing. This script handles fresh orbital predictions and pass
scheduling; it deliberately does not implement a second, incomplete decoder.
"""
from __future__ import annotations

import argparse
import math
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meteor_sat_tracker import SATELLITES, calculate_passes, print_passes

DEFAULT_OUTPUT_DIR = Path.home() / "Pictures" / "Weather_Satellites"
DEFAULT_PIPELINE = "meteor_m2-x_lrpt"


def wait_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(5.0, remaining))


def build_satdump_command(args: argparse.Namespace, output_dir: Path, duration: int) -> list[str]:
    return [
        args.satdump,
        "live",
        args.pipeline,
        str(output_dir),
        "--source",
        "hackrf",
        "--samplerate",
        str(args.sample_rate),
        "--baseband_format",
        "cs8",
        "--frequency",
        str(int(args.frequency_mhz * 1_000_000)),
        "--lna_gain",
        str(args.lna_gain),
        "--vga_gain",
        str(args.vga_gain),
        "--timeout",
        str(duration),
        "--dc_block",
    ]


def run_capture(args: argparse.Namespace, satellite_pass: dict) -> int:
    now = datetime.now(timezone.utc)
    capture_start = max(now, satellite_pass["rise"] - timedelta(seconds=args.lead_seconds))
    capture_end = satellite_pass["set"] + timedelta(seconds=args.tail_seconds)
    if capture_end <= capture_start:
        print("Pass has already ended; skipping.")
        return 1

    print(
        f"\nNext capture: {satellite_pass['satellite']} "
        f"({satellite_pass['frequency_mhz']:.3f} MHz)"
    )
    print(
        f"Peak {satellite_pass['max_elevation']:.1f}° at "
        f"{satellite_pass['peak']:%Y-%m-%d %H:%M:%S} UTC; "
        f"capture window {capture_start:%H:%M:%S}–{capture_end:%H:%M:%S} UTC."
    )
    if satellite_pass["max_elevation"] < 30:
        print(
            "NOTE: This is a low-elevation pass. A higher pass generally gives "
            "a longer, less obstructed reception window."
        )

    output_dir = args.output_dir.expanduser() / (
        f"{satellite_pass['satellite'].lower().replace('-', '_')}_"
        f"{capture_start:%Y%m%d_%H%M%S}_utc"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    if capture_start > now:
        print(f"Waiting until {capture_start:%H:%M:%S} UTC...")
        wait_until(capture_start)

    duration = max(30, math.ceil((capture_end - datetime.now(timezone.utc)).total_seconds()))
    command = build_satdump_command(args, output_dir, duration)
    print("Starting SatDump:")
    print("  " + " ".join(command))
    print(f"Output directory: {output_dir}")
    print("Keep the antenna and HackRF connected until the capture finishes.\n")

    process = None
    try:
        process = subprocess.Popen(command)
        return_code = process.wait()
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Could not find '{args.satdump}'. Install SatDump and ensure its CLI "
            "executable is on PATH, or pass --satdump /full/path/to/satdump."
        ) from exc
    except KeyboardInterrupt:
        print("\nStopping SatDump...")
        if process is not None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
        return 130

    images = [
        path for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    ]
    if return_code == 0 and images:
        print(f"\nSatDump finished. Found {len(images)} image file(s):")
        for image in images:
            print(f"  {image}")
    elif return_code == 0:
        print(
            "\nSatDump exited successfully but no image file was found. "
            "Check its console output for frame synchronisation / Reed-Solomon "
            "errors and inspect the capture folder."
        )
    else:
        print(f"\nSatDump exited with status {return_code}.")
    return return_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automatically receive Meteor-M N2-3/N2-4 LRPT passes using HackRF and SatDump."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List upcoming passes without starting a receiver.",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Keep tracking and automatically capture successive passes.",
    )
    parser.add_argument("--satellite", choices=tuple(SATELLITES))
    parser.add_argument("--hours", type=float, default=24.0, help="Pass prediction look-ahead.")
    parser.add_argument(
        "--min-elevation",
        type=float,
        default=25.0,
        help="Only schedule passes whose peak elevation meets this threshold.",
    )
    parser.add_argument("--lead-seconds", type=int, default=30)
    parser.add_argument("--tail-seconds", type=int, default=30)
    parser.add_argument("--frequency-mhz", type=float, default=137.900)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--lna-gain", type=int, default=24, help="HackRF LNA gain (0–40, 8 dB steps).")
    parser.add_argument("--vga-gain", type=int, default=20, help="HackRF VGA gain (0–62, 2 dB steps).")
    parser.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    parser.add_argument("--satdump", default="satdump")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.hours <= 0:
        raise SystemExit("--hours must be greater than zero.")
    if not 0 <= args.lna_gain <= 40 or args.lna_gain % 8:
        raise SystemExit("--lna-gain must be 0–40 in 8 dB steps.")
    if not 0 <= args.vga_gain <= 62 or args.vga_gain % 2:
        raise SystemExit("--vga-gain must be 0–62 in 2 dB steps.")
    if args.sample_rate < 1_000_000:
        raise SystemExit("--sample-rate must be at least 1 MS/s.")

    if args.list:
        try:
            passes = calculate_passes(args.hours, args.min_elevation, args.satellite)
            print_passes(passes)
            return
        except Exception as exc:
            raise SystemExit(f"ERROR: {exc}") from exc

    if not shutil.which(args.satdump):
        raise SystemExit(
            f"SatDump executable '{args.satdump}' was not found. "
            "Install SatDump and ensure its CLI is on PATH."
        )

    print("Roselawn Radio — Meteor-M LRPT automatic receiver")
    print(
        f"Pipeline: {args.pipeline} | HackRF sample rate: {args.sample_rate:,} samples/s | "
        f"RF: {args.frequency_mhz:.3f} MHz"
    )
    while True:
        try:
            passes = calculate_passes(args.hours, args.min_elevation, args.satellite)
        except Exception as exc:
            print(f"Pass calculation failed: {exc}", file=sys.stderr)
            if not args.continuous:
                raise SystemExit(1) from exc
            time.sleep(60)
            continue

        now = datetime.now(timezone.utc)
        future_passes = [item for item in passes if item["set"] > now]
        if not future_passes:
            if not args.continuous:
                print("No qualifying pass found in the look-ahead window.")
                return
            print("No qualifying pass found. Checking again in 60 seconds...")
            time.sleep(60)
            continue

        next_pass = future_passes[0]
        result = run_capture(args, next_pass)
        if result == 130:
            return
        if not args.continuous:
            return
        print("\nRefreshing orbital elements before looking for the next pass...")
        time.sleep(5)


if __name__ == "__main__":
    main()
