import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from tickets   import TicketManager, IncidentTicket, ServiceRequest, ProblemRecord
from itil      import IncidentManager, ServiceRequestManager, ProblemManager, ChangeManager, SLAManager
from monitor   import Monitor
from reports   import ReportGenerator
from logger    import logger
from utils     import (
    divider, header_banner, priority_label,
    ITILError, TicketNotFoundError, EmptyValueError,
    InvalidPriorityError, InvalidStatusError,
)


# ─────────────────────────────────────────────────────────────
# APPLICATION BOOTSTRAP
# ─────────────────────────────────────────────────────────────
def bootstrap():
    """Initialise all managers and return them."""
    tm   = TicketManager()
    im   = IncidentManager(tm)
    srm  = ServiceRequestManager(tm)
    pm   = ProblemManager(tm)
    cm   = ChangeManager()
    slam = SLAManager(tm)
    mon  = Monitor(ticket_manager=tm)
    rg   = ReportGenerator(tm)
    return tm, im, srm, pm, cm, slam, mon, rg


# ─────────────────────────────────────────────────────────────
# INPUT HELPERS
# ─────────────────────────────────────────────────────────────
def prompt(label: str, required: bool = True) -> str:
    while True:
        val = input(f"  {label}: ").strip()
        if val or not required:
            return val
        print("  ⚠️  This field is required.")


