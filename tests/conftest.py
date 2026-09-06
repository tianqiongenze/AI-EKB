import os

import pytest


@pytest.fixture(autouse=True)
def _restore_environ():
    """Snapshot os.environ around each test.

    Several tests mutate process env directly (EKB_AUTH_TOKEN, EKB_ENV, ...);
    restoring afterwards keeps test order from leaking configuration into
    sibling tests.
    """
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)
