import re
import uuid
import json
import csv
import os
import logging
from datetime import datetime
from functools import reduce
from typing import List, Dict, Any, Optional
_util_logger = logging.getLogger("ITServiceDesk")

DATA_DIR      = os.path.join(os.path.dirname(__file__), "data")
TICKETS_FILE  = os.path.join(DATA_DIR, "tickets.json")
PROBLEMS_FILE = os.path.join(DATA_DIR, "problems.json")
BACKUP_FILE   = os.path.join(DATA_DIR, "backup.csv")
LOG_FILE      = os.path.join(DATA_DIR, "logs.txt")

os.makedirs(DATA_DIR, exist_ok=True)

# Priority → SLA in minutes
SLA_RULES: Dict[str, int] = {
    "P1": 60,        # 1 hour
    "P2": 240,       # 4 hours
    "P3": 480,       # 8 hours
    "P4": 1440,      # 24 hours
}

# Issue keyword → priority mapping
ISSUE_PRIORITY_MAP: Dict[str, str] = {
    "server down":      "P1",
    "server is down":   "P1",
    "internet down":    "P2",
    "internet issues":  "P2",
    "network":          "P2",
    "laptop slow":      "P3",
    "printer":          "P3",
    "disk full":        "P3",
    "high cpu":         "P3",
    "application":      "P3",
    "password reset":   "P4",
    "password":         "P4",
    "software install": "P4",
}

VALID_STATUSES: frozenset = frozenset({

    "Open", "In Progress", "Resolved", "Closed", "Escalated"

})

VALID_PRIORITIES: frozenset = frozenset({"P1", "P2", "P3", "P4"})
VALID_CATEGORIES: frozenset = frozenset({
    "Hardware", "Software", "Network",
    "Security", "Access", "Performance", 
    "Other"

})

# tuple = ordered immutable sequence — demonstrates TUPLE data type explicitly
PRIORITY_ORDER: tuple = ("P1", "P2", "P3", "P4")
SLA_HOURS: tuple = (1, 4, 8, 24)  # matching hours for P1..P4



class ITILError(Exception):
    """Base exception for all ITIL application errors."""
    pass


class TicketNotFoundError(ITILError):
    """Raised when a ticket ID cannot be found."""
    def __init__(self, ticket_id: str):
        super().__init__(f"Ticket '{ticket_id}' not found.")
        self.ticket_id = ticket_id


class DuplicateTicketError(ITILError):
    """Raised when a duplicate ticket is detected."""
    def __init__(self, ticket_id: str):
        super().__init__(f"Duplicate ticket ID '{ticket_id}'.")
        self.ticket_id = ticket_id


class InvalidPriorityError(ITILError):
    """Raised for an unrecognised priority string."""
    def __init__(self, priority: str):
        super().__init__(
            f"Invalid priority '{priority}'. Must be one of {VALID_PRIORITIES}."
        )


class InvalidStatusError(ITILError):
    """Raised for an unrecognised status string."""
    def __init__(self, status: str):
        super().__init__(
            f"Invalid status '{status}'. Must be one of {VALID_STATUSES}."
        )


class EmptyValueError(ITILError):
    """Raised when a required field is empty or None."""
    def __init__(self, field: str):
        super().__init__(f"Required field '{field}' cannot be empty.")


class FileOperationError(ITILError):
    """Raised on file read/write failures."""
    pass



def generate_ticket_id() -> str:
    """Generate a unique ticket ID like TKT-20240101-A1B2."""
    date_part = datetime.now().strftime("%Y%m%d")
    uid_part   = uuid.uuid4().hex[:4].upper()
    return f"TKT-{date_part}-{uid_part}"


def now_iso() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now().isoformat(timespec="seconds")


def parse_dt(iso_str: str) -> datetime:
    """Parse ISO-8601 string back to datetime."""
    return datetime.fromisoformat(iso_str)


def minutes_since(iso_str: str) -> float:
    """Return elapsed minutes from iso_str to now."""
    delta = datetime.now() - parse_dt(iso_str)
    return delta.total_seconds() / 60



