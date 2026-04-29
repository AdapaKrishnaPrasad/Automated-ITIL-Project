import os
import sys
import json
import unittest
import tempfile
import shutil
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(__file__))

import utils
from utils import (
    infer_priority, generate_ticket_id, validate_priority,
    validate_status, validate_non_empty, load_json, save_json,
    TicketNotFoundError, DuplicateTicketError, EmptyValueError,
    InvalidPriorityError, InvalidStatusError, FileOperationError,
    SLA_RULES,
)
from tickets import (
    Ticket, IncidentTicket, ServiceRequest, ProblemRecord, TicketManager
)
from monitor import Monitor, MetricSnapshot
from itil import SLAManager, ProblemManager


# ═══════════════════════════════════════════════════════════════
# 1. TICKET CREATION TESTS
# ═══════════════════════════════════════════════════════════════
class TestTicketCreation(unittest.TestCase):
    """Test all aspects of ticket creation and OOP structure."""

    def setUp(self):
        """Create a fresh temp directory and mock TICKETS_FILE for each test."""
        self.tmp = tempfile.mkdtemp()
        self.tickets_file = os.path.join(self.tmp, "tickets.json")
        # Patch the file path used by TicketManager
        patcher = patch("tickets.TICKETS_FILE", self.tickets_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tm = TicketManager()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_basic_incident(self):
        t = self.tm.create_ticket(
            employee_name="Alice",
            department="IT",
            issue_description="Server is down",
            category="Hardware",
            priority="P1",
            ticket_type="Incident",
        )
        self.assertIsInstance(t, IncidentTicket)
        self.assertEqual(t.priority, "P1")
        self.assertEqual(t.status, "Open")

    def test_create_service_request(self):
        t = self.tm.create_ticket(
            employee_name="Bob",
            department="HR",
            issue_description="Need password reset",
            category="Access",
            ticket_type="ServiceRequest",
        )
        self.assertIsInstance(t, ServiceRequest)
        self.assertFalse(t.approved)

    def test_create_problem_record(self):
        t = self.tm.create_ticket(
            employee_name="System",
            department="Ops",
            issue_description="Repeated disk full across servers",
            category="Performance",
            ticket_type="Problem",
            related_tickets=["TKT-001", "TKT-002"],
        )
        self.assertIsInstance(t, ProblemRecord)
        self.assertEqual(len(t.related_tickets), 2)

    def test_ticket_has_unique_id(self):
        t1 = self.tm.create_ticket("Alice", "IT", "Issue A", "Hardware", "P1")
        t2 = self.tm.create_ticket("Bob", "HR", "Issue B", "Software", "P2")
        self.assertNotEqual(t1.ticket_id, t2.ticket_id)

    def test_ticket_id_format(self):
        tid = generate_ticket_id()
        self.assertTrue(tid.startswith("TKT-"))
        parts = tid.split("-")
        self.assertEqual(len(parts), 3)

    def test_ticket_str_representation(self):
        t = IncidentTicket(
            employee_name="Carol", department="Finance",
            issue_description="App crash", category="Software", priority="P2",
        )
        s = str(t)
        self.assertIn("P2", s)
        self.assertIn("Carol", s)

    def test_ticket_eq(self):
        t1 = IncidentTicket("A", "IT", "Issue", "Hardware", "P1", ticket_id="TKT-SAME-0001")
        t2 = IncidentTicket("B", "HR", "Other", "Software", "P2", ticket_id="TKT-SAME-0001")
        self.assertEqual(t1, t2)

    def test_ticket_lt_sorting(self):
        t1 = IncidentTicket("A", "IT", "Issue", "Hardware", priority="P1")
        t2 = IncidentTicket("B", "HR", "Issue", "Software", priority="P3")
        self.assertLess(t1, t2)
        self.assertEqual(sorted([t2, t1])[0], t1)

    def test_ticket_counter_increments(self):
        before = Ticket.get_ticket_count()
        IncidentTicket("X", "Y", "Desc", "Hardware", priority="P1")
        after = Ticket.get_ticket_count()
        self.assertGreater(after, before)

    def test_incident_escalate(self):
        t = IncidentTicket("A", "IT", "Server down", "Hardware", priority="P1")
        t.escalate()
        self.assertEqual(t.status, "Escalated")
        self.assertEqual(t.escalation_count, 1)

    def test_service_request_approve(self):
        t = ServiceRequest("A", "HR", "Password reset", "Access", priority="P4")
        t.approve()
        self.assertTrue(t.approved)
        self.assertEqual(t.status, "In Progress")

    def test_problem_set_root_cause(self):
        t = ProblemRecord("Sys", "Ops", "Disk full", "Performance", priority="P2")
        t.set_root_cause("Log rotation not configured")
        self.assertTrue(t.known_error)
        self.assertIn("Log rotation", t.root_cause)

    def test_ticket_to_dict_roundtrip(self):
        t = IncidentTicket("Alice", "IT", "Network down", "Network", priority="P2",
                           impact="High", urgency="Medium")
        d = t.to_dict()
        t2 = Ticket.from_dict(d)
        self.assertEqual(t2.ticket_id, t.ticket_id)
        self.assertEqual(t2.priority, "P2")

    def test_total_tickets_in_manager(self):
        self.tm.create_ticket("A", "IT", "Issue 1", "Hardware", "P1")
        self.tm.create_ticket("B", "HR", "Issue 2", "Software", "P2")
        self.assertEqual(len(self.tm), 2)


# ═══════════════════════════════════════════════════════════════
# 2. PRIORITY LOGIC TESTS
# ═══════════════════════════════════════════════════════════════
class TestPriorityLogic(unittest.TestCase):
    """Test priority inference and validation."""

    def test_server_down_is_p1(self):
        self.assertEqual(infer_priority("Server is down"), "P1")

    def test_internet_down_is_p2(self):
        self.assertEqual(infer_priority("Internet down in office"), "P2")

    def test_laptop_slow_is_p3(self):
        self.assertEqual(infer_priority("My laptop slow today"), "P3")

    def test_password_reset_is_p4(self):
        self.assertEqual(infer_priority("Need a password reset ASAP"), "P4")

    def test_unknown_defaults_to_p3(self):
        self.assertEqual(infer_priority("Some random issue"), "P3")

    def test_validate_priority_valid(self):
        for p in ["P1", "P2", "P3", "P4"]:
            self.assertEqual(validate_priority(p), p)

    def test_validate_priority_lowercase(self):
        self.assertEqual(validate_priority("p1"), "P1")

    def test_validate_priority_invalid(self):
        with self.assertRaises(InvalidPriorityError):
            validate_priority("P5")

    def test_auto_priority_assigned_on_creation(self):
        t = IncidentTicket("A", "IT", "server down and network failure", "Network")
        # server down → P1
        self.assertEqual(t.priority, "P1")

    def test_explicit_priority_overrides_inference(self):
        t = IncidentTicket("A", "IT", "server down", "Hardware", priority="P4")
        self.assertEqual(t.priority, "P4")

    def test_priority_label_includes_emoji(self):
        from utils import priority_label
        label = priority_label("P1")
        self.assertIn("P1", label)
        self.assertIn("🔴", label)


# ═══════════════════════════════════════════════════════════════
# 3. SLA BREACH TESTS
# ═══════════════════════════════════════════════════════════════
class TestSLABreach(unittest.TestCase):
    """Test SLA tracking, breach detection, and escalation."""

    def _make_ticket(self, priority: str, minutes_ago: float) -> IncidentTicket:
        """Create a ticket with a backdated created_date."""
        past = datetime.now() - timedelta(minutes=minutes_ago)
        t = IncidentTicket(
            employee_name="Test User",
            department="IT",
            issue_description="Test issue",
            category="Hardware",
            priority=priority,
        )
        t.created_date = past.isoformat()
        return t

    def test_p1_sla_limit_is_60_min(self):
        self.assertEqual(SLA_RULES["P1"], 60)

    def test_p2_sla_limit_is_240_min(self):
        self.assertEqual(SLA_RULES["P2"], 240)

    def test_p3_sla_limit_is_480_min(self):
        self.assertEqual(SLA_RULES["P3"], 480)

    def test_p4_sla_limit_is_1440_min(self):
        self.assertEqual(SLA_RULES["P4"], 1440)

    def test_sla_not_breached_within_time(self):
        t = self._make_ticket("P1", minutes_ago=30)
        self.assertFalse(t.is_sla_breached)

    def test_sla_breached_after_limit(self):
        t = self._make_ticket("P1", minutes_ago=90)   # P1 limit = 60
        self.assertTrue(t.is_sla_breached)

    def test_resolved_ticket_not_breached(self):
        t = self._make_ticket("P1", minutes_ago=90)
        t.status = "Resolved"
        self.assertFalse(t.is_sla_breached)

    def test_remaining_minutes_decreases(self):
        t = self._make_ticket("P2", minutes_ago=200)  # P2 limit = 240
        remaining = t.remaining_sla_minutes
        self.assertAlmostEqual(remaining, 40, delta=2)

    def test_elapsed_minutes_increases(self):
        t = self._make_ticket("P3", minutes_ago=100)
        self.assertGreater(t.elapsed_minutes, 99)

    def test_sla_manager_detects_breach(self):
        tmp = tempfile.mkdtemp()
        tickets_file = os.path.join(tmp, "tickets.json")
        with patch("tickets.TICKETS_FILE", tickets_file):
            tm = TicketManager()
            # Manually inject a breached ticket
            t = self._make_ticket("P1", minutes_ago=120)
            tm._tickets[t.ticket_id] = t
            slam = SLAManager(tm)
            breached = slam.get_breached_tickets()
            self.assertIn(t, breached)
        shutil.rmtree(tmp)


# ═══════════════════════════════════════════════════════════════
# 4. AUTO MONITORING TICKET CREATION TESTS
# ═══════════════════════════════════════════════════════════════
class TestAutoMonitoring(unittest.TestCase):
    """Test that Monitor auto-creates P1 tickets on threshold breach."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tickets_file = os.path.join(self.tmp, "tickets.json")
        patcher = patch("tickets.TICKETS_FILE", self.tickets_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tm = TicketManager()
        self.mon = Monitor(ticket_manager=self.tm)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_alert_triggered_for_high_cpu(self):
        snap = MetricSnapshot(
            timestamp="2024-01-01T10:00:00",
            cpu_percent=95.0, memory_percent=50.0,
            disk_percent=40.0, disk_free_gb=100.0,
            net_sent_mbps=1.0, net_recv_mbps=1.0,
        )
        alerts = snap.alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0][0], "cpu")

    def test_alert_triggered_for_high_memory(self):
        snap = MetricSnapshot(
            timestamp="2024-01-01T10:00:00",
            cpu_percent=50.0, memory_percent=97.0,
            disk_percent=40.0, disk_free_gb=100.0,
            net_sent_mbps=1.0, net_recv_mbps=1.0,
        )
        alerts = snap.alerts()
        names = [a[0] for a in alerts]
        self.assertIn("memory", names)

    def test_alert_triggered_for_full_disk(self):
        snap = MetricSnapshot(
            timestamp="2024-01-01T10:00:00",
            cpu_percent=50.0, memory_percent=50.0,
            disk_percent=92.0, disk_free_gb=5.0,   # >90% used
            net_sent_mbps=1.0, net_recv_mbps=1.0,
        )
        alerts = snap.alerts()
        names = [a[0] for a in alerts]
        self.assertIn("disk", names)

    def test_no_alert_within_thresholds(self):
        snap = MetricSnapshot(
            timestamp="2024-01-01T10:00:00",
            cpu_percent=50.0, memory_percent=60.0,
            disk_percent=40.0, disk_free_gb=200.0,
            net_sent_mbps=1.0, net_recv_mbps=1.0,
        )
        self.assertEqual(len(snap.alerts()), 0)

    def test_auto_ticket_created_on_cpu_alert(self):
        before = len(self.tm)
        self.mon._auto_create_ticket("cpu", 95.0)
        after  = len(self.tm)
        self.assertEqual(after - before, 1)

    def test_auto_ticket_is_p1(self):
        self.mon._auto_create_ticket("memory", 97.0)
        tickets = self.tm.search_by_priority("P1")
        self.assertTrue(any("MEMORY" in t.issue_description.upper() for t in tickets))

    def test_system_info_returns_dict(self):
        info = Monitor.system_info()
        self.assertIsInstance(info, dict)
        self.assertIn("platform", info)


# ═══════════════════════════════════════════════════════════════
# 5. FILE READ/WRITE TESTS
# ═══════════════════════════════════════════════════════════════
class TestFileHandling(unittest.TestCase):
    """Test JSON and CSV file operations."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_and_load_json(self):
        path = os.path.join(self.tmp, "test.json")
        data = [{"id": "T1", "status": "Open"}, {"id": "T2", "status": "Closed"}]
        save_json(path, data)
        loaded = load_json(path)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["id"], "T1")

    def test_load_missing_json_returns_default(self):
        path = os.path.join(self.tmp, "nonexistent.json")
        result = load_json(path, default=[])
        self.assertEqual(result, [])

    def test_load_malformed_json_raises(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as f:
            f.write("{this is not valid json}")
        with self.assertRaises(FileOperationError):
            load_json(path)

    def test_tickets_persist_to_json(self):
        tickets_file = os.path.join(self.tmp, "tickets.json")
        with patch("tickets.TICKETS_FILE", tickets_file):
            tm = TicketManager()
            tm.create_ticket("Alice", "IT", "Server down", "Hardware", "P1")
            tm2 = TicketManager()   # reload fresh
            self.assertEqual(len(tm2), 1)

    def test_backup_csv_created(self):
        tickets_file = os.path.join(self.tmp, "tickets.json")
        backup_file  = os.path.join(self.tmp, "backup.csv")
        with patch("tickets.TICKETS_FILE", tickets_file), \
             patch("tickets.BACKUP_FILE",  backup_file):
            tm = TicketManager()
            tm.create_ticket("Bob", "HR", "Printer issue", "Hardware", "P3")
            count = tm.backup_to_csv()
            self.assertEqual(count, 1)
            self.assertTrue(os.path.isfile(backup_file))

    def test_csv_contains_correct_data(self):
        import csv as csvmod
        tickets_file = os.path.join(self.tmp, "tickets.json")
        backup_file  = os.path.join(self.tmp, "backup.csv")
        with patch("tickets.TICKETS_FILE", tickets_file), \
             patch("tickets.BACKUP_FILE",  backup_file):
            tm = TicketManager()
            tm.create_ticket("Carol", "Finance", "App crash", "Software", "P2")
            tm.backup_to_csv()
            with open(backup_file, newline="") as f:
                rows = list(csvmod.DictReader(f))
            self.assertEqual(rows[0]["employee_name"], "Carol")


# ═══════════════════════════════════════════════════════════════
# 6. SEARCH TICKET TESTS
# ═══════════════════════════════════════════════════════════════
class TestSearchTicket(unittest.TestCase):
    """Test all search operations on TicketManager."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tickets_file = os.path.join(self.tmp, "tickets.json")
        patcher = patch("tickets.TICKETS_FILE", self.tickets_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tm = TicketManager()
        self.t1 = self.tm.create_ticket("Alice Smith", "IT",      "Server down",    "Hardware", "P1")
        self.t2 = self.tm.create_ticket("Bob Jones",   "HR",      "Password reset", "Access",   "P4")
        self.t3 = self.tm.create_ticket("Alice Wong",  "Finance", "App crash",      "Software", "P2")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_search_by_id_found(self):
        result = self.tm.search_by_id(self.t1.ticket_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.ticket_id, self.t1.ticket_id)

    def test_search_by_id_not_found(self):
        result = self.tm.search_by_id("TKT-INVALID-XXXX")
        self.assertIsNone(result)

    def test_get_ticket_raises_for_missing(self):
        with self.assertRaises(TicketNotFoundError):
            self.tm.get_ticket("TKT-NOT-EXIST")

    def test_search_by_employee_partial(self):
        results = self.tm.search_by_employee("alice")
        self.assertEqual(len(results), 2)

    def test_search_by_employee_full_name(self):
        results = self.tm.search_by_employee("Bob Jones")
        self.assertEqual(len(results), 1)

    def test_search_by_status_open(self):
        results = self.tm.search_by_status("Open")
        self.assertEqual(len(results), 3)

    def test_search_by_priority_p1(self):
        results = self.tm.search_by_priority("P1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].employee_name, "Alice Smith")

    def test_sorted_by_priority(self):
        sorted_list = self.tm.sorted_by_priority()
        priorities  = [t.priority for t in sorted_list]
        self.assertEqual(priorities, sorted(priorities))

    def test_sorted_by_date(self):
        sorted_list = self.tm.sorted_by_date(reverse=True)
        self.assertGreaterEqual(
            sorted_list[0].created_date,
            sorted_list[-1].created_date,
        )

    def test_get_open_tickets(self):
        open_list = self.tm.get_open_tickets()
        self.assertEqual(len(open_list), 3)
        self.tm.update_status(self.t1.ticket_id, "Closed")
        open_list2 = self.tm.get_open_tickets()
        self.assertEqual(len(open_list2), 2)


# ═══════════════════════════════════════════════════════════════
# 7. EXCEPTION HANDLING TESTS
# ═══════════════════════════════════════════════════════════════
class TestExceptionHandling(unittest.TestCase):
    """Test all custom exceptions and edge-case error handling."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tickets_file = os.path.join(self.tmp, "tickets.json")
        patcher = patch("tickets.TICKETS_FILE", self.tickets_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tm = TicketManager()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # Empty values
    def test_empty_employee_name_raises(self):
        with self.assertRaises(EmptyValueError):
            IncidentTicket("", "IT", "Issue", "Hardware", priority="P1")

    def test_empty_department_raises(self):
        with self.assertRaises(EmptyValueError):
            IncidentTicket("Alice", "", "Issue", "Hardware", priority="P1")

    def test_empty_description_raises(self):
        with self.assertRaises(EmptyValueError):
            IncidentTicket("Alice", "IT", "", "Hardware", priority="P1")

    # Invalid priority
    def test_invalid_priority_raises(self):
        with self.assertRaises(InvalidPriorityError):
            validate_priority("P9")

    def test_invalid_priority_on_ticket(self):
        with self.assertRaises(InvalidPriorityError):
            IncidentTicket("Alice", "IT", "Issue", "Hardware", priority="CRITICAL")

    # Invalid status
    def test_invalid_status_raises(self):
        with self.assertRaises(InvalidStatusError):
            validate_status("Pending")   # not in VALID_STATUSES

    def test_valid_status_accepted(self):
        for s in ["Open", "In Progress", "Escalated", "Resolved", "Closed"]:
            self.assertEqual(validate_status(s), s)

    # Ticket not found
    def test_get_nonexistent_ticket_raises(self):
        with self.assertRaises(TicketNotFoundError):
            self.tm.get_ticket("TKT-GHOST-0000")

    def test_update_nonexistent_ticket_raises(self):
        with self.assertRaises(TicketNotFoundError):
            self.tm.update_status("TKT-GHOST-0000", "Closed")

    def test_delete_nonexistent_ticket_raises(self):
        with self.assertRaises(TicketNotFoundError):
            self.tm.delete_ticket("TKT-GHOST-0000")

    # Validate non-empty
    def test_validate_non_empty_strips_whitespace(self):
        result = validate_non_empty("  Alice  ", "name")
        self.assertEqual(result, "Alice")

    def test_validate_non_empty_raises_for_whitespace(self):
        with self.assertRaises(EmptyValueError):
            validate_non_empty("   ", "name")

    # File errors
    def test_save_json_to_unwritable_path(self):
        with self.assertRaises(FileOperationError):
            save_json("/no_such_dir/file.json", [])

    # Update after close
    def test_close_ticket_sets_closed_date(self):
        t = self.tm.create_ticket("X", "IT", "Issue", "Hardware", "P1")
        self.tm.close_ticket(t.ticket_id, "Fixed")
        closed = self.tm.get_ticket(t.ticket_id)
        self.assertIsNotNone(closed.closed_date)

    # Ticket iterator
    def test_ticket_iterator(self):
        from utils import TicketIterator
        self.tm.create_ticket("A", "IT", "I1", "Hardware", "P1")
        self.tm.create_ticket("B", "HR", "I2", "Software", "P2")
        all_t = self.tm.get_all_tickets()
        it    = TicketIterator(all_t)
        count = sum(1 for _ in it)
        self.assertEqual(count, 2)

    # Generator
    def test_ticket_generator_yields_all(self):
        self.tm.create_ticket("A", "IT", "I1", "Hardware", "P1")
        self.tm.create_ticket("B", "HR", "I2", "Software", "P2")
        gen_items = list(self.tm.ticket_gen())
        self.assertEqual(len(gen_items), 2)


# ═══════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  SMART IT SERVICE DESK – UNIT TESTS")
    print("═" * 60 + "\n")
    loader  = unittest.TestLoader()
    suite   = unittest.TestSuite()

    test_classes = [
        TestTicketCreation,
        TestPriorityLogic,
        TestSLABreach,
        TestAutoMonitoring,
        TestFileHandling,
        TestSearchTicket,
        TestExceptionHandling,
    ]
    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
