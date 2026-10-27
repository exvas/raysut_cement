# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Worked, break and required hours per employee per day, plus punches on rest days."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate
from frappe.utils.nestedset import get_descendants_of


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date must be before To Date"))
	data = attendance_rows(filters) + rest_day_rows(filters)
	data.sort(key=lambda r: (r["employee"], str(r["date"])))
	return get_columns(), data


def get_columns():
	def col(label, fieldname, fieldtype="Data", width=110, **kw):
		return {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **kw}

	return [
		col("Employee", "employee", "Link", 120, options="Employee"),
		col("Name", "employee_name", width=150),
		col("Date", "date", "Date", 100),
		col("Pattern", "shift_pattern", "Link", 120, options="Shift Pattern"),
		col("Timetable", "timetable", "Link", 130, options="Shift Type"),
		col("First In", "first_in", "Datetime", 150),
		col("Last Out", "last_out", "Datetime", 150),
		col("Gross Hours", "gross_hours", "Float", 95, precision=2),
		col("Break Deducted (Min)", "break_minutes", "Int", 110),
		col("Net Hours", "net_hours", "Float", 90, precision=2),
		col("Required Hours", "required_hours", "Float", 105, precision=2),
		col("Shortfall / Excess", "difference", "Float", 115, precision=2),
		col("Status", "status", width=110),
		col("Remarks", "remarks", width=220),
	]


def employee_filter(filters):
	conditions = {"company": filters.company}
	if filters.employee:
		conditions["name"] = filters.employee
	if filters.department:
		conditions["department"] = ("in", [filters.department, *get_descendants_of("Department", filters.department)])
	return conditions


def attendance_rows(filters):
	conditions = {
		"docstatus": 1,
		"attendance_date": ("between", [filters.from_date, filters.to_date]),
		"shift": ("is", "set"),
		**{k: v for k, v in employee_filter(filters).items() if k != "name"},
	}
	if filters.employee:
		conditions["employee"] = filters.employee
	if filters.timetable:
		conditions["shift"] = filters.timetable
	if filters.shift_pattern:
		conditions["shift_pattern"] = filters.shift_pattern

	rows = []
	for a in frappe.get_all(
		"Attendance",
		filters=conditions,
		fields=["employee", "employee_name", "attendance_date", "shift", "shift_pattern", "in_time", "out_time", "working_hours",
				"break_deducted_minutes", "required_work_hours", "status", "flexible_remarks"],
	):
		net = flt(a.working_hours, 2)
		breaks = a.break_deducted_minutes or 0
		required = flt(a.required_work_hours, 2) or None
		rows.append(
			{
				"employee": a.employee,
				"employee_name": a.employee_name,
				"date": a.attendance_date,
				"shift_pattern": a.shift_pattern,
				"timetable": a.shift,
				"first_in": a.in_time,
				"last_out": a.out_time,
				"gross_hours": flt(net + breaks / 60, 2),
				"break_minutes": breaks,
				"net_hours": net,
				"required_hours": required,
				"difference": flt(net - required, 2) if required else None,
				"status": a.status,
				"remarks": a.flexible_remarks,
				"below_required": 1 if required and net < required else 0,
			}
		)
	return rows


def rest_day_rows(filters):
	"""Punches not linked to any shift (no Shift Assignment that day) are shown as Rest Day Work."""
	if filters.timetable or filters.shift_pattern:
		return []
	employees = frappe.get_all("Employee", filters=employee_filter(filters), fields=["name", "employee_name"])
	names = {e.name: e.employee_name for e in employees}
	if not names:
		return []

	logs = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": ("in", list(names)),
			"time": ("between", [filters.from_date, add_days(filters.to_date, 1)]),
			"shift": ("is", "not set"),
		},
		fields=["employee", "time"],
		order_by="employee, time",
	)
	by_day = defaultdict(list)
	for log in logs:
		if getdate(log.time) <= getdate(filters.to_date):
			by_day[(log.employee, getdate(log.time))].append(log.time)

	rows = []
	for (employee, day), times in by_day.items():
		gross = flt((times[-1] - times[0]).total_seconds() / 3600, 2) if len(times) > 1 else 0
		rows.append(
			{
				"employee": employee,
				"employee_name": names[employee],
				"date": day,
				"first_in": times[0],
				"last_out": times[-1] if len(times) > 1 else None,
				"gross_hours": gross,
				"net_hours": gross,
				"status": "Rest Day Work",
				"remarks": _("{0} punch(es) on a day without a shift").format(len(times)),
			}
		)
	return rows
