"""The CPU cap must really reach the kernel: a fresh python that calls
procutil.limit_cpu() reports an affinity mask of the first N cores and
BelowNormal priority when read back. Until 2026-09-06 ctypes truncated the
GetCurrentProcess() pseudo handle to 32 bits, every call on it failed
silently and the whole server tree ran uncapped while logging
"cpu-limited to 4 core(s)"."""
import json
import os
import subprocess
import sys

import pytest

from crystalpilot import procutil

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows job/affinity API")

CHILD = """
import json, os
os.environ['CRYSTALPILOT_CPU_CORES'] = '2'
from crystalpilot import procutil
note = procutil.limit_cpu()
print(json.dumps({'note': note, 'state': procutil.cpu_state()}))
"""


def test_limit_cpu_is_visible_to_the_kernel():
    out = subprocess.run([sys.executable, "-X", "utf8", "-c", CHILD],
                         capture_output=True, text=True, timeout=120, check=True,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    rep = json.loads(out.stdout.strip().splitlines()[-1])
    assert rep["note"] == "cpu-limited to 2 core(s) at BelowNormal", rep
    assert rep["state"]["affinity_mask"] == 0b11
    assert rep["state"]["priority_class"] == procutil.BELOW_NORMAL_PRIORITY_CLASS


def test_cpu_state_reads_this_process():
    st = procutil.cpu_state()
    assert st is not None
    assert st["affinity_mask"] and st["system_mask"]
    assert st["affinity_mask"] & st["system_mask"] == st["affinity_mask"]


def test_zero_cores_disables_the_cap(monkeypatch):
    monkeypatch.setenv("CRYSTALPILOT_CPU_CORES", "0")
    assert procutil.limit_cpu() is None
