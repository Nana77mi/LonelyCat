"""
Event Stream System - Phase 2.4-B

Provides machine-readable event logging for execution analysis.

Philosophy:
- Append-only: Events are immutable, never modified
- Structured: JSON format for easy parsing
- Timestamped: Precise timing for time-series analysis
- Minimal overhead: Fast writes, no blocking

Event Types:
- file_changed: File modification events
- test_failed: Test failure events
- test_passed: Test success events
- health_check_failed: Health check failure events
- health_check_passed: Health check success events
- rollback_triggered: Rollback events
- verification_started: Verification start events
- verification_completed: Verification completion events

Use Cases:
- Debugging: "What happened at 10:15:30?"
- Time-series analysis: "How often do tests fail?"
- Correlation: "Does file X change always cause test Y to fail?"
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
import threading


class EventType(Enum):
    """Event type enumeration."""
    FILE_CHANGED = "file_changed"
    TEST_FAILED = "test_failed"
    TEST_PASSED = "test_passed"
    HEALTH_CHECK_FAILED = "health_check_failed"
    HEALTH_CHECK_PASSED = "health_check_passed"
    ROLLBACK_TRIGGERED = "rollback_triggered"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"


@dataclass
class Event:
    """
    Structured event for execution timeline.

    All events have:
    - event_type: Category of event
    - timestamp: When it occurred (ISO8601 UTC)
    - data: Type-specific payload
    """
    event_type: str  # EventType value
    timestamp: str  # ISO8601 UTC
    data: Dict[str, Any]  # Event-specific data

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(asdict(self), separators=(',', ':'))

    @classmethod
    def from_json(cls, json_str: str) -> "Event":
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def create(cls, event_type: EventType, data: Dict[str, Any]) -> "Event":
        """
        Create event with current timestamp.

        Args:
            event_type: Type of event
            data: Event-specific payload

        Returns:
            Event with timestamp
        """
        return cls(
            event_type=event_type.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data
        )


class EventWriter:
    """
    Writes events to JSONL file (append-only).

    Thread-safe for concurrent writes.
    """

    def __init__(self, events_file: Path):
        """
        Initialize event writer.

        Args:
            events_file: Path to events.jsonl file
        """
        self.events_file = events_file
        self._lock = threading.Lock()

        # Ensure parent directory exists
        self.events_file.parent.mkdir(parents=True, exist_ok=True)

    def write_event(self, event: Event):
        """
        Write event to file (append mode).

        Thread-safe.

        Args:
            event: Event to write
        """
        with self._lock:
            with open(self.events_file, 'a', encoding='utf-8') as f:
                f.write(event.to_json() + '\n')

    def write_events(self, events: List[Event]):
        """
        Write multiple events atomically.

        Args:
            events: Events to write
        """
        with self._lock:
            with open(self.events_file, 'a', encoding='utf-8') as f:
                for event in events:
                    f.write(event.to_json() + '\n')


class EventReader:
    """
    Reads and filters events from JSONL file.
    """

    def __init__(self, events_file: Path):
        """
        Initialize event reader.

        Args:
            events_file: Path to events.jsonl file
        """
        self.events_file = events_file

    def read_all_events(self) -> List[Event]:
        """
        Read all events from file.

        Returns:
            List of events in chronological order
        """
        if not self.events_file.exists():
            return []

        events = []
        with open(self.events_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        event = Event.from_json(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue

        return events

    def filter_events(
        self,
        event_type: Optional[EventType] = None,
        since: Optional[str] = None,
        until: Optional[str] = None
    ) -> List[Event]:
        """
        Filter events by type and time range.

        Args:
            event_type: Filter by event type (None = all types)
            since: ISO timestamp - only events after this time
            until: ISO timestamp - only events before this time

        Returns:
            Filtered events
        """
        events = self.read_all_events()

        filtered = []
        for event in events:
            # Filter by type
            if event_type and event.event_type != event_type.value:
                continue

            # Filter by time range
            if since and event.timestamp < since:
                continue

            if until and event.timestamp > until:
                continue

            filtered.append(event)

        return filtered

    def get_event_count(self, event_type: Optional[EventType] = None) -> int:
        """
        Count events by type.

        Args:
            event_type: Event type to count (None = all events)

        Returns:
            Number of events
        """
        events = self.filter_events(event_type=event_type)
        return len(events)

    def get_event_timeline(self) -> List[Dict[str, Any]]:
        """
        Get event timeline summary (for visualization).

        Returns:
            List of {timestamp, event_type, summary} dicts
        """
        events = self.read_all_events()

        timeline = []
        for event in events:
            # Create summary based on event type
            summary = self._create_event_summary(event)

            timeline.append({
                'timestamp': event.timestamp,
                'event_type': event.event_type,
                'summary': summary
            })

        return timeline

    def _create_event_summary(self, event: Event) -> str:
        """Create human-readable summary of event."""
        event_type = event.event_type
        data = event.data

        if event_type == EventType.FILE_CHANGED.value:
            return f"{data.get('operation', 'changed')} {data.get('path', 'unknown')}"

        elif event_type == EventType.TEST_FAILED.value:
            return f"Test failed: {data.get('test_name', 'unknown')}"

        elif event_type == EventType.TEST_PASSED.value:
            return f"Test passed: {data.get('test_name', 'unknown')}"

        elif event_type == EventType.HEALTH_CHECK_FAILED.value:
            return f"Health check failed: {data.get('endpoint', 'unknown')} ({data.get('status_code', 'N/A')})"

        elif event_type == EventType.HEALTH_CHECK_PASSED.value:
            return f"Health check passed: {data.get('endpoint', 'unknown')}"

        elif event_type == EventType.ROLLBACK_TRIGGERED.value:
            return f"Rollback: {data.get('reason', 'unknown')}"

        elif event_type == EventType.VERIFICATION_STARTED.value:
            return f"Verification started: {data.get('plan_type', 'unknown')}"

        elif event_type == EventType.VERIFICATION_COMPLETED.value:
            success = data.get('success', False)
            status = "✓" if success else "✗"
            return f"Verification {status}: {data.get('plan_type', 'unknown')}"

        else:
            return event_type


# ==================== Event Factory Functions ====================

def create_file_changed_event(path: str, operation: str, checksum: Optional[str] = None) -> Event:
    """
    Create file_changed event.

    Args:
        path: File path
        operation: Operation type (CREATE, UPDATE, DELETE)
        checksum: File checksum (optional)

    Returns:
        Event
    """
    return Event.create(
        EventType.FILE_CHANGED,
        {
            'path': path,
            'operation': operation,
            'checksum': checksum
        }
    )


def create_test_failed_event(test_name: str, error: str, duration_seconds: Optional[float] = None) -> Event:
    """
    Create test_failed event.

    Args:
        test_name: Test name/identifier
        error: Error message
        duration_seconds: Test duration

    Returns:
        Event
    """
    return Event.create(
        EventType.TEST_FAILED,
        {
            'test_name': test_name,
            'error': error,
            'duration_seconds': duration_seconds
        }
    )


def create_test_passed_event(test_name: str, duration_seconds: Optional[float] = None) -> Event:
    """
    Create test_passed event.

    Args:
        test_name: Test name/identifier
        duration_seconds: Test duration

    Returns:
        Event
    """
    return Event.create(
        EventType.TEST_PASSED,
        {
            'test_name': test_name,
            'duration_seconds': duration_seconds
        }
    )


def create_health_check_failed_event(
    endpoint: str,
    status_code: int,
    response_time_ms: Optional[float] = None,
    error: Optional[str] = None
) -> Event:
    """
    Create health_check_failed event.

    Args:
        endpoint: Health check endpoint
        status_code: HTTP status code
        response_time_ms: Response time in milliseconds
        error: Error message

    Returns:
        Event
    """
    return Event.create(
        EventType.HEALTH_CHECK_FAILED,
        {
            'endpoint': endpoint,
            'status_code': status_code,
            'response_time_ms': response_time_ms,
            'error': error
        }
    )


def create_health_check_passed_event(
    endpoint: str,
    status_code: int,
    response_time_ms: Optional[float] = None
) -> Event:
    """
    Create health_check_passed event.

    Args:
        endpoint: Health check endpoint
        status_code: HTTP status code
        response_time_ms: Response time in milliseconds

    Returns:
        Event
    """
    return Event.create(
        EventType.HEALTH_CHECK_PASSED,
        {
            'endpoint': endpoint,
            'status_code': status_code,
            'response_time_ms': response_time_ms
        }
    )


def create_rollback_triggered_event(reason: str, files_restored: int) -> Event:
    """
    Create rollback_triggered event.

    Args:
        reason: Reason for rollback
        files_restored: Number of files restored

    Returns:
        Event
    """
    return Event.create(
        EventType.ROLLBACK_TRIGGERED,
        {
            'reason': reason,
            'files_restored': files_restored
        }
    )


def create_verification_started_event(plan_type: str, plan_content: Optional[str] = None) -> Event:
    """
    Create verification_started event.

    Args:
        plan_type: Verification plan type (command, test, etc.)
        plan_content: Verification plan content

    Returns:
        Event
    """
    return Event.create(
        EventType.VERIFICATION_STARTED,
        {
            'plan_type': plan_type,
            'plan_content': plan_content
        }
    )


def create_verification_completed_event(
    plan_type: str,
    success: bool,
    duration_seconds: float,
    error: Optional[str] = None
) -> Event:
    """
    Create verification_completed event.

    Args:
        plan_type: Verification plan type
        success: Whether verification succeeded
        duration_seconds: Verification duration
        error: Error message (if failed)

    Returns:
        Event
    """
    return Event.create(
        EventType.VERIFICATION_COMPLETED,
        {
            'plan_type': plan_type,
            'success': success,
            'duration_seconds': duration_seconds,
            'error': error
        }
    )


if __name__ == "__main__":
    # Quick test
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        events_file = Path(tmpdir) / "events.jsonl"

        # Write events
        writer = EventWriter(events_file)

        writer.write_event(create_file_changed_event("src/app.py", "UPDATE", "abc123"))
        writer.write_event(create_test_failed_event("test_app", "AssertionError: expected 1, got 2", 0.5))
        writer.write_event(create_health_check_failed_event("http://localhost:8080/health", 500, 100.5, "Internal Server Error"))
        writer.write_event(create_rollback_triggered_event("Health check failed", 3))

        # Read events
        reader = EventReader(events_file)

        all_events = reader.read_all_events()
        print(f"Total events: {len(all_events)}")

        for event in all_events:
            print(f"{event.timestamp} - {event.event_type}: {event.data}")

        # Filter events
        test_events = reader.filter_events(event_type=EventType.TEST_FAILED)
        print(f"\nTest failures: {len(test_events)}")

        # Timeline
        timeline = reader.get_event_timeline()
        print("\nTimeline:")
        for item in timeline:
            print(f"  {item['timestamp']}: {item['summary']}")
