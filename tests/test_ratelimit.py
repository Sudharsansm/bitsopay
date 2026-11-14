import pytest

from bitsopay.ratelimit import FailureLimiter


def test_blocks_after_max_failures_then_recovers(clock):
    lim = FailureLimiter(3, 60, clock=clock)
    for _ in range(2):
        lim.record_failure("ip")
    assert lim.retry_after("ip") == 0
    lim.record_failure("ip")
    assert 1 <= lim.retry_after("ip") <= 61
    assert lim.retry_after("other") == 0
    clock.t += 61
    assert lim.retry_after("ip") == 0


def test_reset_clears_failures(clock):
    lim = FailureLimiter(1, 60, clock=clock)
    lim.record_failure("ip")
    assert lim.retry_after("ip") > 0
    lim.reset("ip")
    assert lim.retry_after("ip") == 0


def test_memory_is_bounded(clock):
    lim = FailureLimiter(5, 60, clock=clock, max_keys=3)
    for i in range(10):
        lim.record_failure(f"ip{i}")
    assert len(lim._hits) <= 3
    clock.t += 120  # everything expired: stale keys are dropped first
    lim.record_failure("fresh")
    assert set(lim._hits) == {"fresh"}


@pytest.mark.parametrize(("failures", "window"), [(0, 60), (1, 0)])
def test_rejects_bad_config(failures, window):
    with pytest.raises(ValueError, match="max_failures"):
        FailureLimiter(failures, window)
