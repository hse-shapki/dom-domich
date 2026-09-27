"""Узкий адаптер K RequestService к типизированной команде demo executor."""

from dataclasses import dataclass
from uuid import UUID

from dom_domych.application.executor.service import DemoExecutorService
from dom_domych.domain.executor.models import ApprovedDraft, DemoOperation, ExecutorForbidden


@dataclass(frozen=True)
class _SubmitContext:
    house_id: UUID
    capabilities: frozenset[str] = frozenset({"demo_executor.submit"})


class DemoSubmitAdapter:
    def __init__(self, executor: DemoExecutorService) -> None:
        self.executor = executor

    async def submit(
        self, draft: ApprovedDraft, operation_key: str, house_id: UUID
    ) -> DemoOperation:
        if draft.house_id != house_id:
            raise ExecutorForbidden("draft belongs to another house")
        return await self.executor.submit(draft, operation_key, _SubmitContext(house_id))
