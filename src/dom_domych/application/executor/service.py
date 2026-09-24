"""Типизированные команды моделируемого исполнителя."""

from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from dom_domych.domain.executor.models import (
    ApprovedDraft,
    DemoOperation,
    ExecutorForbidden,
    ExternalStatus,
)


class TrustedExecutorContext(Protocol):
    @property
    def house_id(self) -> UUID: ...

    @property
    def capabilities(self) -> frozenset[str]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class ExecutorStore(Protocol):
    async def submit_once(self, operation: DemoOperation) -> DemoOperation:
        """Атомарно фиксирует operation key и submitted event."""
        ...

    async def register_atomic(
        self, house_id: UUID, operation_id: UUID, at: datetime
    ) -> tuple[DemoOperation, bool]:
        """Фиксирует номер/время и request.registered единожды."""
        ...

    async def change_status_atomic(
        self,
        house_id: UUID,
        operation_id: UUID,
        status: ExternalStatus,
        at: datetime,
        source_event_id: UUID,
    ) -> tuple[DemoOperation, bool]:
        """Под lock применяет status transition и событие единожды."""
        ...

    async def get(self, house_id: UUID, request_id: UUID) -> DemoOperation: ...


class DemoExecutorService:
    """Статус внешнего исполнителя не меняет workflow_status и не закрывает дело."""

    def __init__(self, store: ExecutorStore, clock: Clock) -> None:
        self.store = store
        self.clock = clock

    async def submit(
        self,
        draft: ApprovedDraft,
        operation_key: str,
        context: TrustedExecutorContext,
    ) -> DemoOperation:
        self._require(context, "demo_executor.submit")
        if draft.house_id != context.house_id:
            raise ExecutorForbidden("draft belongs to another house")
        if not operation_key:
            raise ValueError("operation key is required")
        return await self.store.submit_once(
            DemoOperation(
                operation_id=uuid4(),
                operation_key=operation_key,
                draft=draft,
                status=ExternalStatus.SUBMITTED,
                submitted_at=self.clock.now(),
            )
        )

    async def register(
        self, operation_id: UUID, context: TrustedExecutorContext
    ) -> tuple[DemoOperation, bool]:
        self._require(context, "demo_executor.register")
        return await self.store.register_atomic(
            context.house_id, operation_id, self.clock.now()
        )

    async def set_status(
        self,
        operation_id: UUID,
        status: ExternalStatus,
        source_event_id: UUID,
        context: TrustedExecutorContext,
    ) -> tuple[DemoOperation, bool]:
        self._require(context, "demo_executor.operator")
        return await self.store.change_status_atomic(
            context.house_id, operation_id, status, self.clock.now(), source_event_id
        )

    async def get_status(
        self, request_id: UUID, context: TrustedExecutorContext
    ) -> DemoOperation:
        return await self.store.get(context.house_id, request_id)

    @staticmethod
    def _require(context: TrustedExecutorContext, capability: str) -> None:
        if capability not in context.capabilities:
            raise ExecutorForbidden("demo executor capability is required")
