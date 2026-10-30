"""Exact compact-target brackets for offline proof fixtures.

The supplied encode/decode functions are the pinned miner reference functions.
This module does not implement hashing, alter proofs or relax their acceptance.
"""


def ceil_compact_target(target, encode, decode):
    """Smallest positive compact target >= an integer target.

    Bitcoin-style compact encoding floors to an exponent-dependent unit. A
    relative epsilon is insufficient: sign-bit normalization can leave only16
    significant mantissa bits. Advance one exact unit from the floor instead.
    """
    if type(target) is not int or target <= 0:
        raise ValueError('ceil compact target must be a positive integer')
    compact = encode(target)
    floor = decode(compact)
    if not 0 < floor <= target:
        raise ValueError('compact encoder did not return a positive floor')
    if floor == target:
        return compact
    exponent = compact >> 24
    unit = 1 << max(0, 8 * (exponent - 3))
    rounded = encode(floor + unit)
    ceiling = decode(rounded)
    if not target <= ceiling or ceiling != floor + unit:
        raise ValueError('compact ceiling failed exact unit/roundtrip validation')
    return rounded


def proof_target_bracket(value, factor, encode, decode):
    """Return compact bounds strictly below and above a nonzero digest.

    Verifier comparison is against decoded base_target * factor. Requiring a
    strict upper bracket also avoids depending on its equality convention.
    A zero digest has no nonnegative lower bracket and is explicitly refused.
    """
    if type(value) is not int or value <= 0 or type(factor) is not int or factor <= 0:
        raise ValueError('bracket requires positive integer digest and factor')
    low = encode((value - 1) // factor)
    high = ceil_compact_target(value // factor + 1, encode, decode)
    if not 0 <= decode(low) * factor < value < decode(high) * factor:
        raise ValueError('compact proof bracket failed decoded endpoint validation')
    return low, high