def infer_priority(description: str) -> str:
    """Guess ticket priority from free-text description (basic regex)."""
    desc_lower = description.lower()
    if re.search(r"server.{0,20}down", desc_lower):
        return "P1"
    for keyword, priority in ISSUE_PRIORITY_MAP.items():
        if re.search(re.escape(keyword), desc_lower):
            return priority
    return "P3"  # default



def validate_non_empty(value: Any, field: str) -> str:
    """Raise EmptyValueError if value is blank, else return stripped string."""
    if value is None or str(value).strip() == "":
        raise EmptyValueError(field)
    return str(value).strip()


def validate_priority(priority: str) -> str:
    p = priority.strip().upper()
    if p not in VALID_PRIORITIES:
        raise InvalidPriorityError(p)
    return p


def validate_status(status: str) -> str:
    s = status.strip().title()
    if s not in VALID_STATUSES:
        raise InvalidStatusError(s)
    return s



def load_json(filepath: str, default=None):
    """Load JSON from file; return default if file missing."""
    if default is None:
        default = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        raise FileOperationError(f"JSON parse error in {filepath}: {e}")
    finally:
        _util_logger.debug(f"load_json attempted: {filepath}")


def save_json(filepath: str, data: Any) -> None:
    """Persist data as pretty-printed JSON."""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
    except OSError as e:
        raise FileOperationError(f"Cannot write {filepath}: {e}")
    finally:
        _util_logger.debug(f"save_json attempted: {filepath}")


def append_to_csv(filepath: str, rows: List[Dict], fieldnames: List[str]) -> None:
    """Append rows to a CSV file, writing header if file is new."""
    file_exists = os.path.isfile(filepath)
    try:
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerows(rows)
    except OSError as e:
        raise FileOperationError(f"Cannot write CSV {filepath}: {e}")


def read_csv(filepath: str) -> List[Dict]:
    """Read all rows from a CSV file into a list of dicts."""
    try:
        with open(filepath, "r", newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise FileOperationError(f"Cannot read CSV {filepath}: {e}")



def filter_by_status(tickets: List[Dict], status: str) -> List[Dict]:
    return list(filter(lambda t: t.get("status") == status, tickets))


def filter_by_priority(tickets: List[Dict], priority: str) -> List[Dict]:
    return list(filter(lambda t: t.get("priority") == priority, tickets))


def map_ticket_ids(tickets: List[Dict]) -> List[str]:
    return list(map(lambda t: t.get("ticket_id", ""), tickets))


def count_by_field(tickets: List[Dict], field: str) -> Dict[str, int]:
    """Group-count tickets by a given field using reduce."""
    def reducer(acc, ticket):
        key = ticket.get(field, "Unknown")
        acc[key] = acc.get(key, 0) + 1
        return acc
    return reduce(reducer, tickets, {})


def ticket_generator(tickets: List[Dict]):
    """Lazy generator that yields one ticket dict at a time."""
    for ticket in tickets:
        yield ticket


class TicketIterator:
    """Custom iterator that walks a list of ticket dicts."""

    def __init__(self, tickets: List[Dict]):
        self._tickets = tickets
        self._index = 0

    def __iter__(self):
        return self

    def __next__(self) -> Dict:
        if self._index >= len(self._tickets):
            raise StopIteration
        ticket = self._tickets[self._index]
        self._index += 1
        return ticket

    def __len__(self):
        return len(self._tickets)



PRIORITY_COLORS = {"P1": "🔴", "P2": "🟠", "P3": "🟡", "P4": "🟢"}

def priority_label(p: str) -> str:
    return f"{PRIORITY_COLORS.get(p, '')} {p}"


def divider(char: str = "─", width: int = 70) -> str:
    return char * width


def header_banner(title: str, width: int = 70) -> str:
    pad = (width - len(title) - 2) // 2
    return f"{'═' * width}\n{'║'}{' ' * pad}{title}{' ' * (width - pad - len(title) - 2)}{'║'}\n{'═' * width}"
