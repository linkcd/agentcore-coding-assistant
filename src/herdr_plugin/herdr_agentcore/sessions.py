"""Session use cases shared by CLI and interactive menus, without UI dependencies."""

from .agentcore import AgentCoreError, AgentCoreTransport
from .connector import Connector
from .models import ConnectionRecord, ConnectionStatus, UserError
from .storage import Store


class SessionService:
    def __init__(self, store: Store, transport_factory=AgentCoreTransport):
        self.store = store
        self.transport_factory = transport_factory

    def create(self, profile: str | None = None, name: str | None = None) -> ConnectionRecord:
        return self.store.create_record(profile, name)

    @staticmethod
    def validate_reconnect(seconds: int):
        if not 0 <= seconds <= 900:
            raise UserError("--reconnect-seconds must be between 0 and 900.")

    def available(self, *, for_stop=False) -> list[ConnectionRecord]:
        return [
            record
            for record in self.store.connection_records()
            if (record.status != ConnectionStatus.STOPPED if for_stop else record.status.attachable)
        ]

    def stop(self, identifier: str) -> ConnectionRecord | None:
        with self.store.lock(identifier):
            record = self.store.load_record(identifier)
            if record.status == ConnectionStatus.STOPPED:
                return None
            try:
                self.transport_factory(record.profile).stop(record.to_dict())
            except AgentCoreError as exc:
                raise UserError(f"Stop failed ({exc.code}); no local status was changed.") from exc
            # Preserve the v1 acknowledgement label; this is not a stop-completion waiter.
            record.transition(ConnectionStatus.STOPPED)
            self.store.save_record(record)
            return record

    async def attach(
        self,
        identifier: str,
        *,
        reconnect_seconds=120,
        terminal_factory=None,
        publish=None,
        on_start=None,
    ) -> int:
        self.validate_reconnect(reconnect_seconds)
        if terminal_factory is None:
            from .terminal import Terminal

            terminal_factory = Terminal
        with self.store.lock(identifier):
            record = self.store.load_record(identifier)
            if not record.status.attachable:
                raise UserError("This remote session has ended. Create a new cloud agent.")
            if on_start:
                on_start(record)
            with terminal_factory() as terminal:
                return await Connector(
                    self.store,
                    record,
                    self.transport_factory(record.profile),
                    terminal,
                    reconnect_seconds=reconnect_seconds,
                    publish=publish,
                ).run()
