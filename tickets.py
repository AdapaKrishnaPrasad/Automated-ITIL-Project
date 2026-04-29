import json
from datetime import datetime
from typing import List, Dict, Optional, Any

from utils import (
    generate_ticket_id, now_iso, minutes_since, infer_priority,
    validate_non_empty, validate_priority, validate_status,
    SLA_RULES, TICKETS_FILE, PROBLEMS_FILE,
    load_json, save_json, append_to_csv, BACKUP_FILE,
    TicketIterator, ticket_generator, count_by_field,
    filter_by_status, filter_by_priority, map_ticket_ids,
    DuplicateTicketError, TicketNotFoundError, EmptyValueError,
    InvalidPriorityError, InvalidStatusError, FileOperationError,
    priority_label, divider,
)
from logger import logger, log_action, log_ticket_event, log_sla_breach, log_error


class Ticket:

    _ticket_count: int = 0   # class variable (encapsulation demo)

    def __init__(
        self,
        employee_name: str,
        department: str,
        issue_description: str,
        category: str,
        priority: Optional[str] = None,
        ticket_id: Optional[str] = None,
        status: str = "Open",
        created_date: Optional[str] = None,
    ):
        # Validate required fields
        self.employee_name    = validate_non_empty(employee_name, "employee_name")
        self.department       = validate_non_empty(department, "department")
        self.issue_description = validate_non_empty(issue_description, "issue_description")
        self.category         = validate_non_empty(category, "category")

        # Priority: provided or auto-inferred from description
        if priority:
            self.priority = validate_priority(priority)
        else:
            self.priority = infer_priority(issue_description)

        self.ticket_id    = ticket_id if ticket_id else generate_ticket_id()
        self.status       = validate_status(status)
        self.created_date = created_date if created_date else now_iso()
        self.updated_date = now_iso()
        self.closed_date: Optional[str] = None

        # Private encapsulated field
        self._resolution_notes: List[str] = []

        Ticket._ticket_count += 1

    # ── Properties ──────────────────────────────────────────
    @property
    def resolution_notes(self) -> List[str]:
        """Read-only view of internal resolution notes."""
        return list(self._resolution_notes)

    @property
    def sla_limit_minutes(self) -> int:
        return SLA_RULES.get(self.priority, 480)

    @property
    def elapsed_minutes(self) -> float:
        return minutes_since(self.created_date)

    @property
    def is_sla_breached(self) -> bool:
        if self.status in ("Resolved", "Closed"):
            return False
        return self.elapsed_minutes > self.sla_limit_minutes

    @property
    def remaining_sla_minutes(self) -> float:
        return max(0.0, self.sla_limit_minutes - self.elapsed_minutes)

    # ── Public Methods ───────────────────────────────────────
    def add_note(self, note: str) -> None:
        """Append a resolution note (encapsulated mutation)."""
        self._resolution_notes.append(f"[{now_iso()}] {note}")

    def update_status(self, new_status: str) -> None:
        self.status = validate_status(new_status)
        self.updated_date = now_iso()
        if new_status in ("Resolved", "Closed"):
            self.closed_date = now_iso()

    def to_dict(self) -> Dict:
        """Serialise to plain dict (for JSON/CSV storage)."""
        return {
            "ticket_type":        self.__class__.__name__,
            "ticket_id":          self.ticket_id,
            "employee_name":      self.employee_name,
            "department":         self.department,
            "issue_description":  self.issue_description,
            "category":           self.category,
            "priority":           self.priority,
            "status":             self.status,
            "created_date":       self.created_date,
            "updated_date":       self.updated_date,
            "closed_date":        self.closed_date,
            "resolution_notes":   self._resolution_notes,
            "sla_breached":       self.is_sla_breached,
        }

    # ── Static Methods ───────────────────────────────────────
    @staticmethod
    def from_dict(data: Dict) -> "Ticket":
        """Factory: reconstruct the correct subclass from a dict."""
        ticket_type = data.get("ticket_type", "Ticket")
        cls_map = {
            "IncidentTicket": IncidentTicket,
            "ServiceRequest":  ServiceRequest,
            "ProblemRecord":   ProblemRecord,
        }
        cls = cls_map.get(ticket_type, Ticket)
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: Dict) -> "Ticket":
        obj = cls.__new__(cls)
        obj.ticket_id          = data["ticket_id"]
        obj.employee_name      = data["employee_name"]
        obj.department         = data["department"]
        obj.issue_description  = data["issue_description"]
        obj.category           = data["category"]
        obj.priority           = data["priority"]
        obj.status             = data["status"]
        obj.created_date       = data["created_date"]
        obj.updated_date       = data.get("updated_date", data["created_date"])
        obj.closed_date        = data.get("closed_date")
        obj._resolution_notes  = data.get("resolution_notes", [])
        return obj

    @staticmethod
    def get_ticket_count() -> int:
        return Ticket._ticket_count

    # ── Special Methods ──────────────────────────────────────
    def __str__(self) -> str:
        breach = "⚠️ BREACHED" if self.is_sla_breached else "✅ OK"
        return (
            f"[{self.ticket_id}] {priority_label(self.priority)} | "
            f"{self.status} | {self.employee_name} ({self.department}) | "
            f"SLA: {breach}"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(id={self.ticket_id!r}, "
            f"priority={self.priority!r}, status={self.status!r})"
        )

    def __eq__(self, other) -> bool:
        if not isinstance(other, Ticket):
            return NotImplemented
        return self.ticket_id == other.ticket_id

    def __lt__(self, other) -> bool:
        """Allow sorting by priority (P1 < P2 < P3 < P4)."""
        if not isinstance(other, Ticket):
            return NotImplemented
        return self.priority < other.priority


# ─────────────────────────────────────────────────────────────
# SUB-CLASS: IncidentTicket
# ─────────────────────────────────────────────────────────────
class IncidentTicket(Ticket):
    """
    Represents an IT incident (unplanned interruption or degradation).
    Demonstrates Inheritance + Polymorphism.
    """

    def __init__(self, *args, impact: str = "Low", urgency: str = "Low", **kwargs):
        super().__init__(*args, **kwargs)
        self.impact  = impact    # Low / Medium / High
        self.urgency = urgency   # Low / Medium / High
        self.escalation_count: int = 0

    def escalate(self) -> None:
        """Increment escalation counter and update status."""
        self.escalation_count += 1
        self.status = "Escalated"
        self.updated_date = now_iso()
        logger.warning(
            f"ESCALATION | ticket={self.ticket_id} | count={self.escalation_count}"
        )

    def to_dict(self) -> Dict:
        d = super().to_dict()
        d.update({
            "impact":            self.impact,
            "urgency":           self.urgency,
            "escalation_count":  self.escalation_count,
        })
        return d

    @classmethod
    def _from_dict(cls, data: Dict) -> "IncidentTicket":
        obj = super()._from_dict(data)          # type: ignore[misc]
        obj.impact            = data.get("impact", "Low")
        obj.urgency           = data.get("urgency", "Low")
        obj.escalation_count  = data.get("escalation_count", 0)
        return obj

    def __str__(self) -> str:
        return f"🚨 INCIDENT | {super().__str__()} | Impact={self.impact}"


# ─────────────────────────────────────────────────────────────
# SUB-CLASS: ServiceRequest
# ─────────────────────────────────────────────────────────────
class ServiceRequest(Ticket):
    """
    Represents a standard service request (password reset, software install…).
    Demonstrates Inheritance + Polymorphism.
    """

    def __init__(self, *args, requested_service: str = "General", **kwargs):
        super().__init__(*args, **kwargs)
        self.requested_service = requested_service
        self.approved: bool = False

    def approve(self) -> None:
        self.approved = True
        self.status = "In Progress"
        self.updated_date = now_iso()

    def to_dict(self) -> Dict:
        d = super().to_dict()
        d.update({
            "requested_service": self.requested_service,
            "approved":          self.approved,
        })
        return d

    @classmethod
    def _from_dict(cls, data: Dict) -> "ServiceRequest":
        obj = super()._from_dict(data)          # type: ignore[misc]
        obj.requested_service = data.get("requested_service", "General")
        obj.approved          = data.get("approved", False)
        return obj

    def __str__(self) -> str:
        approved = "✅ Approved" if self.approved else "⏳ Pending"
        return f"🔧 SERVICE REQUEST | {super().__str__()} | {approved}"


# ─────────────────────────────────────────────────────────────
# SUB-CLASS: ProblemRecord
# ─────────────────────────────────────────────────────────────
class ProblemRecord(Ticket):
    """
    Created when the same issue occurs 5+ times (ITIL Problem Management).
    Links to the related incident ticket IDs.
    """

    PROBLEM_THRESHOLD = 5

    def __init__(self, *args, related_tickets: Optional[List[str]] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.related_tickets: List[str] = related_tickets or []
        self.root_cause: str = "Under investigation"
        self.known_error: bool = False

    def set_root_cause(self, cause: str) -> None:
        self.root_cause = cause
        self.known_error = True
        self.updated_date = now_iso()

    def to_dict(self) -> Dict:
        d = super().to_dict()
        d.update({
            "related_tickets": self.related_tickets,
            "root_cause":      self.root_cause,
            "known_error":     self.known_error,
        })
        return d

    @classmethod
    def _from_dict(cls, data: Dict) -> "ProblemRecord":
        obj = super()._from_dict(data)          # type: ignore[misc]
        obj.related_tickets = data.get("related_tickets", [])
        obj.root_cause      = data.get("root_cause", "Under investigation")
        obj.known_error     = data.get("known_error", False)
        return obj

    def __str__(self) -> str:
        return (
            f"⚙️  PROBLEM | {super().__str__()} | "
            f"Related={len(self.related_tickets)} | RCA={self.root_cause[:30]}…"
        )


# ─────────────────────────────────────────────────────────────
# TICKET MANAGER
# ─────────────────────────────────────────────────────────────
class TicketManager:
    """
    CRUD operations, persistence, search, sort, and SLA checks.

    Demonstrates:
      - Encapsulation (_tickets dict)
      - Iterators / generators
      - map / filter / reduce (via utils)
      - JSON + CSV file handling
      - Exception handling
    """

    def __init__(self):
        self._tickets: Dict[str, Ticket] = {}
        self._load_from_file()

    # ── Internal helpers ─────────────────────────────────────
    def _load_from_file(self) -> None:
        """Load tickets from JSON at startup."""
        raw_list = load_json(TICKETS_FILE, default=[])
        for raw in raw_list:
            try:
                t = Ticket.from_dict(raw)
                self._tickets[t.ticket_id] = t
            except Exception as e:
                log_error("TicketManager._load_from_file", e)
        logger.info(f"Loaded {len(self._tickets)} tickets from storage.")

    def _save_to_file(self) -> None:
        """Persist all tickets to JSON."""
        data = [t.to_dict() for t in self._tickets.values()]
        save_json(TICKETS_FILE, data)

    # ── CREATE ───────────────────────────────────────────────
    @log_action("CreateTicket")
    def create_ticket(
        self,
        employee_name: str,
        department: str,
        issue_description: str,
        category: str,
        priority: Optional[str] = None,
        ticket_type: str = "Incident",
        **kwargs,
    ) -> Ticket:
        """
        Factory method: create and store the right ticket subclass.
        ticket_type: 'Incident' | 'ServiceRequest' | 'Problem'
        """
        cls_map = {
            "Incident":       IncidentTicket,
            "ServiceRequest": ServiceRequest,
            "Problem":        ProblemRecord,
        }
        cls = cls_map.get(ticket_type, IncidentTicket)

        ticket = cls(
            employee_name=employee_name,
            department=department,
            issue_description=issue_description,
            category=category,
            priority=priority,
            **kwargs,
        )

        if ticket.ticket_id in self._tickets:
            raise DuplicateTicketError(ticket.ticket_id)

        self._tickets[ticket.ticket_id] = ticket
        self._save_to_file()
        log_ticket_event("CREATED", ticket.ticket_id, f"priority={ticket.priority}")
        return ticket

    # ── READ ─────────────────────────────────────────────────
    def get_ticket(self, ticket_id: str) -> Ticket:
        t = self._tickets.get(ticket_id.strip())
        if not t:
            raise TicketNotFoundError(ticket_id)
        return t

    def get_all_tickets(self) -> List[Ticket]:
        return list(self._tickets.values())

    def get_open_tickets(self) -> List[Ticket]:
        return [t for t in self._tickets.values() if t.status not in ("Resolved", "Closed")]

    # ── SEARCH ───────────────────────────────────────────────
    def search_by_id(self, ticket_id: str) -> Optional[Ticket]:
        return self._tickets.get(ticket_id.strip())

    def search_by_employee(self, name: str) -> List[Ticket]:
        n = name.lower()
        return [t for t in self._tickets.values() if n in t.employee_name.lower()]

    def search_by_status(self, status: str) -> List[Ticket]:
        return [t for t in self._tickets.values() if t.status == status]

    def search_by_priority(self, priority: str) -> List[Ticket]:
        return [t for t in self._tickets.values() if t.priority == priority.upper()]

    # ── UPDATE ───────────────────────────────────────────────
    @log_action("UpdateTicket")
    def update_status(self, ticket_id: str, new_status: str, note: str = "") -> Ticket:
        ticket = self.get_ticket(ticket_id)
        old_status = ticket.status
        ticket.update_status(new_status)
        if note:
            ticket.add_note(note)
        self._save_to_file()
        log_ticket_event(
            "UPDATED", ticket_id,
            f"status={old_status}→{new_status}"
        )
        return ticket

    # ── CLOSE ────────────────────────────────────────────────
    @log_action("CloseTicket")
    def close_ticket(self, ticket_id: str, resolution: str) -> Ticket:
        ticket = self.get_ticket(ticket_id)
        ticket.update_status("Closed")
        ticket.add_note(f"Resolution: {resolution}")
        self._save_to_file()
        log_ticket_event("CLOSED", ticket_id)
        return ticket

    # ── DELETE ───────────────────────────────────────────────
    @log_action("DeleteTicket")
    def delete_ticket(self, ticket_id: str) -> None:
        if ticket_id not in self._tickets:
            raise TicketNotFoundError(ticket_id)
        del self._tickets[ticket_id]
        self._save_to_file()
        log_ticket_event("DELETED", ticket_id)

    # ── SLA ──────────────────────────────────────────────────
    def get_breached_tickets(self) -> List[Ticket]:
        return [t for t in self._tickets.values() if t.is_sla_breached]

    def check_and_escalate(self) -> List[Ticket]:
        """Escalate any open IncidentTickets with breached SLA."""
        escalated = []
        for ticket in self._tickets.values():
            if ticket.is_sla_breached and isinstance(ticket, IncidentTicket):
                ticket.escalate()
                escalated.append(ticket)
                log_sla_breach(ticket.ticket_id, ticket.priority, ticket.elapsed_minutes - ticket.sla_limit_minutes)
        if escalated:
            self._save_to_file()
        return escalated

    # ── SORT ─────────────────────────────────────────────────
    def sorted_by_priority(self) -> List[Ticket]:
        return sorted(self._tickets.values())

    def sorted_by_date(self, reverse: bool = True) -> List[Ticket]:
        return sorted(
            self._tickets.values(),
            key=lambda t: t.created_date,
            reverse=reverse,
        )

    # ── BACKUP ───────────────────────────────────────────────
    def backup_to_csv(self) -> int:
        """Write all tickets to backup.csv; returns count written."""
        tickets_dicts = [t.to_dict() for t in self._tickets.values()]
        if not tickets_dicts:
            return 0

        # Collect ALL unique keys across every ticket type (Incident, Service, Problem)
        all_keys = []
        seen = set()
        for d in tickets_dicts:
            for k in d.keys():
                if k not in seen:
                    seen.add(k)
                    all_keys.append(k)

        import csv, os
        with open(BACKUP_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
            writer.writeheader()
            # Fill missing fields with empty string so all rows have the same columns
            for row in tickets_dicts:
                filled = {k: row.get(k, "") for k in all_keys}
                writer.writerow(filled)

        logger.info(f"Backup: wrote {len(tickets_dicts)} tickets to {BACKUP_FILE}")
        return len(tickets_dicts)

    # ── GENERATOR ────────────────────────────────────────────
    def ticket_gen(self):
        """Generator: yields each ticket one at a time."""
        yield from ticket_generator([t.to_dict() for t in self._tickets.values()])

    def __iter__(self):
        return TicketIterator(self.get_all_tickets())

    def __len__(self):
        return len(self._tickets)

    def __repr__(self):
        return f"TicketManager(total={len(self._tickets)})"

    # ── DISPLAY ──────────────────────────────────────────────
    def display_all(self) -> None:
        print(divider())
        print(f"  ALL TICKETS  (total: {len(self)})")
        print(divider())
        for ticket in self.sorted_by_priority():
            print(ticket)
        print(divider())

    def display_sla_status(self) -> None:
        print(divider())
        print("  SLA STATUS REPORT")
        print(divider())
        open_tickets = self.get_open_tickets()
        for t in sorted(open_tickets):
            status = "⚠️ BREACHED" if t.is_sla_breached else f"⏳ {t.remaining_sla_minutes:.0f} min left"
            print(f"  {t.ticket_id} | {t.priority} | {t.status} | {status}")
        if not open_tickets:
            print("  No open tickets.")
        print(divider())