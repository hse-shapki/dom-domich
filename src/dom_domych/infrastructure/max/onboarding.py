"""Команды регистрации в личном MAX-чате; ответы идут после commit."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dom_domych.application.residents.enrollment import (
    DemoEnrollmentService,
    EnrollmentDenied,
    HouseSelection,
)
from dom_domych.contracts.events import EventEnvelope, EventName, EventSource
from dom_domych.domain.ports.core import Clock
from dom_domych.infrastructure.max.client import MaxApiClient
from dom_domych.infrastructure.postgres.enrollment import PostgresEnrollment


class MaxOnboardingHandler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        max_client: MaxApiClient,
        clock: Clock,
    ) -> None:
        self.sessions = sessions
        self.max_client = max_client
        self.clock = clock

    async def handle(self, event: EventEnvelope) -> bool:
        if event.source is not EventSource.MAX:
            return False
        if event.name in {EventName.BOT_STARTED, EventName.BOT_STOPPED}:
            lifecycle = event.lifecycle
            if lifecycle is None:
                return False
            async with self.sessions.begin() as session:
                service = DemoEnrollmentService(PostgresEnrollment(session), self.clock)
                if event.name is EventName.BOT_STOPPED:
                    await service.bot_stopped(lifecycle.user_id)
                    return True
                await service.bot_started(lifecycle.user_id)
                selection = await service.current_house(lifecycle.user_id)
            await self.max_client.send_text(
                self._status_text(selection), user_id=int(lifecycle.user_id)
            )
            return True
        if event.name is not EventName.MESSAGE_RECEIVED or event.message is None:
            return False
        message = event.message
        if message.chat_id != f"dm:{message.sender_user_id}" or not message.text:
            return False
        parts = message.text.strip().split(maxsplit=1)
        if not parts or parts[0].lower() not in {"/start", "/house"}:
            return False
        async with self.sessions.begin() as session:
            service = DemoEnrollmentService(PostgresEnrollment(session), self.clock)
            try:
                if parts[0].lower() == "/start" and len(parts) == 2:
                    result = await service.redeem(parts[1], message.sender_user_id)
                    reply = (
                        f"Квартира подтверждена: подъезд {result.entrance}, этаж {result.floor}. "
                        "Теперь можно писать о проблеме."
                    )
                elif parts[0].lower() == "/house" and len(parts) == 2:
                    selection = await service.current_house(message.sender_user_id)
                    index = int(parts[1]) - 1
                    if index < 0 or index >= len(selection.available_house_ids):
                        raise EnrollmentDenied("unknown house choice")
                    selected = await service.choose_house(
                        message.sender_user_id, selection.available_house_ids[index]
                    )
                    reply = self._status_text(selected)
                else:
                    selection = await service.current_house(message.sender_user_id)
                    reply = self._status_text(selection)
            except (EnrollmentDenied, ValueError):
                reply = "Код или выбор дома не подошёл. Проверьте данные и попробуйте ещё раз."
        await self.max_client.send_text(reply, user_id=int(message.sender_user_id))
        return True

    @staticmethod
    def _status_text(selection: HouseSelection) -> str:
        if not selection.available_house_ids:
            return "Для подтверждения квартиры введите /start <код от администратора дома>."
        if selection.selected_house_id is not None:
            return "Квартира подтверждена. Напишите о проблеме дома обычным сообщением."
        choices = "\n".join(
            f"{index}. Дом {house_id}"
            for index, house_id in enumerate(selection.available_house_ids, 1)
        )
        return f"Выберите дом командой /house <номер>:\n{choices}"
