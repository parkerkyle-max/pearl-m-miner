"""Public macOS thermal pressure guard and completed-scan accounting."""
import json
import math
import os
import time


class BatteryPoller:
    """Cache process-based battery queries outside the scan hot path.

    While on AC, unplug detection is bounded by 20 seconds. During a pause,
    poll every two seconds so reconnecting AC resumes promptly.
    """
    def __init__(self, read_source, *, initial=None, clock=time.monotonic):
        self.read_source = read_source
        self.clock = clock
        self.source = initial
        self.next_poll = clock() + (2 if initial == 'battery' else 20) if initial else -math.inf

    def on_battery(self):
        now = self.clock()
        if now >= self.next_poll:
            self.source = self.read_source()
            self.next_poll = now + (2 if self.source == 'battery' else 20)
        return self.source == 'battery'


def event(kind, **values):
    values['session'] = os.environ.get('PEARL_M_SESSION', '')
    print(kind + ' ' + json.dumps(values, separators=(',', ':')), flush=True)


def activity(seconds, tiles):
    if not math.isfinite(seconds) or seconds < 0 or type(tiles) is not int or tiles <= 0:
        raise RuntimeError('invalid completed-scan accounting')
    if os.environ.get('PEARL_M_ACTIVITY') == '1':
        event('PMM_ACTIVITY', seconds=seconds, tiles=tiles)


def wait_until_safe(read_state, *, sleep=time.sleep):
    """0 nominal / 1 fair proceed; 2 serious / 3 critical pause.

    This is the public OS pressure signal, not a degree-C temperature sensor.
    Read errors fail closed. Signals remain interruptible while paused.
    """
    paused = False
    while True:
        value = read_state()
        if type(value) is not int or value not in (0, 1, 2, 3):
            raise RuntimeError('cannot read a valid macOS thermal pressure state')
        if value < 2:
            if paused:
                event('PMM_STATE', state='ready', reason='thermal-recovered')
            return
        if not paused:
            event('PMM_STATE', state='paused', reason='thermal', pressure=value)
            paused = True
        sleep(2)
