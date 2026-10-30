"""--benchmark: the offline speed test. No pool, no wallet, no network —
a synthetic job at the exact default mining shape, swept by the same
Engine/GridFactory machinery as live mining (grid rebuild stalls included),
so the number it prints is the number the miner really achieves. This is
what makes the README's headline speed reproducible by a shipped command,
and its paste-ready block is the format contract for the community
hardware table in the README.
"""

from __future__ import annotations

import datetime
import json
import platform
import time

from . import __version__
from . import reference as ref
from pearl_m_miner.safety import BatteryPoller


class _SyntheticJob:
    job_id = "benchmark"
    header_bytes = bytes(range(76))  # any fixed 76 bytes; timing is value-blind
    cert_version = 3


def run(args, shape) -> int:
    # lazy — miner imports us lazily
    from .miner import Engine, GridFactory, log, power_source

    factor = ref.difficulty_factor(shape.h, shape.w, args.k, args.rank)
    seconds = args.benchmark_seconds
    warmup = min(10.0, max(2.0, seconds / 5))

    log("benchmark: offline synthetic cert3 job — no pool, no wallet, no network")
    engine = Engine(shape, args.m, args.n)
    # Keep external pmset queries out of the per-region GPU hot path.
    initial_power = power_source()
    battery = BatteryPoller(power_source, initial=initial_power)
    power = "AC" if initial_power == "ac" else "battery"
    if power == "battery":
        log("on battery — benchmark scanning will wait for AC power")
    log(f"warmup {warmup:.0f}s, then {seconds:.0f}s measured at intensity 100")

    factory = GridFactory(shape, args.m, args.n)
    job = _SyntheticJob()
    bound = (1).to_bytes(32, "little")  # nothing can hit: pure sweep timing
    grid = factory.take(job)
    factory.request(job)
    engine.load_grid(grid)
    n_regions = engine.n_regions(args.region_rows)
    row_cursor = 0
    tiles = 0
    t_warm_end = time.monotonic() + warmup
    t_measure_0 = tiles_0 = t_end = None
    measure_start_unix_ns = None

    while True:
        while battery.on_battery():
            log('benchmark paused on battery; reconnect AC to continue')
            time.sleep(2)
        now = time.monotonic()
        if t_measure_0 is None and now >= t_warm_end:
            t_measure_0, tiles_0 = now, tiles
            measure_start_unix_ns = time.time_ns()
            t_end = now + seconds
        if t_end is not None and now >= t_end:
            break
        _, n = engine.sweep_region(row_cursor, args.region_rows,
                                   grid.a_seed, bound)
        tiles += n
        row_cursor += 1
        if row_cursor >= n_regions:  # same rebuild cadence as live mining
            grid = factory.take(job)
            factory.request(job)
            engine.load_grid(grid)
            row_cursor = 0

    dt = time.monotonic() - t_measure_0
    rate = (tiles - tiles_0) / dt
    print('BENCHMARK_JSON ' + json.dumps({'measure_start_monotonic': t_measure_0,
        'measure_start_unix_ns': measure_start_unix_ns,
        'measure_end_monotonic': t_measure_0 + dt, 'measured_tiles': tiles - tiles_0,
        'measured_seconds': dt, 'tiles_per_second': rate, 'difficulty_factor': factor,
        'equivalent_hashes_per_second': rate * factor,
        'warmup_seconds_requested': warmup,
        'scope': 'offline returned scans including grid preparation; no pool proof or network'}), flush=True)
    macos = platform.mac_ver()[0] or "unknown"
    today = datetime.date.today().isoformat()
    log(f"measured {rate / 1e6:.3f}M tiles/s over {dt:.0f}s on "
        f"{engine.device_name} ({power})")
    # The community-hardware-table contract (the README table's columns):
    print(f"""
paste-ready for the community hardware table
(https://github.com/parkerkyle-max/pearl-m-miner — benchmark reports issue):

| chip | macOS | tiles/s | intensity | power | version | date |
| ---- | ----- | ------- | --------- | ----- | ------- | ---- |
| {engine.device_name} | {macos} | {rate / 1e6:.3f}M | 100 | {power} | {__version__} | {today} |
""")
    return 0
