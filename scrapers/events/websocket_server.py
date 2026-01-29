"""
WebSocket Server for Test Lab Real-Time Updates

WebSocket server using Socket.io for broadcasting Test Lab events to connected clients.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class ConnectionHandler:
    """Handles individual WebSocket connections."""

    def __init__(self, socket: Any) -> None:
        """Initialize connection handler with socket."""
        self.socket = socket
        self.client_id = str(uuid.uuid4())
        self.rooms: set[str] = set()

    def join_room(self, room_id: str) -> None:
        """Join a room for targeted broadcasts."""
        self.rooms.add(room_id)
        logger.info(f"Client {self.client_id} joined room {room_id}")

    def leave_room(self, room_id: str) -> None:
        """Leave a room."""
        self.rooms.discard(room_id)
        logger.info(f"Client {self.client_id} left room {room_id}")

    def send_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Send an event to this client."""
        message = json.dumps(
            {
                "event_type": event_type,
                "data": data,
            }
        )
        self.socket.emit(event_type, message)

    def disconnect(self) -> None:
        """Handle client disconnection."""
        logger.info(f"Client {self.client_id} disconnected")


class ReconnectionHandler:
    """Handles client reconnection with exponential backoff."""

    def __init__(
        self,
        max_attempts: int = 5,
        base_delay: int = 1000,
        max_delay: int = 30000,
    ) -> None:
        """Initialize reconnection handler."""
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay

    def get_delay(self, attempt: int) -> int:
        """Calculate delay for given attempt number (exponential backoff)."""
        delay = min(self.base_delay * (2**attempt), self.max_delay)
        # Add jitter (10%)
        import random

        delay = int(delay * (0.9 + random.random() * 0.2))
        return delay


class TestLabWebSocketServer:
    """WebSocket server for Test Lab real-time updates."""

    def __init__(
        self,
        max_reconnect_attempts: int = 5,
        reconnect_delay: int = 1000,
    ) -> None:
        """Initialize WebSocket server."""
        self.connections: dict[str, ConnectionHandler] = {}
        self.rooms: dict[str, set[str]] = {}
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.reconnection_handler = ReconnectionHandler(
            max_attempts=max_reconnect_attempts,
            base_delay=reconnect_delay,
        )

    def connect(self, socket: Any) -> ConnectionHandler:
        """Accept a new WebSocket connection."""
        handler = ConnectionHandler(socket)
        self.connections[handler.client_id] = handler
        logger.info(f"New connection: {handler.client_id}")
        return handler

    def disconnect(self, client_id: str) -> None:
        """Handle disconnection."""
        if client_id in self.connections:
            handler = self.connections[client_id]
            # Remove from all rooms
            for room_id in handler.rooms:
                self._remove_from_room(client_id, room_id)
            del self.connections[client_id]
            logger.info(f"Disconnected: {client_id}")

    def subscribe(self, client_id: str, room_id: str) -> bool:
        """Subscribe a client to a room."""
        if client_id not in self.connections:
            return False

        handler = self.connections[client_id]
        handler.join_room(room_id)

        if room_id not in self.rooms:
            self.rooms[room_id] = set()
        self.rooms[room_id].add(client_id)

        return True

    def unsubscribe(self, client_id: str, room_id: str) -> bool:
        """Unsubscribe a client from a room."""
        if client_id not in self.connections:
            return False

        handler = self.connections[client_id]
        handler.leave_room(room_id)
        self._remove_from_room(client_id, room_id)

        return True

    def _remove_from_room(self, client_id: str, room_id: str) -> None:
        """Remove client from room tracking."""
        if room_id in self.rooms:
            self.rooms[room_id].discard(client_id)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    def get_room_clients(self, room_id: str) -> list[str]:
        """Get list of client IDs in a room."""
        return list(self.rooms.get(room_id, set()))

    def emit(self, event_type: str, data: dict[str, Any], room_id: str | None = None) -> None:
        """Emit an event to connected clients."""
        message = json.dumps(
            {
                "event_type": event_type,
                "data": data,
            }
        )

        if room_id:
            # Send to specific room
            client_ids = self.rooms.get(room_id, set())
            for client_id in client_ids:
                if client_id in self.connections:
                    handler = self.connections[client_id]
                    handler.socket.emit(event_type, message)
        else:
            # Send to all connected clients
            for handler in self.connections.values():
                handler.socket.emit(event_type, message)

    def broadcast_to_room(self, room_id: str, event_data: dict[str, Any]) -> int:
        """Broadcast event to all clients in a room."""
        if room_id not in self.rooms:
            return 0

        count = 0
        for client_id in self.rooms[room_id]:
            if client_id in self.connections:
                handler = self.connections[client_id]
                handler.socket.emit(event_data.get("event_type", "event"), json.dumps(event_data))
                count += 1

        logger.info(f"Broadcast to room {room_id}: {count} clients")
        return count

    def broadcast_all(self, event_data: dict[str, Any]) -> int:
        """Broadcast event to all connected clients."""
        count = 0
        for handler in self.connections.values():
            handler.socket.emit(event_data.get("event_type", "event"), json.dumps(event_data))
            count += 1

        logger.info(f"Broadcast to all: {count} clients")
        return count

    def authenticate(self, token: str) -> bool:
        """Authenticate a connection token."""
        # Simple token validation - in production, use proper JWT validation
        if not token or len(token) < 8:
            return False
        return True

    def get_stats(self) -> dict[str, Any]:
        """Get server statistics."""
        return {
            "total_connections": len(self.connections),
            "total_rooms": len(self.rooms),
            "clients_per_room": {room_id: len(clients) for room_id, clients in self.rooms.items()},
        }
