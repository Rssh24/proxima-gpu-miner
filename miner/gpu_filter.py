"""Pure host-side filtering of 64-byte GPU VRF outputs.

This module does no VRF calculation and opens no files or devices. A passing
record still needs the current beat comparison and the independent official
oracle check before a mining result can be submitted.
"""

from collections.abc import Iterator


def candidate_indices(data: bytes | bytearray, k: int) -> Iterator[int]:
    """Yield aligned record indices with at least ``k`` trailing zero bits.

    ``data`` must contain complete consecutive 64-byte records. For complete
    zero suffix bytes, ``bytes.find`` does the large scan in native code; the
    Python loop checks record alignment and any remaining low-order bits.
    Indices are yielded once, in ascending order. No records are copied.
    """
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError('data must be bytes or bytearray')
    if type(k) is not int:
        raise TypeError('k must be an integer')
    if not 0 <= k <= 512:
        raise ValueError('k must be between 0 and 512')
    if len(data) % 64:
        raise ValueError('data length must be a multiple of 64')

    count = len(data) // 64
    if k == 0:
        yield from range(count)
        return

    whole, remaining = divmod(k, 8)
    mask = (1 << remaining) - 1
    if whole == 0:
        for index in range(count):
            if data[(index + 1) * 64 - 1] & mask == 0:
                yield index
        return

    needle = b'\x00' * whole
    search_from = 0
    while True:
        found = data.find(needle, search_from)
        if found < 0:
            return
        end = found + whole
        # Include overlapping occurrences: a zero run can cross boundaries.
        search_from = found + 1
        if end % 64:
            continue
        if remaining and data[found - 1] & mask:
            continue
        yield end // 64 - 1


def selftest(seed: int = 0x9070255) -> dict[str, int]:
    """Compare every K to the original big-integer definition on test data."""
    import random

    rng = random.Random(seed)

    def random_bytes(length: int) -> bytes:
        return bytes(rng.getrandbits(8) for _ in range(length))

    def original_trailing(beta: bytes | bytearray) -> int:
        number = int.from_bytes(beta, 'big')
        return 512 if number == 0 else (number & -number).bit_length() - 1

    def reference(data: bytes | bytearray, k: int) -> list[int]:
        return [index for index in range(len(data) // 64)
                if original_trailing(data[index * 64:(index + 1) * 64]) >= k]

    # Each possible exact trailing-bit count, including a full zero record.
    planted = bytearray()
    for bits in range(513):
        record = bytearray(random_bytes(64))
        whole, remaining = divmod(bits, 8)
        if whole:
            record[64 - whole:] = b'\x00' * whole
        if bits < 512:
            position = 63 - whole
            record[position] &= 255 ^ ((1 << remaining) - 1)
            record[position] |= 1 << remaining
        assert original_trailing(record) == bits
        planted.extend(record)

    crossing = bytearray(b'\xa5' * (64 * 7))
    crossing[7:211] = b'\x00' * 204
    crossing[319:385] = b'\x00' * 66
    # Zero runs ending away from record boundaries must not be mistaken for
    # complete trailing suffixes; adjacent full-zero records test overlaps.
    datasets = [
        b'', b'\x00' * 64, b'\xff' * 64, b'\x00' * 128,
        bytes(crossing), bytes(planted),
        (b'\x00' * 63 + b'\xff') * 5,
    ]
    datasets.extend(random_bytes(count * 64) for count in (1, 2, 7, 64, 129, 257))
    comparisons = 0
    for dataset in datasets:
        for k in range(513):
            expected = reference(dataset, k)
            for representation in (dataset, bytearray(dataset)):
                actual = list(candidate_indices(representation, k))
                assert actual == expected, ('candidate mismatch', len(dataset), k)
                comparisons += 1

    invalid_cases = [
        (b'\x00', 0, ValueError), (b'\x00' * 63, 8, ValueError),
        (b'\x00' * 65, 512, ValueError), (b'\x00' * 127, 32, ValueError),
        (b'', -1, ValueError), (b'', 513, ValueError),
        (b'', True, TypeError), (b'', 32.0, TypeError), (b'', '32', TypeError),
        ('', 0, TypeError), (None, 32, TypeError),
        (memoryview(b'\x00' * 64), 32, TypeError),
    ]
    for data, k, expected_error in invalid_cases:
        try:
            list(candidate_indices(data, k))
        except expected_error:
            pass
        else:
            raise AssertionError('invalid input was accepted')

    return {'datasets': len(datasets), 'k_values': 513,
            'comparisons': comparisons, 'invalid_cases': len(invalid_cases)}


if __name__ == '__main__':
    print('GPU output filter selftest passed:', selftest())
