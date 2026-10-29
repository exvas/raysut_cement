# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Import the old TAMS attendance system: employees, punches and daily attendance.

The rows are the tab-separated files scripts/tams_export.sh pulls out of a restored TAMS
backup. Every function skips what is already in the site, so a batch can be sent again.
Run it on the server with `bench execute ...tams_import.import_dir --kwargs '{"path": ...}'`,
or batch by batch over the API with scripts/tams_import.py.
"""

import csv
import os
from collections import defaultdict

import frappe
from frappe.utils import flt, now_datetime

# TAMS pay code -> (Attendance status, Leave Type). Off days (OF) and holidays (HL) get no row.
PAY_CODES = {
	"PR": ("Present", None),
	"HDL": ("Half Day", None),
	"AL": ("On Leave", "Annual Leave"),
	"SL": ("On Leave", "Sick Leave"),
	"CL": ("On Leave", "Casual Leave"),
	"EL": ("On Leave", "Emergency Leave"),
	"SPL": ("On Leave", "Special Leave"),
	"LL": ("On Leave", "Lieu Leave"),
	"NP": ("On Leave", "Leave Without Pay"),
	"AB": ("Absent", None),
}
# a day with several TAMS rows takes the first code in this order
PRIORITY = list(PAY_CODES)
# TAMS punch mode: 0701 is a check-in, 0703 a check-out
LOG_TYPES = {"0701": "IN", "0703": "OUT"}


@frappe.whitelist(methods=["POST"])
def import_employees(rows, company=None):
	"""rows: [code, name, card_no, job_title, hire_date, dept_code, status]"""
	frappe.only_for("System Manager")
	company = company or default_company()
	existing = set(frappe.get_all("Employee", {"employee_number": ("is", "set")}, pluck="employee_number"))
	designations = set(frappe.get_all("Designation", pluck="name"))
	created, errors = 0, []
	for code, name, card, job, hire, _dept, status in frappe.parse_json(rows):
		if code in existing:
			continue
		first, *middle, last = name.split() if len(name.split()) > 1 else (name, "")
		employee = frappe.new_doc("Employee")
		employee.update(
			{
				"employee_number": code,
				"first_name": first,
				"middle_name": " ".join(middle),
				"last_name": last,
				"attendance_device_id": card,
				"date_of_joining": hire,
				"designation": job if job in designations else None,
				"status": status,
				"company": company,
			}
		)
		# TAMS has no date of birth, and its gender column is a default; HR fills both in later
		employee.flags.ignore_mandatory = True
		frappe.db.savepoint("tams_employee")
		try:
			employee.insert()
		except frappe.DuplicateEntryError:
			frappe.db.rollback(save_point="tams_employee")
			errors.append(f"{code}: attendance device ID {card} is already used by another employee")
			continue
		existing.add(code)
		created += 1
	return {"created": created, "errors": errors}


@frappe.whitelist(methods=["POST"])
def import_checkins(rows):
	"""rows: [card_no, time, mode, machine]. Historical punches, so auto attendance skips them."""
	frappe.only_for("System Manager")
	rows = frappe.parse_json(rows)
	employees = dict(
		frappe.get_all(
			"Employee", {"attendance_device_id": ("is", "set")}, ["attendance_device_id", "name"], as_list=1
		)
	)
	names = dict(frappe.get_all("Employee", fields=["name", "employee_name"], as_list=1))
	times = [row[1] for row in rows]
	seen = {
		(e, str(t))
		for e, t in frappe.get_all(
			"Employee Checkin", {"time": ("between", [min(times), max(times)])}, ["employee", "time"], as_list=1
		)
	} if rows else set()

	new = []
	for card, time, mode, machine in rows:
		employee = employees.get(card)
		if not employee or (employee, time) in seen:
			continue
		seen.add((employee, time))
		new.append((employee, names[employee], LOG_TYPES.get(mode.strip()), time, machine or None))

	by_series = defaultdict(list)
	for row in new:
		by_series[f"EMP-CKIN-{row[3][5:7]}-{row[3][:4]}-"].append(row)
	values = []
	for prefix, series_rows in by_series.items():
		for name, row in zip(reserve_names(prefix, 6, len(series_rows)), series_rows):
			values.append((name, *row, 1, *standard_values()))
	frappe.db.bulk_insert(
		"Employee Checkin",
		["name", "employee", "employee_name", "log_type", "time", "device_id", "skip_auto_attendance", *STANDARD],
		values,
	)
	return {"created": len(values)}


@frappe.whitelist(methods=["POST"])
def import_timesheet(rows, company=None):
	"""rows: [code, date, pay_code, in_time, out_time, work_hours, ot_hours], all of an employee's days in one batch."""
	frappe.only_for("System Manager")
	company = company or default_company()
	ensure_leave_types()
	employees = {
		e.employee_number: e
		for e in frappe.get_all(
			"Employee", {"employee_number": ("is", "set")}, ["name", "employee_number", "employee_name", "department"]
		)
	}

	days = defaultdict(list)
	for code, date, pay_code, in_time, out_time, hours, _ot in frappe.parse_json(rows):
		if code in employees and pay_code in PAY_CODES:
			days[(employees[code].name, date)].append((pay_code, in_time.strip(), out_time.strip(), flt(hours)))
	if not days:
		return {"created": 0}

	dates = [date for _, date in days]
	marked = set(
		(e, str(d))
		for e, d in frappe.get_all(
			"Attendance",
			{"attendance_date": ("between", [min(dates), max(dates)]), "docstatus": ("!=", 2)},
			["employee", "attendance_date"],
			as_list=1,
		)
	)
	by_employee = {e.name: e for e in employees.values()}

	new = []
	for (employee, date), entries in sorted(days.items()):
		if (employee, date) in marked:
			continue
		pay_code = min((entry[0] for entry in entries), key=PRIORITY.index)
		status, leave_type = PAY_CODES[pay_code]
		ins = [entry[1] for entry in entries if entry[1]]
		outs = [entry[2] for entry in entries if entry[2]]
		present = status in ("Present", "Half Day")
		new.append(
			(
				employee,
				by_employee[employee].employee_name,
				by_employee[employee].department,
				date,
				status,
				leave_type,
				round(sum(entry[3] for entry in entries), 2) if present else 0,
				min(ins) if present and ins else None,
				max(outs) if present and outs else None,
			)
		)

	by_series = defaultdict(list)
	for row in new:
		by_series[f"HR-ATT-{row[3][:4]}-"].append(row)
	values = []
	for prefix, series_rows in by_series.items():
		for name, row in zip(reserve_names(prefix, 5, len(series_rows)), series_rows):
			values.append((name, "HR-ATT-.YYYY.-", *row, company, 1, *standard_values()))
	frappe.db.bulk_insert(
		"Attendance",
		[
			"name", "naming_series", "employee", "employee_name", "department", "attendance_date", "status",
			"leave_type", "working_hours", "in_time", "out_time", "company", "docstatus", *STANDARD,
		],
		values,
	)
	return {"created": len(values)}


