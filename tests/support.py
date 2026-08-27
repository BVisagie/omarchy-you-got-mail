"""Shared helpers for mocked contract tests. No live mailboxes."""

from __future__ import annotations

import json
import sys
import types
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "lib"
PROVIDERS = ROOT / "providers"

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))
if str(PROVIDERS) not in sys.path:
    sys.path.insert(0, str(PROVIDERS))


def load_provider(name: str):
    path = PROVIDERS / name
    source = path.read_text(encoding="utf-8")
    module = types.ModuleType(f"ygm_provider_{name}")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def capture_json(fn, *args, **kwargs) -> dict:
    buf = StringIO()
    with redirect_stdout(buf):
        try:
            fn(*args, **kwargs)
        except SystemExit:
            pass
    text = buf.getvalue().strip()
    if not text:
        raise AssertionError("expected JSON on stdout")
    return json.loads(text.splitlines()[-1])


def message(local_id: str, ts: int, subject: str = "Hello") -> dict:
    return {
        "id": local_id,
        "threadId": local_id,
        "subject": subject,
        "from": "Ada",
        "snippet": "First line",
        "ts": ts,
        "labels": [],
        "url": "https://mail.example.test/m/" + local_id,
    }
