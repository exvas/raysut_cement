# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Under time per employee for a period: days short and the total shortfall."""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from raysut_cement.raysut_cement.report.consolidated_attendance.consolidated_attendance import get_employees, hh_mm


def execute(filters=None):
	filters = frappe._dict(filters or {}, status=(filters or {}).get("status") or "All")
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date must be before To Date"))
	employees = {e.name: e for e in get_employees(filters)}
	if not employees:
		return get_columns(), []

	totals = {}
	for a in frappe.get_all(
		"Attendance",
		filters={
			"docstatus": 1,
			"employee": ("in", list(employees)),
			"attendance_date": ("between", [filters.from_date, filters.to_date]),
			"under_time_minutes": (">", 0),
		},
		fields=["employee", "under_time_minutes"],
	):
		e = employees[a.employee]
		row = totals.setdefault(
			a.employee,
			{"employee": e.name, "employee_name": e.employee_name, "department": e.department or _("Not Set"),
			 "branch": e.branch, "days": 0, "minutes": 0},
		)
		row["days"] += 1
		row["minutes"] += cint(a.under_time_minutes)

	rows = sorted(totals.values(), key=lambda r: -r["minutes"])
	for row in rows:
		row["under_time"] = hh_mm(row["minutes"])
		row["under_time_hours"] = round(row["minutes"] / 60, 2)
	if rows:
		minutes = sum(r["minutes"] for r in rows)
		rows.append(
			{"employee_name": _("Total"), "days": sum(r["days"] for r in rows), "under_time": hh_mm(minutes),
			 "under_time_hours": round(minutes / 60, 2), "is_total": 1}
		)
	return get_columns(), rows


def get_columns():
	return [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Data", "width": 160},
		{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Link", "options": "Branch", "width": 110},
		{"label": _("Days with Under Time"), "fieldname": "days", "fieldtype": "Int", "width": 140},
		{"label": _("Under Time (HH:MM)"), "fieldname": "under_time", "fieldtype": "Data", "width": 130},
		{"label": _("Under Time (Hours)"), "fieldname": "under_time_hours", "fieldtype": "Float", "precision": 2, "width": 120},
	]
