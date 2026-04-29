from typing import Dict, List, Optional
from collections import defaultdict, Counter

from tickets import Ticket, IncidentTicket, ServiceRequest, ProblemRecord, TicketManager
from utils import (
    PROBLEMS_FILE, now_iso, SLA_RULES, load_json, save_json,
    divider, header_banner, priority_label, count_by_field,
)
from logger import logger, log_ticket_event, log_sla_breach, log_error


# ─────────────────────────────────────────────────────────────
# SLA MANAGER
# ─────────────────────────────────────────────────────────────
class SLAManager:

    SLA_TABLE = SLA_RULES  # {P1: 60, P2: 240, P3: 480, P4: 1440}

    def __init__(self, ticket_manager: TicketManager):
        self._tm = ticket_manager

    def get_sla_status_all(self) -> Dict[str, Dict]:
        """Return SLA status dict for every open ticket."""
        result = {}
        for ticket in self._tm.get_open_tickets():
            elapsed  = ticket.elapsed_minutes
            limit    = ticket.sla_limit_minutes
            breached = ticket.is_sla_breached
            result[ticket.ticket_id] = {
                "priority":        ticket.priority,
                "status":          ticket.status,
                "elapsed_min":     round(elapsed, 1),
                "sla_limit_min":   limit,
                "remaining_min":   round(max(0, limit - elapsed), 1),
                "breached":        breached,
            }
            if breached:
                log_sla_breach(
                    ticket.ticket_id, ticket.priority,
                    elapsed - limit
                )
        return result

    def get_breached_tickets(self) -> List[Ticket]:
        return self._tm.get_breached_tickets()

    def escalate_breached(self) -> List[Ticket]:
        return self._tm.check_and_escalate()

    def generate_warnings(self) -> List[str]:
        """
        Generator-based: yield a warning string for each
        ticket within 10 minutes of SLA breach.
        """
        def _warn_gen():
            for t in self._tm.get_open_tickets():
                remaining = t.remaining_sla_minutes
                if 0 < remaining <= 10:
                    yield (
                        f"⚠️  SLA WARNING | {t.ticket_id} | {t.priority} | "
                        f"only {remaining:.0f} min remaining"
                    )
        return list(_warn_gen())

    @staticmethod
    def sla_target_for(priority: str) -> str:
        mins = SLA_RULES.get(priority.upper(), 480)
        if mins < 60:
            return f"{mins} minutes"
        return f"{mins // 60} hour(s)"

    def display_sla_report(self) -> None:
        print(header_banner("SLA STATUS REPORT"))
        statuses = self.get_sla_status_all()
        if not statuses:
            print("  No open tickets.")
            return
        for tid, info in statuses.items():
            breach = "❌ BREACHED" if info["breached"] else f"✅ {info['remaining_min']} min left"
            print(
                f"  {tid} | {priority_label(info['priority'])} | "
                f"{info['status']} | Elapsed {info['elapsed_min']} min | {breach}"
            )
        print(divider())


# ─────────────────────────────────────────────────────────────
# INCIDENT MANAGER
# ─────────────────────────────────────────────────────────────
class IncidentManager:
    """
    ITIL Incident Management:
    Handle outages and failures quickly, minimise impact.
    """

    def __init__(self, ticket_manager: TicketManager):
        self._tm = ticket_manager

    def raise_incident(
        self,
        employee_name: str,
        department: str,
        description: str,
        category: str,
        priority: Optional[str] = None,
        impact: str = "Medium",
        urgency: str = "Medium",
    ) -> IncidentTicket:
        ticket = self._tm.create_ticket(
            employee_name=     employee_name,
            department=        department,
            issue_description= description,
            category=          category,
            priority=          priority,
            ticket_type=       "Incident",
            impact=            impact,
            urgency=           urgency,
        )
        logger.info(f"INCIDENT RAISED | id={ticket.ticket_id} | impact={impact}")
        return ticket  # type: ignore[return-value]

    def resolve_incident(self, ticket_id: str, resolution: str) -> Ticket:
        ticket = self._tm.close_ticket(ticket_id, resolution)
        logger.info(f"INCIDENT RESOLVED | id={ticket_id}")
        return ticket

    def list_active_incidents(self) -> List[IncidentTicket]:
        return [
            t for t in self._tm.get_open_tickets()
            if isinstance(t, IncidentTicket)
        ]

    def escalate_p1_incidents(self) -> List[IncidentTicket]:
        """Immediately escalate all unresolved P1 incidents."""
        escalated = []
        for t in self.list_active_incidents():
            if t.priority == "P1" and t.status != "Escalated":
                t.escalate()
                escalated.append(t)
        return escalated


