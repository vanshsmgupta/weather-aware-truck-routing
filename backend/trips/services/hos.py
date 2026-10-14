"""Simplified FMCSA property-carrier hours of service: 11 h driving, a 30 min break
after 8 h behind the wheel, then a 10 h off-duty reset."""

import math

DRIVING_LIMIT_S = 11 * 3600
BREAK_AFTER_S = 8 * 3600
BREAK_S = 30 * 60
REST_S = 10 * 3600


def elapsed(drive_s, enabled=True):
    """Wall-clock seconds since departure after `drive_s` seconds of driving."""
    if not enabled or drive_s <= 0:
        return max(drive_s, 0.0)
    finished_shifts = math.ceil(drive_s / DRIVING_LIMIT_S) - 1
    into_shift = drive_s - finished_shifts * DRIVING_LIMIT_S
    total = drive_s + finished_shifts * (BREAK_S + REST_S)
    if into_shift > BREAK_AFTER_S:
        total += BREAK_S
    return total


def stops(total_drive_s, enabled=True):
    """(kind, driving seconds when the stop starts, stop length) for every stop before arrival."""
    if not enabled:
        return []
    result = []
    shift_start = 0
    while True:
        break_at = shift_start + BREAK_AFTER_S
        rest_at = shift_start + DRIVING_LIMIT_S
        if break_at < total_drive_s:
            result.append(("break", break_at, BREAK_S))
        if rest_at < total_drive_s:
            result.append(("rest", rest_at, REST_S))
        else:
            return result
        shift_start = rest_at
