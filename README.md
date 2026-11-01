# Roselawn Radio — Meteor-M LRPT Satellite Ground Station

Roselawn Radio receives digital weather imagery from the **Meteor-M N2-3** and
**Meteor-M N2-4** polar-orbiting weather satellites using a **HackRF One** and
a 137 MHz V-dipole antenna.

> **Important change:** NOAA-15, NOAA-18 and NOAA-19 have all been decommissioned.
> Their old APT frequencies and the original hardcoded pass schedule are no
> longer useful for live reception. The old noaa_*.py script names remain as
> compatibility launchers, but now call the Meteor-M implementation.

## Current receiving target

| Satellite | NORAD catalogue number | Mode | LRPT frequency |
|---|---:|---|---:|
| Meteor-M N2-3 | 57166 | LRPT | 137.900 MHz |
| Meteor-M N2-4 | 59051 | LRPT | 137.900 MHz |

Satellite operation and transmission frequencies can change. The tracker
downloads current two-line elements from CelesTrak for orbital predictions.
TLEs are cached locally and rejected when older than seven days; stale orbital
elements are not silently used.

## Signal and software pipeline

1. A horizontal V-dipole receives the 137.9 MHz LRPT downlink.
2. HackRF One supplies the IQ stream to SatDump.
3. SatDump's meteor_m2-x_lrpt pipeline performs demodulation, frame
   synchronisation, error correction and image reconstruction.
4. SatDump products are written beneath ~/Pictures/Weather_Satellites/.

The Python code schedules passes and launches SatDump. It intentionally does
not implement its own LRPT demodulator or image decoder.

## Hardware setup

- HackRF One with current firmware and working USB connection.
- V-dipole with each element extended to approximately **53.5 cm**.
- Start with the elements horizontal and approximately **120° apart**.
- Put the antenna outside with a clear view of as much sky as practical.
- Keep the coaxial feed and nearby electronics away from the radiating elements.
- A low-loss coaxial cable is preferable. Avoid adding an LNA or filter until
  you have checked the spectrum and confirmed that it is needed.

The V-dipole is a reasonable starting antenna, but it is linearly polarised.
Meteor transmissions are circularly polarised, so fading due to polarisation
and satellite attitude can still occur. A suitable circularly polarised antenna
can be considered after the first signal test.

## Installation (Linux Mint / Ubuntu)

### 1. System packages

~~~bash
sudo apt update
sudo apt install -y hackrf libhackrf-dev python3 python3-venv python3-pip
~~~

Check that the operating system can see the SDR:

~~~bash
hackrf_info
~~~

If access is denied, configure the HackRF udev rules for your distribution and
reconnect the device. Do not run the receiver permanently as root just to work
around missing USB permissions.

### 2. Install SatDump

Install a current Linux SatDump build from the official project releases or
build it from the official source repository:

- https://github.com/SatDump/SatDump/releases
- https://github.com/SatDump/SatDump

The build must include HackRF SDR support. Check that the CLI is available:

~~~bash
satdump --help
satdump sdr_probe
~~~

The SDR probe should list HackRF. The live command used by this project follows
SatDump's documented legacy live interface.

### 3. Python environment

From the repository root:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
~~~

## First reception: recommended sequence

### 1. Verify upcoming passes

~~~bash
python src/meteor_sat_tracker.py --hours 24 --min-elevation 25
~~~

The tracker prints AOS, peak and LOS in UTC. It uses fresh CelesTrak TLEs for
NORAD 57166 and 59051. A high pass (ideally above 40°) is a better first target
than a low pass.

### 2. Check the pass schedule without starting the SDR

~~~bash
python src/meteor_sat_receiver.py --list --hours 24 --min-elevation 25
~~~

### 3. Automatically receive the next qualifying pass

~~~bash
python src/meteor_sat_receiver.py
~~~

The receiver waits until 30 seconds before the next pass, then starts SatDump
and captures until 30 seconds after the satellite drops below the 10° horizon
threshold.

### 4. Keep the station running

~~~bash
python src/meteor_sat_receiver.py --continuous
~~~

The process refreshes orbital elements between passes and schedules the next
qualifying pass. Use Ctrl+C to stop it.

### 5. Choose stricter pass criteria or a different output directory