# ─────────────────────────────────────────────────────────────
# SERVICE REQUEST MANAGER
# ─────────────────────────────────────────────────────────────
class ServiceRequestManager:
    """
    ITIL Service Request Management:
    Standard fulfilment items – password reset, software installs, etc.
    """

    def __init__(self, ticket_manager: TicketManager):
        self._tm = ticket_manager

    def raise_request(
        self,
        employee_name: str,
        department: str,
        description: str,
        requested_service: str = "General",
        category: str = "Access",
    ) -> ServiceRequest:
        ticket = self._tm.create_ticket(
            employee_name=     employee_name,
            department=        department,
            issue_description= description,
            category=          category,
            ticket_type=       "ServiceRequest",
            requested_service= requested_service,
        )
        logger.info(f"SERVICE REQUEST | id={ticket.ticket_id} | service={requested_service}")
        return ticket  # type: ignore[return-value]

    def approve_request(self, ticket_id: str) -> ServiceRequest:
        ticket = self._tm.get_ticket(ticket_id)
        if not isinstance(ticket, ServiceRequest):
            raise ValueError(f"Ticket {ticket_id} is not a ServiceRequest.")
        ticket.approve()
        logger.info(f"SERVICE REQUEST APPROVED | id={ticket_id}")
        return ticket

    def list_pending_requests(self) -> List[ServiceRequest]:
        return [
            t for t in self._tm.get_open_tickets()
            if isinstance(t, ServiceRequest) and not t.approved
        ]


# ─────────────────────────────────────────────────────────────
# PROBLEM MANAGER
# ─────────────────────────────────────────────────────────────
class ProblemManager:
    """
    ITIL Problem Management:
    If same issue occurs 5+ times → create ProblemRecord.
    Persists problem records to problems.json.
    """

    THRESHOLD = ProblemRecord.PROBLEM_THRESHOLD   # 5

    def __init__(self, ticket_manager: TicketManager):
        self._tm = ticket_manager
        self._problems: Dict[str, ProblemRecord] = {}
        self._load_problems()

    def _load_problems(self) -> None:
        raw_list = load_json(PROBLEMS_FILE, default=[])
        for raw in raw_list:
            try:
                prob = ProblemRecord._from_dict(raw)
                self._problems[prob.ticket_id] = prob
            except Exception as e:
                log_error("ProblemManager._load_problems", e)

    def _save_problems(self) -> None:
        save_json(PROBLEMS_FILE, [p.to_dict() for p in self._problems.values()])

    def analyse_repeat_issues(self) -> Dict[str, List[str]]:
        """
        Scan all tickets; group by normalised description keyword.
        Returns {keyword: [ticket_id, …]} for groups with 5+ tickets.
        """
        from utils import ISSUE_PRIORITY_MAP
        import re

        groups: Dict[str, List[str]] = defaultdict(list)
        for ticket in self._tm.get_all_tickets():
            desc = ticket.issue_description.lower()
            matched_key = "other"
            for keyword in ISSUE_PRIORITY_MAP:
                if re.search(re.escape(keyword), desc):
                    matched_key = keyword
                    break
            groups[matched_key].append(ticket.ticket_id)

        return {k: v for k, v in groups.items() if len(v) >= self.THRESHOLD}

    def create_problem_records(self) -> List[ProblemRecord]:
        """Auto-create ProblemRecords for repeat groups."""
        repeat_groups = self.analyse_repeat_issues()
        created = []
        for keyword, ticket_ids in repeat_groups.items():
            # Avoid duplicate problem records
            existing = any(
                keyword in p.issue_description for p in self._problems.values()
            )
            if existing:
                continue

            prob = self._tm.create_ticket(
                employee_name=     "Problem Management System",
                department=        "IT Operations",
                issue_description= f"PROBLEM RECORD: Repeated issue – '{keyword}' ({len(ticket_ids)} occurrences)",
                category=          "Other",
                priority=          "P2",
                ticket_type=       "Problem",
                related_tickets=   ticket_ids,
            )
            self._problems[prob.ticket_id] = prob  # type: ignore[assignment]
            created.append(prob)
            logger.warning(
                f"PROBLEM_RECORD CREATED | id={prob.ticket_id} | "
                f"keyword={keyword!r} | occurrences={len(ticket_ids)}"
            )

        self._save_problems()
        return created

    def set_root_cause(self, problem_id: str, cause: str) -> ProblemRecord:
        prob = self._problems.get(problem_id)
        if not prob:
            from utils import TicketNotFoundError
            raise TicketNotFoundError(problem_id)
        prob.set_root_cause(cause)
        self._save_problems()
        logger.info(f"ROOT_CAUSE SET | id={problem_id} | cause={cause[:60]}")
        return prob

    def list_problems(self) -> List[ProblemRecord]:
        return list(self._problems.values())


