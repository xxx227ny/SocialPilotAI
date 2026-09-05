import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.services.production_batch_lock import serialized_batch_control


def test_concurrent_batch_controls_are_serialized_and_exception_releases(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lock.db'}")
    barrier = Barrier(2)
    active = []
    overlapping = []

    class Control:
        def __init__(self, session):
            self.session = session

        @serialized_batch_control
        def advance(self, product_id, batch_id, fail=False):
            if active:
                overlapping.append(True)
            active.append(True)
            try:
                time.sleep(0.05)
                if fail:
                    raise RuntimeError("test failure")
            finally:
                active.pop()

    def run(fail):
        with Session(engine) as session:
            barrier.wait()
            try:
                Control(session).advance(1, 1, fail=fail)
            except RuntimeError:
                assert fail

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, [True, False]))
    assert not overlapping
    with Session(engine) as session:
        Control(session).advance(1, 1)
    engine.dispose()
