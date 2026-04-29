# 🖥️ Smart IT Service Desk — ITIL Automation System

A Python-based IT helpdesk automation system built on ITIL principles. Automates ticket creation, incident management, SLA tracking, system monitoring, logging, and reporting.

---

## 📁 Project Structure

```
smart_it_service_desk/
│── main.py              # Entry point — interactive CLI menu
│── tickets.py           # Ticket classes + TicketManager (CRUD)
│── itil.py              # IncidentManager, ServiceRequestManager, ProblemManager, ChangeManager, SLAManager
│── monitor.py           # System monitoring (CPU, RAM, Disk, Network)
│── reports.py           # Daily and monthly report generation
│── utils.py             # Helpers — validators, file I/O, generators, map/filter/reduce
│── logger.py            # Logging setup, decorators, event helpers
│── requirements.txt     # Python dependencies
│── test_service_desk.py # Unit tests (74 test cases across 7 categories)
│── data/
│   ├── tickets.json     # Persistent ticket storage
│   ├── problems.json    # Problem records storage
│   ├── backup.csv       # CSV backup of all tickets
│   ├── logs.txt         # Application log file
│   └── reports/         # Generated daily/monthly CSV reports
└── README.md
```

---

## ⚙️ Setup & Installation

### Prerequisites
- Python 3.10 or higher
- pip

### Install dependencies

pip install -r requirements.txt

> `psutil` is the only external dependency (for live CPU/RAM/Disk/Network metrics).  
> If `psutil` is not installed, the monitor module falls back to simulated metrics automatically.

### Run the application

python main.py


### Run unit tests

python test_service_desk.py


## 🚀 Features

### 🎫 Ticket Management
- Create, view, search, update, close, and delete tickets
- Three ticket types: **IncidentTicket**, **ServiceRequest**, **ProblemRecord**
- Auto-priority inference from issue description using regex keyword matching
- Unique ticket ID generation (e.g. `TKT-20240101-A1B2`)
- Persistent JSON storage — loaded automatically at startup

### 🔴 Priority Rules

| Issue Type       | Priority | SLA Target |
|------------------|----------|------------|
| Server Down       | P1       | 1 hour     |
| Internet Down     | P2       | 4 hours    |
| Laptop Slow       | P3       | 8 hours    |
| Password Reset    | P4       | 24 hours   |

### ⏱️ SLA Tracking
- Real-time SLA breach detection per ticket
- Remaining SLA time calculated dynamically
- Auto-escalation of breached P1 IncidentTickets
- 10-minute SLA warning notifications

### 📡 System Monitoring
- Live metrics: CPU %, Memory %, Disk %, Network throughput (Mbps)
- Alert thresholds: CPU > 90%, RAM > 95%, Disk > 90% used
- Auto-creates a **P1 incident ticket** on any threshold breach
- Logs CRITICAL alerts to `logs.txt`
- Falls back to simulated metrics if `psutil` is unavailable

### 🔄 ITIL Modules
| Module | Description |
|--------|-------------|
| Incident Management | Raise, resolve, escalate incidents |
| Service Request Management | Raise and approve standard service requests |
| Problem Management | Detects 5+ repeated issues → auto-creates ProblemRecord |
| Change Management | Request, approve, and implement change records |
| SLA Management | Track, report, and escalate SLA breaches |

### 📊 Reports
- **Daily Report**: total tickets, open/closed, P1 count, SLA breaches, breakdown by category and priority
- **Monthly Report**: avg resolution time, most common issue, top department, repeated problems
- Export to CSV in `data/reports/`

### 🗂️ Data Storage
| File | Contents |
|------|----------|
| `data/tickets.json` | All ticket records (auto-saved on every change) |
| `data/problems.json` | Problem records created by ProblemManager |
| `data/backup.csv` | Full CSV backup of all tickets |
| `data/logs.txt` | Timestamped application event log |

---

## 🧪 Unit Tests

74 test cases across 7 categories using `unittest` + `unittest.mock`:

| # | Test Class | Coverage |
|---|-----------|----------|
| 1 | `TestTicketCreation` | 14 tests — all ticket types, ID format, OOP methods |
| 2 | `TestPriorityLogic` | 11 tests — keyword inference, validation, override |
| 3 | `TestSLABreach` | 10 tests — SLA limits, breach detection, resolved exclusion |
| 4 | `TestAutoMonitoring` | 7 tests — threshold alerts, auto P1 ticket creation |
| 5 | `TestFileHandling` | 6 tests — JSON/CSV save/load, persistence, malformed input |
| 6 | `TestSearchTicket` | 10 tests — search by ID, name, status, priority, sort |
| 7 | `TestExceptionHandling` | 16 tests — all custom exceptions, edge cases |

---

## 🐛 Debugging

Debugging was performed using  **VS Code** with the following techniques:

screenshots/
├── 1_breakpoint_variables.png   ← real ticket data in variables panel
├── 2_watch_window.png           ← ticket.priority, ticket_id live values
└── 3_step_execution.png         ← yellow arrow stepping through tickets.py

> Screenshots of debugging sessions are in the `/screenshots` folder.

---

## 🏗️ OOP Design

```
Ticket  (base class)
├── IncidentTicket     — impact, urgency, escalation_count
├── ServiceRequest     — requested_service, approved flag
└── ProblemRecord      — related_tickets, root_cause, known_error

TicketManager          — CRUD, persistence, search, sort, SLA
SLAManager             — breach detection, escalation, warnings
IncidentManager        — ITIL incident lifecycle
ServiceRequestManager  — ITIL service request fulfilment
ProblemManager         — repeat issue detection, problem records
ChangeManager          — change request, approval, implementation
Monitor                — live metrics, alerts, auto-ticket creation
ReportGenerator        — daily/monthly reports + CSV export
```

Key OOP concepts demonstrated:
- **Inheritance & Polymorphism** — `to_dict()`, `_from_dict()`, `__str__()` overridden per subclass
- **Encapsulation** — `_tickets`, `_history`, `_resolution_notes` private; exposed via `@property`
- **Static methods** — `Ticket.from_dict()`, `Monitor.system_info()`, `SLAManager.sla_target_for()`
- **Special methods** — `__str__`, `__repr__`, `__eq__`, `__lt__`, `__iter__`, `__next__`, `__len__`
- **Decorators** — `@log_action` factory decorator wraps all CRUD methods with entry/exit/error logging
- **Generators** — `ticket_generator()`, `metric_stream()`, `generate_warnings()`
- **Iterators** — `TicketIterator` custom class; `TicketManager` implements `__iter__`

---

## 📦 Dependencies

```
psutil>=5.9.0
```

All other modules used (`json`, `csv`, `logging`, `re`, `uuid`, `datetime`, `collections`, `dataclasses`, `functools`, `unittest`) are part of the Python standard library.
