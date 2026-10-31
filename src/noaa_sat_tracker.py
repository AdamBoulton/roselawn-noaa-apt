#!/usr/bin/env python3
"""Backward-compatible entry point; NOAA POES APT services are decommissioned."""
from meteor_sat_tracker import main

if __name__ == "__main__":
    print("NOTICE: NOAA-15/18/19 APT is decommissioned. Running the Meteor-M tracker instead.")
    main()
