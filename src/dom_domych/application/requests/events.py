"""K13: проверка данных Z перед изменением request/case и продолжением агента."""

from typing import Protocol

from dom_domych.application.jobs.inbox_worker import EventDispatcher
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import DocumentPort, DocumentRef, ExecutorPort, RequestRef


class RequestEventStore(Protocol):
    async def record_external_status(
        self, event: EventEnvelope, external: RequestRef
    ) -> object: ...

    async def bind_document(self, event: EventEnvelope, document: DocumentRef) -> object: ...


class RequestEventHandler:
    """Возвращает False, чтобы следующий handler увидел уже записанное состояние."""

    def __init__(
        self,
        executor: ExecutorPort,
        documents: DocumentPort,
        store: RequestEventStore,
    ) -> None:
        self.executor = executor
        self.documents = documents
        self.store = store

    async def __call__(self, event: EventEnvelope) -> bool:
        if event.house_id is None or event.entity is None:
            raise ValueError("CONTINUATION_CONTEXT_MISSING")
        if event.name is EventName.REQUEST_STATUS_CHANGED:
            if event.source is not EventSource.EXECUTOR or event.entity.case_id is None:
                raise ValueError("UNTRUSTED_REQUEST_STATUS_EVENT")
            external = await self.executor.get_status(event.entity.entity_id, event.house_id)
            await self.store.record_external_status(event, external)
            return False
        if event.name is EventName.DOCUMENT_READY:
            if event.source is not EventSource.DOMAIN or event.entity.case_id is None:
                raise ValueError("UNTRUSTED_DOCUMENT_EVENT")
            document = await self.documents.get(event.entity.entity_id, event.house_id)
            if document is None:
                raise ValueError("DOCUMENT_NOT_FOUND")
            await self.store.bind_document(event, document)
            return False
        return False


def register_request_events(dispatcher: EventDispatcher, handler: RequestEventHandler) -> None:
    """Регистрируется до agent handlers, чтобы prompt видел уже сохранённое состояние."""

    dispatcher.register(EventName.REQUEST_STATUS_CHANGED, handler)
    dispatcher.register(EventName.DOCUMENT_READY, handler)
