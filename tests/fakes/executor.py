"""Транзакционный fake для проверки контракта DemoExecutorService."""

import asyncio
from datetime import datetime
from uuid import UUID

from dom_domych.domain.executor.models import (
    DemoOperation,
    ExecutorConflict,
    ExecutorNotFound,
    ExternalStatus,
)


class FakeExecutorStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_id: dict[UUID, DemoOperation] = {}
        self._by_operation_key: dict[tuple[UUID, str], UUID] = {}
        self._by_request: dict[tuple[UUID, UUID], UUID] = {}
        self.events: list[tuple[str, UUID]] = []

    async def submit_once(self, operation: DemoOperation) -> DemoOperation:
        async with self._lock:
            key = (operation.draft.house_id, operation.operation_key)
            existing_id = self._by_operation_key.get(key)
            if existing_id is not None:
                existing = self._by_id[existing_id]
                if existing.draft != operation.draft:
                    raise ExecutorConflict("operation key was used for another draft")
                return existing
            request_key = (operation.draft.house_id, operation.draft.request_id)
            if request_key in self._by_request:
                raise ExecutorConflict("request already has a demo submission")
            self._by_operation_key[key] = operation.operation_id
            self._by_request[request_key] = operation.operation_id
            self._by_id[operation.operation_id] = operation
            self.events.append(("request.submitted", operation.operation_id))
            return operation

    async def register_atomic(
        self, house_id: UUID, operation_id: UUID, at: datetime
    ) -> tuple[DemoOperation, bool]:
        async with self._lock:
            current = self._get_operation(house_id, operation_id)
            changed, emitted = current.register(at)
            if emitted:
                self._by_id[operation_id] = changed
                self.events.append(("request.registered", operation_id))
            return changed, emitted

    async def change_status_atomic(
        self,
        house_id: UUID,
        operation_id: UUID,
        status: ExternalStatus,
        at: datetime,
        source_event_id: UUID,
    ) -> tuple[DemoOperation, bool]:
        async with self._lock:
            current = self._get_operation(house_id, operation_id)
            changed, emitted = current.change_status(status, at, source_event_id)
            if emitted:
                self._by_id[operation_id] = changed
                self.events.append(("request.status_changed", operation_id))
            return changed, emitted

    async def get(self, house_id: UUID, request_id: UUID) -> DemoOperation:
        async with self._lock:
            for operation in self._by_id.values():
                if (
                    operation.draft.house_id == house_id
                    and operation.draft.request_id == request_id
                ):
                    return operation
            raise ExecutorNotFound("request is not registered for this house")

    def _get_operation(self, house_id: UUID, operation_id: UUID) -> DemoOperation:
        operation = self._by_id.get(operation_id)
        if operation is None or operation.draft.house_id != house_id:
            raise ExecutorNotFound("operation is not available for this house")
        return operation
