"""SQLite checkpoint boundary for LangGraph graph state."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


class ExecutionCheckpoint:
    """Own one SQLite connection separate from the Runtime Ledger."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
        )
        self.saver = SqliteSaver(self.connection)

    def close(self) -> None:
        self.connection.close()
