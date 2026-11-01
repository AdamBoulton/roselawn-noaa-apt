#!/usr/bin/env python3
"""Schedule and receive Meteor-M LRPT passes with SatDump and HackRF One.

SatDump performs the LRPT demodulation, frame synchronisation, error correction
and image processing. This script handles fresh orbital predictions and pass
scheduling; it deliberately does not implement a second, incomplete decoder.
"""
from __future__ import annotations

import argparse
import math
import re
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


def detect_satdump_cli_mode(satdump: str) -> str:
    """Detect the SatDump live CLI syntax supported by the installed build.

    Newer builds document 'satdump legacy live ...'. Older/stable 1.x builds use
    'satdump live ...' and only print live usage when 'satdump live' is invoked.
    """
    for cmd in ([satdump, "--help"], [satdump, "live"]):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            help_text = (result.stdout or "") + "\n" + (result.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            return "live"

        if re.search(r"\bsatdump\s+legacy\s+live\b", help_text, flags=re.IGNORECASE):
            return "legacy"
        if re.search(r"\bsatdump\s+live(?:\s|\[|<)", help_text, flags=re.IGNORECASE):
            return "live"

    return "live"


def build_satdump_command(args: argparse.Namespace, output_dir: Path, duration: int) -> list[str]:
    command = [args.satdump]
    if args.satdump_cli_mode == "legacy":
        command.extend(["legacy", "live"])
    else:
        command.append("live")
    command.extend([
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
        "--finish_processing",
    ])
    if args.amp:
        command.append("--amp")
    if args.bias:
        command.append("--bias")
    if args.fill_missing:
        command.append("--fill_missing")
    return command


def build_satdump_record_command(args: argparse.Namespace, baseband_prefix: Path, duration: int) -> list[str]:
    command = [
        args.satdump,
        "record",
        str(baseband_prefix),
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
    if args.amp:
        command.append("--amp")
    if args.bias:
        command.append("--bias")
    return command


def build_satdump_offline_command(
    args: argparse.Namespace,
    pipeline: str,
    input_level: str,
    input_file: Path,
    output_dir: Path,
) -> list[str]:
    command = [
        args.satdump,
        pipeline,
        input_level,
        str(input_file),
        str(output_dir),
    ]
    if input_level == "baseband":
        command.extend([
            "--samplerate",
            str(args.sample_rate),
            "--baseband_format",
            "cs8",
            "--dc_block",
        ])
    if args.fill_missing:
        command.append("--fill_missing")
    return command


def find_images(output_dir: Path) -> list[Path]:
    return sorted(
        path for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
    )


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

    if capture_start > now:
        print(f"Waiting until {capture_start:%H:%M:%S} UTC...")
        wait_until(capture_start)

    output_dir.mkdir(parents=True, exist_ok=True)
    duration = max(30, math.ceil((capture_end - datetime.now(timezone.utc)).total_seconds()))

    if args.record_baseband:
        baseband_prefix = output_dir / "baseband"
        command = build_satdump_record_command(args, baseband_prefix, duration)
    else:
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

    if args.record_baseband and return_code == 0:
        baseband_file = output_dir / "baseband.cs8"
        if baseband_file.is_file() and baseband_file.stat().st_size > 0:
            pipelines_to_try = [args.pipeline]
            if args.pipeline == "meteor_m2-x_lrpt":
                pipelines_to_try.append("meteor_m2-x_lrpt_80k")
            for pipeline in pipelines_to_try:
                decode_cmd = build_satdump_offline_command(
                    args, pipeline, "baseband", baseband_file, output_dir
                )
                print(f"\nDecoding recorded baseband with pipeline '{pipeline}':")
                print("  " + " ".join(decode_cmd))
                subprocess.run(decode_cmd, check=False)
                if find_images(output_dir):
                    break

    images = find_images(output_dir)
    cadu_files = sorted(output_dir.glob("*.cadu"))
    non_empty_cadus = [f for f in cadu_files if f.is_file() and f.stat().st_size > 0]

    # Fallback: if live capture wrote CADU frames but skipped product generation, run offline CADU decode.
    if return_code == 0 and not images and non_empty_cadus:
        cadu_file = non_empty_cadus[0]
        decode_cmd = build_satdump_offline_command(
            args, args.pipeline, "cadu", cadu_file, output_dir
        )
        print(f"\nFound non-empty CADU file ({cadu_file.stat().st_size:,} bytes); generating images:")
        print("  " + " ".join(decode_cmd))
        subprocess.run(decode_cmd, check=False)
        images = find_images(output_dir)

    if return_code == 0 and images:
        print(f"\nSatDump finished. Found {len(images)} image file(s):")
        for image in images:
            print(f"  {image}")
    elif return_code == 0:
        if non_empty_cadus:
            cadu_bytes = sum(f.stat().st_size for f in non_empty_cadus)
            print(
                f"\nSatDump exited with {cadu_bytes:,} bytes of CADU frames in {output_dir}, "
                "but no MSU-MR image channels contained enough lines to render an image."
            )
        else:
            print(
                "\nSatDump exited successfully but 0 CADU frames were locked (meteor_m2-x_lrpt.cadu is 0 bytes). "
                "The demodulator did not achieve Viterbi / Reed-Solomon frame synchronisation during the pass.\n"
                "Tips:\n"
                "  1. Check antenna placement and coax connection.\n"
                "  2. Increase gain if signal levels are too weak (e.g. --lna-gain 40 --vga-gain 36 or --amp).\n"
                "  3. Pass --record-baseband to save raw IQ (.cs8) and automatically try both 72k and 80k LRPT modes."
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
    parser.add_argument("--lna-gain", type=int, default=40, help="HackRF LNA gain (0–40, 8 dB steps).")
    parser.add_argument("--vga-gain", type=int, default=32, help="HackRF VGA gain (0–62, 2 dB steps).")
    parser.add_argument(
        "--amp",
        action="store_true",
        help="Enable HackRF internal 14 dB RF amplifier (use with caution near strong FM transmitters).",
    )
    parser.add_argument(
        "--bias",
        action="store_true",
        help="Enable HackRF antenna port bias-tee power (only when an external filtered LNA is inline).",
    )
    parser.add_argument(
        "--fill-missing",
        action="store_true",
        help="Ask SatDump to generate filled MSU-MR images correcting short dropouts.",
    )
    parser.add_argument(
        "--record-baseband",
        action="store_true",
        help="Record raw .cs8 IQ baseband first, then decode offline (trying both 72k and 80k LRPT if needed).",
    )
    parser.add_argument("--pipeline", default=DEFAULT_PIPELINE)
    parser.add_argument("--satdump", default="satdump")
    parser.add_argument(
        "--satdump-cli-mode",
        choices=("auto", "legacy", "live"),
        default="auto",
        help="SatDump command syntax; auto-detected by default.",
    )
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

    if args.satdump_cli_mode == "auto":
        args.satdump_cli_mode = detect_satdump_cli_mode(args.satdump)
    print(f"SatDump CLI mode: {args.satdump_cli_mode}")
    print("Roselawn Radio — Meteor-M LRPT automatic receiver")
    print(
        f"Pipeline: {args.pipeline} | HackRF sample rate: {args.sample_rate:,} samples/s | "
        f"RF: {args.frequency_mhz:.3f} MHz | LNA: {args.lna_gain} dB | VGA: {args.vga_gain} dB | "
        f"AMP: {'on' if args.amp else 'off'}"
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
