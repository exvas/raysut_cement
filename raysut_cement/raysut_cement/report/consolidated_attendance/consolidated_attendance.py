# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Per employee for a period: days by status, worked hours, OT1 (normal) and OT2 (holiday)."""

import frappe
from frappe import _
from frappe.utils import flt, getdate
from frappe.utils.nestedset import get_descendants_of

COUNTS = {"Present": "present_days", "Work From Home": "present_days", "Half Day": "half_days", "Absent": "absent_days", "On Leave": "leave_days"}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date must be before To Date"))
	return get_columns(), get_data(filters)


def get_columns():
	def col(label, fieldname, fieldtype="Float", width=100, **kw):
		return {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **kw}

	return [
		col("Employee", "employee", "Link", 120, options="Employee"),
		col("Employee Name", "employee_name", "Data", 180),
		col("Department", "department", "Link", 150, options="Department"),
		col("Branch", "branch", "Link", 110, options="Branch"),
		col("Present Days", "present_days", "Int", 95),
		col("Half Days", "half_days", "Int", 80),
		col("Absent Days", "absent_days", "Int", 90),
		col("Leave Days", "leave_days", "Int", 85),
		col("Holiday Days Worked", "holiday_days_worked", "Int", 125),
		col("Missing Punch Days", "missing_punch_days", "Int", 120),
		col("Worked Hours", "worked_hours", precision=2, width=105),
		col("OT1 (Normal OT)", "ot1_hours", precision=2, width=115),
		col("OT2 (Holiday OT)", "ot2_hours", precision=2, width=120),
	]


def get_employees(filters):
	"""Through get_list, so the user's permissions (branch, department, ...) decide who is listed."""
	conditions = {"company": filters.company}
	if filters.employee:
		conditions["name"] = filters.employee
	if filters.branch:
		conditions["branch"] = filters.branch
	if filters.department:
		conditions["department"] = ("in", [filters.department, *get_descendants_of("Department", filters.department)])
	return {
		e.name: e
		for e in frappe.get_list(
			"Employee", filters=conditions, fields=["name", "employee_name", "department", "branch"], limit_page_length=0
		)
	}


def get_data(filters):
	employees = get_employees(filters)
	if not employees:
		return []

	rows = {}
	for a in frappe.get_list(
		"Attendance",
		filters={
			"docstatus": 1,
			"company": filters.company,
			"employee": ("in", list(employees)),
			"attendance_date": ("between", [filters.from_date, filters.to_date]),
		},
		fields=[
			"employee", "status", "working_hours", "custom_worked_hours", "custom_ot1_hours", "custom_ot2_hours",
			"custom_is_holiday_work", "custom_missing_punch",
		],
		limit_page_length=0,
	):
		e = employees[a.employee]
		row = rows.setdefault(
			a.employee,
			{
				"employee": e.name, "employee_name": e.employee_name, "department": e.department, "branch": e.branch,
				**dict.fromkeys(("present_days", "half_days", "absent_days", "leave_days", "holiday_days_worked", "missing_punch_days"), 0),
				**dict.fromkeys(("worked_hours", "ot1_hours", "ot2_hours"), 0.0),
			},
		)
		if a.status in COUNTS:
			row[COUNTS[a.status]] += 1
		row["holiday_days_worked"] += 1 if a.custom_is_holiday_work else 0
		row["missing_punch_days"] += 1 if a.custom_missing_punch else 0
		# rows marked before the overtime fields existed only have working_hours
		row["worked_hours"] += flt(a.custom_worked_hours) or (flt(a.working_hours) if a.status in ("Present", "Half Day", "Work From Home") else 0)
		row["ot1_hours"] += flt(a.custom_ot1_hours)
		row["ot2_hours"] += flt(a.custom_ot2_hours)

	for row in rows.values():
		for key in ("worked_hours", "ot1_hours", "ot2_hours"):
			row[key] = flt(row[key], 2)
	return sorted(rows.values(), key=lambda r: r["employee"])
