import csv
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import Counter

from tickets import TicketManager, Ticket
from utils import (
    count_by_field, filter_by_status, filter_by_priority,
    divider, header_banner, priority_label, now_iso, parse_dt,
    BACKUP_FILE, DATA_DIR,
)
from logger import logger, log_error


# ─────────────────────────────────────────────────────────────
# REPORT GENERATOR
# ─────────────────────────────────────────────────────────────
class ReportGenerator:

    REPORT_DIR = os.path.join(DATA_DIR, "reports")

    def __init__(self, ticket_manager: TicketManager):
        self._tm = ticket_manager
        os.makedirs(self.REPORT_DIR, exist_ok=True)

    # ── Helpers ───────────────────────────────────────────────
    @staticmethod
    def _resolution_minutes(ticket: Ticket) -> Optional[float]:
        """Return minutes from creation to close, or None if still open."""
        if ticket.closed_date:
            try:
                delta = parse_dt(ticket.closed_date) - parse_dt(ticket.created_date)
                return delta.total_seconds() / 60
            except Exception:
                return None
        return None

    @staticmethod
    def _tickets_today(tickets: List[Ticket]) -> List[Ticket]:
        today = datetime.now().date()
        return [
            t for t in tickets
            if parse_dt(t.created_date).date() == today
        ]

    @staticmethod
    def _tickets_in_month(tickets: List[Ticket], year: int, month: int) -> List[Ticket]:
        return [
            t for t in tickets
            if parse_dt(t.created_date).year == year
            and parse_dt(t.created_date).month == month
        ]

    # ── DAILY REPORT ─────────────────────────────────────────
    def daily_report(self, target_date: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a daily summary report.
        target_date: 'YYYY-MM-DD' string, defaults to today.
        """
        all_tickets = self._tm.get_all_tickets()

        if target_date:
            try:
                d = datetime.strptime(target_date, "%Y-%m-%d").date()
            except ValueError:
                d = datetime.now().date()
        else:
            d = datetime.now().date()

        day_tickets = [
            t for t in all_tickets
            if parse_dt(t.created_date).date() == d
        ]

        total       = len(day_tickets)
        open_count  = sum(1 for t in day_tickets if t.status not in ("Resolved", "Closed"))
        closed      = sum(1 for t in day_tickets if t.status == "Closed")
        resolved    = sum(1 for t in day_tickets if t.status == "Resolved")
        p1_count    = sum(1 for t in day_tickets if t.priority == "P1")
        breached    = sum(1 for t in day_tickets if t.is_sla_breached)

        by_category = count_by_field([t.to_dict() for t in day_tickets], "category")
        by_priority = count_by_field([t.to_dict() for t in day_tickets], "priority")

        report = {
            "report_type":    "Daily",
            "date":           str(d),
            "generated_at":   now_iso(),
            "total_tickets":  total,
            "open_tickets":   open_count,
            "closed_tickets": closed,
            "resolved_tickets": resolved,
            "high_priority_p1": p1_count,
            "sla_breaches":   breached,
            "by_category":    by_category,
            "by_priority":    by_priority,
        }
        logger.info(f"REPORT GENERATED | Daily | date={d} | total={total}")
        return report

    # ── MONTHLY REPORT ────────────────────────────────────────
    def monthly_report(self, year: Optional[int] = None, month: Optional[int] = None) -> Dict[str, Any]:
        """Generate a monthly analysis report."""
        now = datetime.now()
        year  = year  or now.year
        month = month or now.month

        all_tickets  = self._tm.get_all_tickets()
        month_tickets = self._tickets_in_month(all_tickets, year, month)

        total    = len(month_tickets)
        closed   = [t for t in month_tickets if t.status in ("Resolved", "Closed")]
        breached = [t for t in month_tickets if t.is_sla_breached]

        # Average resolution time
        res_times = [self._resolution_minutes(t) for t in closed]
        res_times  = [r for r in res_times if r is not None]
        avg_resolution = round(sum(res_times) / len(res_times), 1) if res_times else 0.0

        # Most common issue category
        cat_counter = Counter(t.category for t in month_tickets)
        most_common_issue = cat_counter.most_common(1)[0][0] if cat_counter else "N/A"

        # Department with most incidents
        dept_counter = Counter(t.department for t in month_tickets)
        top_dept = dept_counter.most_common(1)[0][0] if dept_counter else "N/A"

        # Repeated problems (issues with 5+ tickets)
        desc_counter = Counter(t.issue_description[:40] for t in month_tickets)
        repeated = {k: v for k, v in desc_counter.items() if v >= 3}

        report = {
            "report_type":         "Monthly",
            "year":                year,
            "month":               month,
            "generated_at":        now_iso(),
            "total_tickets":       total,
            "closed_tickets":      len(closed),
            "sla_breaches":        len(breached),
            "avg_resolution_min":  avg_resolution,
            "most_common_issue":   most_common_issue,
            "top_department":      top_dept,
            "category_breakdown":  dict(cat_counter),
            "dept_breakdown":      dict(dept_counter),
            "repeated_issues":     repeated,
        }
        logger.info(f"REPORT GENERATED | Monthly | {year}-{month:02d} | total={total}")
        return report

    # ── EXPORT ────────────────────────────────────────────────
    def export_daily_csv(self, report: Dict) -> str:
        """Write daily report to CSV; return filepath."""
        fname = os.path.join(
            self.REPORT_DIR, f"daily_{report['date']}.csv"
        )
        rows = [
            {"metric": k, "value": v}
            for k, v in report.items()
            if not isinstance(v, dict)
        ]
        try:
            with open(fname, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["metric", "value"])
                writer.writeheader()
                writer.writerows(rows)
            logger.info(f"REPORT EXPORTED | {fname}")
        except OSError as e:
            log_error("ReportGenerator.export_daily_csv", e)
        return fname

    def export_monthly_csv(self, report: Dict) -> str:
        """Write monthly report to CSV; return filepath."""
        fname = os.path.join(
            self.REPORT_DIR,
            f"monthly_{report['year']}_{report['month']:02d}.csv"
        )
        rows = [
            {"metric": k, "value": v}
            for k, v in report.items()
            if not isinstance(v, dict)
        ]
        try:
            with open(fname, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["metric", "value"])
                writer.writeheader()
                writer.writerows(rows)
            logger.info(f"REPORT EXPORTED | {fname}")
        except OSError as e:
            log_error("ReportGenerator.export_monthly_csv", e)
        return fname

    # ── DISPLAY ───────────────────────────────────────────────
    def print_daily_report(self, target_date: Optional[str] = None) -> None:
        r = self.daily_report(target_date)
        print(header_banner(f"DAILY REPORT – {r['date']}"))
        print(f"  Generated   : {r['generated_at']}")
        print(divider())
        print(f"  Total Tickets         : {r['total_tickets']}")
        print(f"  Open Tickets          : {r['open_tickets']}")
        print(f"  Closed Tickets        : {r['closed_tickets']}")
        print(f"  Resolved Tickets      : {r['resolved_tickets']}")
        print(f"  High Priority (P1)    : {r['high_priority_p1']}")
        print(f"  SLA Breaches          : {r['sla_breaches']}")
        print(divider())
        print("  By Category:")
        for cat, cnt in r["by_category"].items():
            print(f"    {cat:<20} {cnt}")
        print("  By Priority:")
        for pri, cnt in r["by_priority"].items():
            print(f"    {priority_label(pri):<22} {cnt}")
        print(divider("═"))

    def print_monthly_report(self, year=None, month=None) -> None:
        r = self.monthly_report(year, month)
        mname = datetime(r["year"], r["month"], 1).strftime("%B %Y")
        print(header_banner(f"MONTHLY REPORT – {mname}"))
        print(f"  Generated             : {r['generated_at']}")
        print(divider())
        print(f"  Total Tickets         : {r['total_tickets']}")
        print(f"  Closed Tickets        : {r['closed_tickets']}")
        print(f"  SLA Breaches          : {r['sla_breaches']}")
        print(f"  Avg Resolution Time   : {r['avg_resolution_min']} min")
        print(f"  Most Common Issue     : {r['most_common_issue']}")
        print(f"  Top Department        : {r['top_department']}")
        print(divider())
        print("  Category Breakdown:")
        for cat, cnt in r["category_breakdown"].items():
            bar = "█" * min(cnt * 3, 30)
            print(f"    {cat:<20} {bar} {cnt}")
        print(divider())
        if r["repeated_issues"]:
            print("  Repeated Issues (3+ tickets):")
            for desc, cnt in r["repeated_issues"].items():
                print(f"    [{cnt}x] {desc}")
        print(divider("═"))

    # ── Special Methods ───────────────────────────────────────
    def __str__(self) -> str:
        return (
            f"ReportGenerator | Total tickets: {len(self._tm)} | "
            f"Reports dir: {self.REPORT_DIR}"
        )

    def __repr__(self) -> str:
        return f"ReportGenerator(ticket_count={len(self._tm)})"
