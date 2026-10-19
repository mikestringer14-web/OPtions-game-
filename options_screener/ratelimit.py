"""IBKR historical-data pacing (interactivebrokers.github.io/tws-api/historical_limitations.html):

  * max 50 simultaneous open historical requests
  * no identical request within 15 seconds
  * no 6+ requests for the same contract/exchange/tick type within 2 seconds
  * no more than 60 requests in any 10 minutes (bars of 30 seconds or less)
  * BID_ASK requests count twice
  * bars of 1 minute and larger have a softer server-side throttle, so we still apply the
    60-per-10-minutes budget to everything by default (configurable).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class PacingLimiter:
    def __init__(self, max_per_window: int = 60, window_s: float = 600.0, identical_gap_s: float = 15.0,
                 same_contract_max: int = 5, same_contract_window_s: float = 2.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.max_per_window, self.window_s = max_per_window, window_s
        self.identical_gap_s = identical_gap_s
        self.same_contract_max, self.same_contract_window_s = same_contract_max, same_contract_window_s
        self.clock, self.sleep = clock, sleep
        self._all: deque = deque()                 # timestamps (one entry per counted unit)
        self._by_contract: dict = {}
        self._last_identical: dict = {}
        self._lock = threading.Lock()

    def _wait_needed(self, now: float, contract_key: str, request_key: str, weight: int) -> float:
        waits = [0.0]
        while self._all and now - self._all[0] >= self.window_s:
            self._all.popleft()
        if len(self._all) + weight > self.max_per_window:
            idx = len(self._all) + weight - self.max_per_window - 1
            waits.append(self._all[idx] + self.window_s - now)
        q = self._by_contract.setdefault(contract_key, deque())
        while q and now - q[0] >= self.same_contract_window_s:
            q.popleft()
        if len(q) + 1 > self.same_contract_max:
            waits.append(q[0] + self.same_contract_window_s - now)
        last = self._last_identical.get(request_key)
        if last is not None and now - last < self.identical_gap_s:
            waits.append(last + self.identical_gap_s - now)
        return max(waits)

    def acquire(self, contract_key: str, request_key: str, what_to_show: str = "TRADES") -> float:
        """Block until the request is allowed. Returns seconds waited."""
        weight = 2 if what_to_show.upper() == "BID_ASK" else 1
        waited = 0.0
        while True:
            with self._lock:
                now = self.clock()
                wait = self._wait_needed(now, contract_key, request_key, weight)
                if wait <= 0:
                    for _ in range(weight):
                        self._all.append(now)
                    self._by_contract[contract_key].append(now)
                    self._last_identical[request_key] = now
                    return waited
            self.sleep(wait)
            waited += wait