~~~bash
python src/meteor_sat_receiver.py --list --min-elevation 40
python src/meteor_sat_receiver.py --min-elevation 40 --output-dir "$HOME/SatelliteImages"
~~~

## Receiver settings

The default live capture settings are tuned to drive the HackRF 8-bit ADC above
quantisation noise while keeping the internal 14 dB RF amplifier off to avoid
FM broadcast overload:

- RF: 137.900 MHz
- Sample rate: 2,000,000 samples/s
- HackRF LNA gain: 40 dB
- HackRF VGA gain: 32 dB
- RF amplifier: off (enable with `--amp` if needed)
- Bias-tee power: off (enable with `--bias` only when an external filtered LNA is inline)
- DC blocking: enabled
- Post-pass product generation (`--finish_processing`): enabled
- SatDump pipeline: meteor_m2-x_lrpt

The gain settings are starting values, not universal optimums. Strong local
signals can overload the front end; weak signals may require different gain
settings or a better antenna installation. Change gains only after inspecting
the received spectrum and SatDump logs.

For example:

~~~bash
python src/meteor_sat_receiver.py --lna-gain 40 --vga-gain 36
python src/meteor_sat_receiver.py --record-baseband --fill-missing
~~~

Passing `--record-baseband` records the raw `.cs8` IQ stream during the pass
and then runs offline decoding (automatically trying `meteor_m2-x_lrpt_80k` if
the default `72k` pipeline produces no images).

## Offline decoding of a raw IQ or CADU capture

For a raw signed 8-bit IQ file recorded at 2 MS/s or a `.cadu` frame file:

~~~bash
python src/meteor_decoder.py recording.cs8 --sample-rate 2000000 --baseband-format cs8
python src/meteor_decoder.py meteor_m2-x_lrpt.cadu
~~~

SatDump's offline pipeline syntax and supported Meteor LRPT options are
documented at:

https://github.com/SatDump/SatDump.Docs/blob/master/pipelines.rst


### SatDump CLI compatibility

The receiver detects the installed SatDump live command syntax automatically.
Older releases use \`satdump live PIPELINE OUTPUT\`; newer releases may use
\`satdump legacy live PIPELINE OUTPUT\`. For custom or unusual builds, override
the detection explicitly:

~~~bash
python src/meteor_sat_receiver.py --satdump-cli-mode live
python src/meteor_sat_receiver.py --satdump-cli-mode legacy
~~~

## Troubleshooting

### HackRF is not detected

~~~bash
hackrf_info
satdump sdr_probe
~~~

Check USB permissions, udev rules, cable quality and that another application
is not already using the HackRF.

### Pass predictions look wrong

The tracker needs internet access to obtain fresh TLEs. It will use a cached
TLE only if its epoch is no more than seven days old. Check the warning printed
by the tracker and compare predictions with a second orbital tracker.

### SatDump runs but no image is produced

Check the SatDump console output and the pass output directory. A process exit
code of zero does not guarantee that enough valid LRPT frames were received.
Look for frame synchronisation and Reed-Solomon statistics. Poor results can
be caused by a low-elevation pass, obstructions, polarisation fading, local
interference, excessive gain, a poor coax connection or a frequency/configuration
mismatch.

### Image is incomplete or noisy

Try a higher-elevation pass first. Keep the antenna clear of buildings and
trees, check the connector and coax, and inspect the waterfall for interference
near 137.9 MHz before changing hardware.

## Project files

- src/meteor_sat_tracker.py — downloads current TLEs and predicts passes.
- src/meteor_sat_receiver.py — schedules passes and launches SatDump live.
- src/meteor_decoder.py — runs SatDump offline on an IQ recording.
- src/noaa_*.py — compatibility launchers for the previous command names.

## References

- NOAA POES decommissioning notice:
  https://www.nesdis.noaa.gov/news/suspension-of-poes-data-users-after-june-16-2025-and-decommissioning
- CelesTrak GP/TLE service:
  https://celestrak.org/NORAD/elements/
- SatDump:
  https://github.com/SatDump/SatDump
- SatDump pipeline reference:
  https://github.com/SatDump/SatDump.Docs/blob/master/pipelines.rst

## License

MIT License — Roselawn Radio SDR Project.