def choose(label: str, options: list) -> str:
    print(f"\n  {label}")
    for i, opt in enumerate(options, 1):
        print(f"    {i}. {opt}")
    while True:
        raw = input("  Enter number: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("  Invalid choice, try again.")


def press_enter():
    input("\n  Press ENTER to continue…")


# ─────────────────────────────────────────────────────────────
# TICKET MANAGEMENT MENUS
# ─────────────────────────────────────────────────────────────
def menu_create_ticket(tm: TicketManager) -> None:
    print(header_banner("CREATE NEW TICKET"))
    try:
        name   = prompt("Employee Name")
        dept   = prompt("Department")
        desc   = prompt("Issue Description")
        cat    = choose("Category", ["Hardware", "Software", "Network", "Security", "Access", "Performance", "Other"])
        ttype  = choose("Ticket Type", ["Incident", "ServiceRequest"])
        pri    = choose("Priority (or ENTER for auto)", ["P1", "P2", "P3", "P4", "Auto"])
        priority = None if pri == "Auto" else pri

        kwargs = {}
        if ttype == "Incident":
            impact  = choose("Impact",  ["Low", "Medium", "High"])
            urgency = choose("Urgency", ["Low", "Medium", "High"])
            kwargs  = {"impact": impact, "urgency": urgency}
        elif ttype == "ServiceRequest":
            svc = prompt("Requested Service (e.g. Password Reset)")
            kwargs = {"requested_service": svc}

        ticket = tm.create_ticket(
            employee_name=     name,
            department=        dept,
            issue_description= desc,
            category=          cat,
            priority=          priority,
            ticket_type=       ttype,
            **kwargs,
        )
        print(f"\n  ✅ Ticket Created: {ticket}")
    except ITILError as e:
        print(f"\n  ❌ {e}")
    press_enter()


def menu_view_all_tickets(tm: TicketManager) -> None:
    print(header_banner("ALL TICKETS"))
    tickets = tm.sorted_by_priority()
    if not tickets:
        print("  No tickets found.")
    else:
        for t in tickets:
            print(f"  {t}")
    print(divider())
    press_enter()


def menu_search_ticket(tm: TicketManager) -> None:
    print(header_banner("SEARCH TICKET"))
    method = choose("Search by", ["Ticket ID", "Employee Name", "Status", "Priority"])
    try:
        if method == "Ticket ID":
            tid = prompt("Ticket ID")
            t   = tm.get_ticket(tid)
            print(f"\n  {t}")
            d   = t.to_dict()
            for k, v in d.items():
                print(f"    {k:<22}: {v}")

        elif method == "Employee Name":
            name    = prompt("Employee Name (partial ok)")
            results = tm.search_by_employee(name)
            print(f"\n  Found {len(results)} ticket(s):")
            for t in results:
                print(f"  {t}")

        elif method == "Status":
            status  = choose("Status", ["Open", "In Progress", "Escalated", "Resolved", "Closed"])
            results = tm.search_by_status(status)
            print(f"\n  Found {len(results)} ticket(s) with status={status}:")
            for t in results:
                print(f"  {t}")

        elif method == "Priority":
            pri     = choose("Priority", ["P1", "P2", "P3", "P4"])
            results = tm.search_by_priority(pri)
            print(f"\n  Found {len(results)} ticket(s) with {priority_label(pri)}:")
            for t in results:
                print(f"  {t}")

    except TicketNotFoundError as e:
        print(f"\n  ❌ {e}")
    press_enter()


def menu_update_ticket(tm: TicketManager) -> None:
    print(header_banner("UPDATE TICKET STATUS"))
    try:
        tid    = prompt("Ticket ID")
        status = choose("New Status", ["Open", "In Progress", "Escalated", "Resolved", "Closed"])
        note   = prompt("Resolution Note (optional)", required=False)
        ticket = tm.update_status(tid, status, note)
        print(f"\n  ✅ Updated: {ticket}")
    except ITILError as e:
        print(f"\n  ❌ {e}")
    press_enter()


def menu_close_ticket(tm: TicketManager) -> None:
    print(header_banner("CLOSE TICKET"))
    try:
        tid        = prompt("Ticket ID")
        resolution = prompt("Resolution Details")
        ticket     = tm.close_ticket(tid, resolution)
        print(f"\n  ✅ Closed: {ticket}")
    except ITILError as e:
        print(f"\n  ❌ {e}")
    press_enter()


def menu_delete_ticket(tm: TicketManager) -> None:
    print(header_banner("DELETE TICKET"))
    try:
        tid = prompt("Ticket ID to DELETE")
        confirm = input(f"  ⚠️  Are you sure you want to delete {tid}? (yes/no): ").strip().lower()
        if confirm == "yes":
            tm.delete_ticket(tid)
            print(f"\n  ✅ Ticket {tid} deleted.")
        else:
            print("  Cancelled.")
    except ITILError as e:
        print(f"\n  ❌ {e}")
    press_enter()


# ─────────────────────────────────────────────────────────────
# SLA MENU
# ─────────────────────────────────────────────────────────────
def menu_sla(slam: SLAManager) -> None:
    print(header_banner("SLA MANAGEMENT"))
    slam.display_sla_report()
    breached = slam.get_breached_tickets()
    print(f"\n  Breached Tickets: {len(breached)}")
    warnings = slam.generate_warnings()
    for w in warnings:
        print(f"  {w}")
    escalated = slam.escalate_breached()
    if escalated:
        print(f"\n  🔺 Escalated {len(escalated)} ticket(s).")
    press_enter()


# ─────────────────────────────────────────────────────────────
# INCIDENT MENU
# ─────────────────────────────────────────────────────────────
def menu_incident(im: IncidentManager) -> None:
    while True:
        print(header_banner("INCIDENT MANAGEMENT"))
        print("  1. Raise Incident")
        print("  2. Resolve Incident")
        print("  3. List Active Incidents")
        print("  4. Escalate P1 Incidents")
        print("  0. Back")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            print(header_banner("RAISE INCIDENT"))
            try:
                ticket = im.raise_incident(
                    employee_name= prompt("Employee Name"),
                    department=    prompt("Department"),
                    description=   prompt("Issue Description"),
                    category=      choose("Category", ["Hardware", "Software", "Network", "Performance", "Other"]),
                    impact=        choose("Impact", ["Low", "Medium", "High"]),
                    urgency=       choose("Urgency", ["Low", "Medium", "High"]),
                )
                print(f"\n  ✅ {ticket}")
            except ITILError as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "2":
            tid = prompt("Ticket ID")
            res = prompt("Resolution")
            try:
                im.resolve_incident(tid, res)
                print("  ✅ Incident resolved.")
            except ITILError as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "3":
            active = im.list_active_incidents()
            print(f"\n  Active incidents: {len(active)}")
            for t in active:
                print(f"  {t}")
            press_enter()

        elif choice == "4":
            esc = im.escalate_p1_incidents()
            print(f"\n  Escalated {len(esc)} P1 incidents.")
            press_enter()

        elif choice == "0":
            break


# ─────────────────────────────────────────────────────────────
# SERVICE REQUEST MENU
# ─────────────────────────────────────────────────────────────
def menu_service_request(srm: ServiceRequestManager) -> None:
    while True:
        print(header_banner("SERVICE REQUEST MANAGEMENT"))
        print("  1. Raise Service Request")
        print("  2. Approve Service Request")
        print("  3. List Pending Requests")
        print("  0. Back")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            try:
                ticket = srm.raise_request(
                    employee_name=     prompt("Employee Name"),
                    department=        prompt("Department"),
                    description=       prompt("Issue Description"),
                    requested_service= prompt("Requested Service"),
                )
                print(f"\n  ✅ {ticket}")
            except ITILError as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "2":
            tid = prompt("Ticket ID")
            try:
                t = srm.approve_request(tid)
                print(f"\n  ✅ Approved: {t}")
            except (ITILError, ValueError) as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "3":
            pending = srm.list_pending_requests()
            print(f"\n  Pending requests: {len(pending)}")
            for t in pending:
                print(f"  {t}")
            press_enter()

        elif choice == "0":
            break


# ─────────────────────────────────────────────────────────────
# PROBLEM MENU
# ─────────────────────────────────────────────────────────────
def menu_problem(pm: ProblemManager) -> None:
    while True:
        print(header_banner("PROBLEM MANAGEMENT"))
        print("  1. Analyse Repeat Issues & Create Problem Records")
        print("  2. Set Root Cause")
        print("  3. List Problem Records")
        print("  0. Back")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            created = pm.create_problem_records()
            print(f"\n  Created {len(created)} problem record(s).")
            for p in created:
                print(f"  {p}")
            press_enter()

        elif choice == "2":
            pid   = prompt("Problem Record ID")
            cause = prompt("Root Cause Description")
            try:
                p = pm.set_root_cause(pid, cause)
                print(f"\n  ✅ Root cause set for {p.ticket_id}")
            except Exception as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "3":
            probs = pm.list_problems()
            print(f"\n  Problem Records: {len(probs)}")
            for p in probs:
                print(f"  {p}")
            press_enter()

        elif choice == "0":
            break


# ─────────────────────────────────────────────────────────────
# CHANGE MANAGEMENT MENU
# ─────────────────────────────────────────────────────────────
def menu_change(cm: ChangeManager) -> None:
    while True:
        print(header_banner("CHANGE MANAGEMENT"))
        print("  1. Request Change")
        print("  2. Approve Change")
        print("  3. Mark Change Implemented")
        print("  4. View All Changes")
        print("  0. Back")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            cr = cm.request_change(
                title=        prompt("Change Title"),
                description=  prompt("Description"),
                requested_by= prompt("Requested By"),
                change_type=  choose("Change Type", ["Normal", "Standard", "Emergency"]),
            )
            print(f"\n  ✅ {cr}")
            press_enter()

        elif choice == "2":
            cid      = prompt("Change ID")
            approver = prompt("Approver Name")
            try:
                cr = cm.approve_change(cid, approver)
                print(f"\n  ✅ {cr}")
            except KeyError as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "3":
            cid = prompt("Change ID")
            try:
                cr = cm.implement_change(cid)
                print(f"\n  ✅ {cr}")
            except KeyError as e:
                print(f"\n  ❌ {e}")
            press_enter()

        elif choice == "4":
            cm.display_all()
            press_enter()

        elif choice == "0":
            break


# ─────────────────────────────────────────────────────────────
# MONITORING MENU
# ─────────────────────────────────────────────────────────────
def menu_monitor(mon: Monitor) -> None:
    while True:
        print(header_banner("SYSTEM MONITORING"))
        print("  1. Live Dashboard (single snapshot)")
        print("  2. Run 5 samples (5-second interval)")
        print("  3. View Metric History")
        print("  4. System Info")
        print("  0. Back")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            mon.display_dashboard()
            press_enter()

        elif choice == "2":
            print("\n  Running 5 metric samples (5s each) …")
            for snap in mon.metric_stream(interval_seconds=5, count=5):
                print(f"  {snap.summary_line()}")
                alerts = snap.alerts()
                if alerts:
                    print(f"  ⚠️  ALERT: {[a[0] for a in alerts]}")
            press_enter()

        elif choice == "3":
            history = mon.get_history()
            print(f"\n  History ({len(history)} snapshots):")
            for snap in history[-10:]:
                print(f"  {snap.summary_line()}")
            press_enter()

        elif choice == "4":
            info = Monitor.system_info()
            print("\n  System Information:")
            for k, v in info.items():
                print(f"    {k:<18}: {v}")
            press_enter()

        elif choice == "0":
            break


# ─────────────────────────────────────────────────────────────
# REPORTS MENU
# ─────────────────────────────────────────────────────────────
def menu_reports(rg: ReportGenerator) -> None:
    while True:
        print(header_banner("REPORTS"))
        print("  1. Daily Report (today)")
        print("  2. Monthly Report (this month)")
        print("  3. Export Daily Report to CSV")
        print("  4. Export Monthly Report to CSV")
        print("  0. Back")
        choice = input("\n  Choice: ").strip()

        if choice == "1":
            rg.print_daily_report()
            press_enter()

        elif choice == "2":
            rg.print_monthly_report()
            press_enter()

        elif choice == "3":
            report = rg.daily_report()
            path   = rg.export_daily_csv(report)
            print(f"\n  ✅ Exported: {path}")
            press_enter()

        elif choice == "4":
            report = rg.monthly_report()
            path   = rg.export_monthly_csv(report)
            print(f"\n  ✅ Exported: {path}")
            press_enter()

        elif choice == "0":
            break


# ─────────────────────────────────────────────────────────────
# BACKUP
# ─────────────────────────────────────────────────────────────
def menu_backup(tm: TicketManager) -> None:
    print(header_banner("BACKUP"))
    count = tm.backup_to_csv()
    print(f"\n  ✅ Backup complete — {count} tickets written to backup.csv")
    press_enter()


# ─────────────────────────────────────────────────────────────
# MAIN MENU
# ─────────────────────────────────────────────────────────────
MAIN_MENU = """
╔══════════════════════════════════════════════════════╗
║       SMART IT SERVICE DESK  —  ITIL SYSTEM          ║
╚══════════════════════════════════════════════════════╝
  1.  Ticket Management
  2.  SLA Tracking
  3.  Incident Management
  4.  Service Request Management
  5.  Problem Management
  6.  Change Management
  7.  System Monitoring
  8.  Reports
  9.  Backup to CSV
  0.  Exit
"""

TICKET_MENU = """
  ── TICKET MANAGEMENT ──────────────────────
  1. Create Ticket
  2. View All Tickets
  3. Search Ticket
  4. Update Ticket Status
  5. Close Ticket
  6. Delete Ticket
  7. SLA Status (quick view)
  0. Back
"""


def main():
    print("\n  🚀 Starting Smart IT Service Desk …")
    tm, im, srm, pm, cm, slam, mon, rg = bootstrap()
    print(f"  Loaded {len(tm)} existing ticket(s).\n")
    logger.info("Application started.")

    while True:
        print(MAIN_MENU)
        choice = input("  Enter choice: ").strip()

        if choice == "1":
            while True:
                print(TICKET_MENU)
                tc = input("  Choice: ").strip()
                if tc == "1": menu_create_ticket(tm)
                elif tc == "2": menu_view_all_tickets(tm)
                elif tc == "3": menu_search_ticket(tm)
                elif tc == "4": menu_update_ticket(tm)
                elif tc == "5": menu_close_ticket(tm)
                elif tc == "6": menu_delete_ticket(tm)
                elif tc == "7": tm.display_sla_status()
                elif tc == "0": break

        elif choice == "2": menu_sla(slam)
        elif choice == "3": menu_incident(im)
        elif choice == "4": menu_service_request(srm)
        elif choice == "5": menu_problem(pm)
        elif choice == "6": menu_change(cm)
        elif choice == "7": menu_monitor(mon)
        elif choice == "8": menu_reports(rg)
        elif choice == "9": menu_backup(tm)
        elif choice == "0":
            logger.info("Application exited normally.")
            print("\n  Goodbye! 👋\n")
            sys.exit(0)
        else:
            print("  Invalid option, try again.")


if __name__ == "__main__":
    main()
