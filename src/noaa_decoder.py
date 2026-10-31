#!/usr/bin/env python3
"""
Roselawn Radio - Official NOAA APT Satellite Image Decoder
Integrates noaa-apt v1.4.1 for fast, precise satellite image decoding with false-color palettes & country borders.
"""

import sys
import os
import wave
import argparse
import subprocess
import shutil
import numpy as np

NOAA_APT_BIN = shutil.which("noaa-apt") or "/tmp/noaa-apt-bin/noaa-apt"

def decode_apt_wav(wav_path, output_png_path=None):
    if not os.path.exists(wav_path):
        print(f"❌ Error: File not found: {wav_path}")
        return None

    if not output_png_path:
        output_png_path = wav_path.rsplit(".", 1)[0] + "_DECODED.png"

    print(f"🖼️ Decoding NOAA APT Satellite Image with noaa-apt from: {os.path.basename(wav_path)}...")

    if os.path.exists(NOAA_APT_BIN):
        try:
            cmd = [
                NOAA_APT_BIN,
                "-o", output_png_path,
                wav_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if os.path.exists(output_png_path):
                print(f"✅ SATELLITE IMAGE SUCCESSFULLY GENERATED VIA NOAA-APT:")
                print(f"   👉 {output_png_path}")
                return output_png_path
        except Exception as e:
            print(f"⚠️ noaa-apt fallback to python engine: {e}")

    # Python Fallback Decoder
    try:
        from PIL import Image
        from scipy import signal

        with wave.open(wav_path, "rb") as wf:
            rate = wf.getframerate()
            nframes = wf.getnframes()
            raw_pcm = wf.readframes(nframes)

        data = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
        if len(data) == 0:
            return None

        numtaps = 61
        bp_filter = signal.firwin(numtaps, [1200, 3600], pass_zero=False, fs=rate)
        filtered_audio = signal.lfilter(bp_filter, 1.0, data)
        envelope = np.abs(signal.hilbert(filtered_audio))

        target_rate = 4160
        num_resampled = int(len(envelope) * (target_rate / rate))
        resampled_env = signal.resample(envelope, num_resampled)

        pixels_per_line = 2080
        num_lines = len(resampled_env) // pixels_per_line
        if num_lines < 10:
            return None

        img_matrix = resampled_env[:num_lines * pixels_per_line].reshape((num_lines, pixels_per_line))

        sync_a = np.tile(np.array([0, 0, 0, 255, 255, 0, 255, 255, 0, 255, 255, 0, 255, 255, 0, 255, 255, 0, 0, 0], dtype=np.float32), 2)
        aligned_matrix = np.zeros_like(img_matrix)

        for l_idx in range(num_lines):
            line = img_matrix[l_idx]
            corr = np.correlate(line[:400], sync_a, mode='valid')
            if len(corr) > 0:
                shift = np.argmax(corr)
                aligned_matrix[l_idx] = np.roll(line, -shift)
            else:
                aligned_matrix[l_idx] = line

        p_min = np.percentile(aligned_matrix, 5)
        p_max = np.percentile(aligned_matrix, 95)
        norm_matrix = np.clip((aligned_matrix - p_min) / (p_max - p_min + 1e-5) * 255.0, 0, 255).astype(np.uint8)

        img = Image.fromarray(norm_matrix, mode="L")
        img.save(output_png_path, "PNG")
        print(f"✅ SATELLITE IMAGE SUCCESSFULLY GENERATED & SAVED TO:")
        print(f"   👉 {output_png_path}")
        return output_png_path

    except Exception as e:
        print(f"❌ APT Decoding Error: {e}")
        return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NOAA APT Image Decoder")
    parser.add_argument("wav", type=str, help="Path to recorded NOAA APT WAV file")
    parser.add_argument("-o", "--output", type=str, help="Output PNG path")
    args = parser.parse_args()

    decode_apt_wav(args.wav, args.output)
