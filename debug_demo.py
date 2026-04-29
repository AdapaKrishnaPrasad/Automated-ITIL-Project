import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from tickets import TicketManager

tm = TicketManager()

# This will hit your breakpoint
t = tm.create_ticket(
    employee_name="Debug User",
    department="IT",
    issue_description="Server is down",
    category="Hardware",
    priority="P1",
    ticket_type="Incident",
)

print(f"Created: {t}")