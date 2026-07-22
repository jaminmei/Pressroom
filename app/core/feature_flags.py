from __future__ import annotations

import os
from enum import Enum


class OrchestratorMode(str, Enum):
    SERIAL = "serial"
    QUEUE = "queue"


class FeatureFlags:
    @staticmethod
    def get_orchestrator_mode() -> OrchestratorMode:
        raw_mode = os.getenv("ORCHESTRATOR_MODE")
        if raw_mode is not None and raw_mode.strip():
            return OrchestratorMode(raw_mode.strip().lower())

        queue_toggle = os.getenv("ENABLE_QUEUE_MODE")
        if queue_toggle is not None:
            normalized = queue_toggle.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return OrchestratorMode.QUEUE
            if normalized in {"0", "false", "no", "off", ""}:
                return OrchestratorMode.SERIAL
            raise ValueError(f"Invalid ENABLE_QUEUE_MODE value: {queue_toggle}")

        return OrchestratorMode.SERIAL

    @staticmethod
    def is_queue_mode() -> bool:
        return FeatureFlags.get_orchestrator_mode() == OrchestratorMode.QUEUE