# ─────────────────────────────────────────────────────────────
# CHANGE MANAGER
# ─────────────────────────────────────────────────────────────
class ChangeRecord:
    """Lightweight change record (no full Ticket subclass needed)."""

    _counter = 0

    def __init__(self, title: str, description: str, requested_by: str, change_type: str = "Normal"):
        ChangeRecord._counter += 1
        self.change_id    = f"CHG-{now_iso()[:10].replace('-','')}-{ChangeRecord._counter:04d}"
        self.title        = title
        self.description  = description
        self.requested_by = requested_by
        self.change_type  = change_type   # Normal | Standard | Emergency
        self.status       = "Pending Approval"
        self.created_date = now_iso()
        self.approved_by: Optional[str] = None

    def approve(self, approver: str) -> None:
        self.approved_by = approver
        self.status = "Approved"

    def implement(self) -> None:
        self.status = "Implemented"

    def to_dict(self) -> Dict:
        return vars(self)

    def __str__(self) -> str:
        return (
            f"[{self.change_id}] {self.change_type} | {self.status} | "
            f"{self.title[:50]}"
        )


class ChangeManager:
    """ITIL Change Management: track updates, patches, requested changes."""

    def __init__(self):
        self._changes: List[ChangeRecord] = []

    def request_change(
        self,
        title: str,
        description: str,
        requested_by: str,
        change_type: str = "Normal",
    ) -> ChangeRecord:
        cr = ChangeRecord(title, description, requested_by, change_type)
        self._changes.append(cr)
        logger.info(f"CHANGE_REQUEST | id={cr.change_id} | type={change_type} | title={title[:40]}")
        return cr

    def approve_change(self, change_id: str, approver: str) -> ChangeRecord:
        cr = self._find(change_id)
        cr.approve(approver)
        logger.info(f"CHANGE_APPROVED | id={change_id} | by={approver}")
        return cr

    def implement_change(self, change_id: str) -> ChangeRecord:
        cr = self._find(change_id)
        cr.implement()
        logger.info(f"CHANGE_IMPLEMENTED | id={change_id}")
        return cr

    def list_changes(self, status: Optional[str] = None) -> List[ChangeRecord]:
        if status:
            return [c for c in self._changes if c.status == status]
        return list(self._changes)

    def _find(self, change_id: str) -> ChangeRecord:
        for c in self._changes:
            if c.change_id == change_id:
                return c
        raise KeyError(f"Change '{change_id}' not found.")

    def display_all(self) -> None:
        print(header_banner("CHANGE MANAGEMENT"))
        for cr in self._changes:
            print(f"  {cr}")
        print(divider())
