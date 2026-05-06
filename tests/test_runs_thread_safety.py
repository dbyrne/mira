"""Regression tests for the thread-safety claims added to RunRecord.

The webapp polls `record.result["frames"]` while a background thread is
appending to that same list (and to `record.log_lines`). Before batch Y,
`to_dict()` could observe a torn list mid-append, which would either
corrupt the persisted JSON or surface to the polling template as a
half-rendered table.

These tests stress the lock and snapshot logic by hammering the record
from a writer thread while a reader thread snapshots, and check that
every snapshot is internally consistent.
"""
from __future__ import annotations

import json
import threading
import time
from unittest import TestCase

from anomaly_scout.webapp.runs import RunRecord, _deep_snapshot


class DeepSnapshotTests(TestCase):
    def test_dict_is_copied(self) -> None:
        original = {"a": [1, 2, 3], "b": {"c": 4}}
        snapshot = _deep_snapshot(original)
        snapshot["a"].append(99)
        snapshot["b"]["c"] = 0
        self.assertEqual(original["a"], [1, 2, 3])
        self.assertEqual(original["b"]["c"], 4)

    def test_list_is_copied(self) -> None:
        original = [1, [2, 3], {"k": "v"}]
        snapshot = _deep_snapshot(original)
        snapshot.append(99)
        snapshot[1].append(99)
        snapshot[2]["k"] = "x"
        self.assertEqual(original, [1, [2, 3], {"k": "v"}])

    def test_tuple_is_copied(self) -> None:
        original = (1, [2, 3], (4, 5))
        snapshot = _deep_snapshot(original)
        self.assertEqual(snapshot, original)
        # Mutating the inner list in the snapshot doesn't affect original
        snapshot[1].append(99)
        self.assertEqual(original[1], [2, 3])

    def test_scalars_pass_through(self) -> None:
        self.assertIsNone(_deep_snapshot(None))
        self.assertEqual(_deep_snapshot(42), 42)
        self.assertEqual(_deep_snapshot("hi"), "hi")
        self.assertEqual(_deep_snapshot(3.14), 3.14)


class RunRecordSnapshotConcurrencyTests(TestCase):
    def test_snapshot_never_observes_torn_frames_list(self) -> None:
        """Drive a writer that appends 1000 dicts to record.result['frames']
        while a reader snapshots repeatedly. Each snapshot must contain
        consistent monotonically-increasing entries — proves to_dict's
        deep_snapshot took a coherent view under the lock."""
        record = RunRecord(run_id="r1", kind="submit:X", label="test")
        record.result = {"frames": []}
        stop_writing = threading.Event()
        writer_done = threading.Event()
        snapshots: list[list[dict]] = []
        snapshot_errors: list[str] = []
        N = 500

        def writer():
            for i in range(N):
                # Mutate under the lock to match production code (Y batch).
                record.update_result(
                    lambda r, idx=i: {**r, "frames": r["frames"] + [{"idx": idx}]}
                )
                # Tiny yield so the reader thread gets time slices
                if i % 50 == 0:
                    time.sleep(0)
            writer_done.set()

        def reader():
            while not writer_done.is_set():
                snap = record.to_dict()
                frames = snap["result"]["frames"]
                # Indices in any snapshot must form a contiguous prefix
                for j, frame in enumerate(frames):
                    if frame["idx"] != j:
                        snapshot_errors.append(
                            f"index {j} in snapshot is {frame['idx']}, expected {j}"
                        )
                        break
                snapshots.append(frames)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(snapshot_errors, [], "torn snapshot detected")
        # And the final state should hold all N entries
        final = record.to_dict()
        self.assertEqual(len(final["result"]["frames"]), N)

    def test_to_dict_serializable_under_load(self) -> None:
        """to_dict's snapshot must always be json-serializable. If it was
        a shallow copy, json.dumps could iterate a list mid-append and
        raise RuntimeError: list changed during iteration."""
        record = RunRecord(run_id="r2", kind="submit:Y", label="test2")
        record.result = {"frames": [], "observations": []}
        writer_done = threading.Event()

        def writer():
            for i in range(300):
                record.update_result(
                    lambda r, idx=i: {
                        "frames": r["frames"] + [{"i": idx}],
                        "observations": r["observations"] + [{"jd": idx}],
                    }
                )
            writer_done.set()

        def reader():
            errors = 0
            while not writer_done.is_set():
                try:
                    json.dumps(record.to_dict())
                except (TypeError, ValueError, RuntimeError):
                    errors += 1
            return errors

        writer_thread = threading.Thread(target=writer)
        # We can't easily get the reader's return value from a Thread; track
        # via a list closure.
        results: list[int] = []
        def run_reader() -> None:
            results.append(reader())
        reader_thread = threading.Thread(target=run_reader)

        writer_thread.start()
        reader_thread.start()
        writer_thread.join(timeout=10)
        reader_thread.join(timeout=10)

        self.assertEqual(results, [0], "json.dumps saw a torn structure")


class UpdateResultAtomicityTests(TestCase):
    def test_concurrent_appenders_dont_lose_writes(self) -> None:
        """100 threads each appending one frame; after all threads finish,
        the list must contain exactly 100 unique items. A non-atomic
        ``record.result['frames'].append`` followed by re-assignment would
        lose writes that read a stale frames list."""
        record = RunRecord(run_id="r3", kind="submit:Z", label="atomic")
        record.result = {"frames": []}

        def append_one(idx: int) -> None:
            record.update_result(
                lambda r, i=idx: {**r, "frames": r["frames"] + [i]}
            )

        threads = [threading.Thread(target=append_one, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        frames = record.result["frames"]
        self.assertEqual(len(frames), 100)
        self.assertEqual(set(frames), set(range(100)))
