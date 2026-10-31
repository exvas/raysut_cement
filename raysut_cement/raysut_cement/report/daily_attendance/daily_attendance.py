# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""One row per Attendance: check-in and out, expected checkout, worked hours, late, under time, OT."""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from raysut_cement.raysut_cement.report.consolidated_attendance.consolidated_attendance import get_employees, hh_mm


def execute(filters=None):
	filters = frappe._dict(filters or {}, status=(filters or {}).get("status") or "All")
	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date must be before To Date"))
	employees = {e.name: e for e in get_employees(filters)}
	if not employees:
		return get_columns(), []

	conditions = {
		"docstatus": 1,
		"employee": ("in", list(employees)),
		"attendance_date": ("between", [filters.from_date, filters.to_date]),
	}
	if filters.shift_type:
		conditions["shift"] = filters.shift_type
	rows = []
	for a in frappe.get_all(
		"Attendance",
		filters=conditions,
		fields=[
			"name", "employee", "attendance_date", "shift", "status", "leave_type", "in_time", "out_time",
			"expected_checkout_time", "working_hours", "late_entry", "late_minutes", "under_time_minutes",
			"custom_ot1_hours", "custom_ot2_hours", "custom_missing_punch", "custom_is_holiday_work",
		],
		order_by="employee, attendance_date",
	):
		e = employees[a.employee]
		rows.append(
			{
				"attendance": a.name,
				"date": a.attendance_date,
				"employee": a.employee,
				"employee_name": e.employee_name,
				"department": e.department or _("Not Set"),
				"shift": a.shift,
				"status": a.status if not a.leave_type else f"{a.status} ({a.leave_type})",
				"check_in": a.in_time,
				"check_out": a.out_time,
				"expected_checkout": a.expected_checkout_time,
				"worked": hh_mm(flt(a.working_hours) * 60),
				"late": hh_mm(a.late_minutes) if a.late_entry else "00:00",
				"under_time": hh_mm(a.under_time_minutes),
				"ot1": hh_mm(flt(a.custom_ot1_hours) * 60),
				"ot2": hh_mm(flt(a.custom_ot2_hours) * 60),
				"flags": ", ".join(
					label
					for flag, label in ((a.custom_missing_punch, _("Missing Punch")), (a.custom_is_holiday_work, _("Holiday Work")))
					if cint(flag)
				),
				"worked_hours": flt(a.working_hours, 2),
				"under_time_hours": round(cint(a.under_time_minutes) / 60, 2),
				"ot1_hours": flt(a.custom_ot1_hours, 2),
				"ot2_hours": flt(a.custom_ot2_hours, 2),
			}
		)
	return get_columns(), rows


def get_columns():
	def col(label, fieldname, fieldtype="Data", width=80, **kw):
		return {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": width, **kw}

	return [
		col("Date", "date", "Date", 95),
		col("Employee", "employee", "Link", 115, options="Employee"),
		col("Employee Name", "employee_name", width=170),
		col("Department", "department", width=140),
		col("Shift", "shift", "Link", 130, options="Shift Type"),
		col("Status", "status", width=130),
		col("Check-in", "check_in", "Datetime", 150),
		col("Check-out", "check_out", "Datetime", 150),
		col("Expected Checkout", "expected_checkout", "Datetime", 150),
		col("Worked (HH:MM)", "worked"),
		col("Late (HH:MM)", "late"),
		col("Under Time (HH:MM)", "under_time", width=100),
		col("OT1 (HH:MM)", "ot1"),
		col("OT2 (HH:MM)", "ot2"),
		col("Flags", "flags", width=150),
		col("Attendance", "attendance", "Link", 150, options="Attendance"),
		col("Worked (Hours)", "worked_hours", "Float", 90, precision=2, hidden=1),
		col("Under Time (Hours)", "under_time_hours", "Float", 90, precision=2, hidden=1),
		col("OT1 (Hours)", "ot1_hours", "Float", 90, precision=2, hidden=1),
		col("OT2 (Hours)", "ot2_hours", "Float", 90, precision=2, hidden=1),
	]