def import_dir(path, company=None, batch_size=5000):
	"""Import employees.tsv, checkins.tsv and timesheet.tsv from `path`, committing each batch."""
	frappe.only_for("System Manager")
	result = {"employees": import_employees(read_tsv(path, "employees.tsv"), company)}
	frappe.db.commit()

	result["checkins"] = 0
	# sorted by time, so each batch looks up existing punches over a short range only
	for batch in batches(sorted(read_tsv(path, "checkins.tsv"), key=lambda row: row[1]), batch_size):
		result["checkins"] += import_checkins(batch)["created"]
		frappe.db.commit()

	result["attendance"] = 0
	for batch in employee_batches(read_tsv(path, "timesheet.tsv"), batch_size):
		result["attendance"] += import_timesheet(batch, company)["created"]
		frappe.db.commit()
	return result


def ensure_leave_types():
	for _status, leave_type in PAY_CODES.values():
		if leave_type and not frappe.db.exists("Leave Type", leave_type):
			frappe.get_doc(
				{"doctype": "Leave Type", "leave_type_name": leave_type, "is_lwp": leave_type == "Leave Without Pay"}
			).insert()


def reserve_names(prefix, digits, count):
	"""Take the next `count` numbers of a naming series in one update, as autoname would one by one."""
	if not count:
		return []
	frappe.db.sql("insert ignore into `tabSeries` (name, current) values (%s, 0)", prefix)
	current = frappe.db.sql("select current from `tabSeries` where name = %s for update", prefix)[0][0]
	frappe.db.sql("update `tabSeries` set current = current + %s where name = %s", (count, prefix))
	return [f"{prefix}{number:0{digits}d}" for number in range(current + 1, current + count + 1)]


STANDARD = ["owner", "modified_by", "creation", "modified"]


def standard_values():
	now = now_datetime()
	return (frappe.session.user, frappe.session.user, now, now)


def default_company():
	return frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name", limit=1)[0]


def read_tsv(path, filename):
	with open(os.path.join(path, filename), newline="", encoding="utf-8", errors="replace") as f:
		return [[value.strip() for value in row] for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)]


def batches(rows, size):
	for start in range(0, len(rows), size):
		yield rows[start : start + size]


def employee_batches(rows, size):
	"""Batches of about `size` rows that never split one employee's days (rows sorted by employee)."""
	batch = []
	for row in rows:
		if len(batch) >= size and row[0] != batch[-1][0]:
			yield batch
			batch = []
		batch.append(row)
	if batch:
		yield batch
