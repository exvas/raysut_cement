# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Worked hours, OT1 (normal overtime) and OT2 (holiday overtime) on every Attendance.

The rules are in README.md next to this file.
"""

import math

import frappe
from erpnext.setup.doctype.employee.employee import is_holiday
from frappe import _
from frappe.utils import cint, flt, to_timedelta

from raysut_cement.raysut_cement.settings import is_enabled

WORKED_STATUSES = ("Present", "Half Day", "Work From Home")
SHIFT_FIELDS = (
	"start_time",
	"end_time",
	"custom_is_flexible_shift",
	"custom_day_start_time",
	"custom_required_working_hours",
	"custom_ot_min_hours",
	"custom_ot_max_hours",
	"ot_policy",
	"enable_flexible_checkin",
	"flexi_required_hours",
	"flexi_undertime_tolerance",
)
POLICY_FIELDS = (
	"min_ot_minutes",
	"rounding_minutes",
	"rounding_method",
	"max_ot1_hours",
	"move_to_ot2_after_hours",
	"ot2_on_holidays",
	"max_ot2_hours",
)


def calculate_overtime(worked_hours, required_hours, ot_min_hours=0, ot_max_hours=0, holiday=False):
	"""Return (ot1, ot2). A holiday's whole worked time is OT2, with no min or max."""
	worked_hours = flt(worked_hours)
	if holiday:
		return 0.0, round(max(worked_hours, 0.0), 2)

	extra = worked_hours - flt(required_hours)
	if extra <= 0 or extra < flt(ot_min_hours):
		return 0.0, 0.0
	if flt(ot_max_hours) > 0 and extra > flt(ot_max_hours):
		return round(flt(ot_max_hours), 2), 0.0
	return round(extra, 2), 0.0


def round_hours(hours, policy):
	"""Round to the policy's 15 / 30 / 60 minutes, down, to the nearest or up."""
	step = cint(policy.get("rounding_minutes"))
	if not step:
		return round(hours, 2)
	method = {"Up": math.ceil, "Nearest": lambda x: math.floor(x + 0.5)}.get(policy.get("rounding_method"), math.floor)
	return round(method(round(hours * 60, 6) / step) * step / 60, 2)


def calculate_policy_overtime(worked_hours, required_hours, policy, holiday=False):
	"""Return (ot1, ot2) under an OT Policy."""
	worked_hours = max(flt(worked_hours), 0.0)
	if holiday and cint(policy.get("ot2_on_holidays")):
		ot2 = round_hours(worked_hours, policy)
		cap = flt(policy.get("max_ot2_hours"))
		return 0.0, round(min(ot2, cap) if cap else ot2, 2)

	extra = worked_hours - flt(required_hours)
	if extra <= 0 or extra * 60 < cint(policy.get("min_ot_minutes")):
		return 0.0, 0.0
	ot1, ot2 = round_hours(extra, policy), 0.0
	move_after = flt(policy.get("move_to_ot2_after_hours"))
	if move_after and ot1 > move_after:
		ot1, ot2 = move_after, ot1 - move_after
	if flt(policy.get("max_ot1_hours")):
		ot1 = min(ot1, flt(policy.max_ot1_hours))
	if flt(policy.get("max_ot2_hours")):
		ot2 = min(ot2, flt(policy.max_ot2_hours))
	return round(ot1, 2), round(ot2, 2)


def get_policy(name):
	return frappe.get_cached_value("OT Policy", name, POLICY_FIELDS, as_dict=True) if name else None


def shift_overtime(worked, shift, holiday):
	"""(ot1, ot2) for worked hours on a shift: its OT Policy if it has one, else OT Min / Max.

	Without a shift (or one with no working hours) there is nothing to be over, so no OT1: an
	employee with no shift assigned would otherwise get every hour as overtime. Holiday work is
	still OT2.
	"""
	required = required_hours(shift)
	policy = get_policy(shift.get("ot_policy"))
	if policy:
		ot1, ot2 = calculate_policy_overtime(worked, required, policy, holiday)
	else:
		ot1, ot2 = calculate_overtime(
			worked, required, shift.get("custom_ot_min_hours"), shift.get("custom_ot_max_hours"), holiday
		)
	return (ot1 if required > 0 else 0.0), ot2


def required_hours(shift):
	"""Flexible check-in or Required Working Hours, else the start-end duration of a fixed shift."""
	if shift.get("enable_flexible_checkin") and flt(shift.get("flexi_required_hours")) > 0:
		return flt(shift.flexi_required_hours)
	if flt(shift.get("custom_required_working_hours")) > 0:
		return flt(shift.custom_required_working_hours)
	if shift.get("custom_is_flexible_shift") or not (shift.get("start_time") and shift.get("end_time")):
		return 0.0
	seconds = (to_timedelta(shift.end_time) - to_timedelta(shift.start_time)).total_seconds()
	return round((seconds if seconds > 0 else seconds + 86400) / 3600, 2)


def get_shift(name):
	return frappe.get_cached_value("Shift Type", name, SHIFT_FIELDS, as_dict=True) if name else None


def under_time_minutes(worked, shift):
	"""Minutes short of the shift's required hours, when more than its tolerance (else 0)."""
	required = required_hours(shift)
	shortfall = required * 60 - worked * 60 if required > 0 else 0
	return round(shortfall) if shortfall > cint(shift.get("flexi_undertime_tolerance")) else 0


def overtime_values(attendance, holiday, shift_name=None):
	"""Worked hours, OT1, OT2 and under time for an Attendance (doc or row), given whether its date
	is a holiday.

	Without a shift on the Attendance (manual or imported days) the employee's shift, passed as
	shift_name, sets the required hours. Under time is for a full working day only: not a holiday,
	a half day or a missing punch.
	"""
	missing_punch = attendance.get("custom_missing_punch")
	worked = 0.0 if missing_punch or attendance.status not in WORKED_STATUSES else max(flt(attendance.working_hours), 0.0)
	holiday_work = bool(holiday) and attendance.status in WORKED_STATUSES

	ot1 = ot2 = 0.0
	under_time = 0
	if worked:
		shift = get_shift(attendance.get("shift") or shift_name) or frappe._dict()
		ot1, ot2 = shift_overtime(worked, shift, holiday_work)
		if not holiday_work and attendance.status in ("Present", "Work From Home"):
			under_time = under_time_minutes(worked, shift)
	return {
		"custom_worked_hours": round(worked, 2),
		"custom_is_holiday_work": 1 if holiday_work else 0,
		"custom_ot1_hours": ot1,
		"custom_ot2_hours": ot2,
		"under_time_minutes": under_time,
	}


def set_overtime(doc, method=None):
	"""Attendance before_save / before_submit."""
	if not is_enabled("enable_flexible_overtime"):
		return
	holiday = doc.status in WORKED_STATUSES and is_holiday(doc.employee, doc.attendance_date, raise_exception=False)
	default_shift = None if doc.shift else frappe.db.get_value("Employee", doc.employee, "default_shift")
	doc.update(overtime_values(doc, holiday, default_shift))


@frappe.whitelist(methods=["POST"])
def recalculate_overtime(from_date, to_date, employee=None):
	"""Refill the overtime fields on submitted Attendance in a date range (for example imported
	history). Rows that already hold these values are left untouched. Returns the number changed."""
	frappe.only_for("System Manager")
	fields = ["custom_worked_hours", "custom_is_holiday_work", "custom_ot1_hours", "custom_ot2_hours", "under_time_minutes"]
	filters = {"docstatus": 1, "attendance_date": ("between", [from_date, to_date])}
	if employee:
		filters["employee"] = employee
	rows = frappe.get_all(
		"Attendance",
		filters=filters,
		fields=["name", "employee", "attendance_date", "status", "working_hours", "shift", "custom_missing_punch", *fields],
	)
	if not rows:
		return 0

	employees = {
		e.name: e
		for e in frappe.get_all(
			"Employee",
			{"name": ("in", list({r.employee for r in rows}))},
			["name", "default_shift", "holiday_list", "company"],
		)
	}
	company_lists = dict(frappe.get_all("Company", fields=["name", "default_holiday_list"], as_list=1))
	list_of = {name: e.holiday_list or company_lists.get(e.company) for name, e in employees.items()}
	holidays = {
		(h.parent, h.holiday_date)
		for h in frappe.get_all(
			"Holiday",
			filters={
				"parent": ("in", [name for name in set(list_of.values()) if name] or [""]),
				"holiday_date": ("between", [from_date, to_date]),
			},
			fields=["parent", "holiday_date"],
		)
	}

	changed = 0
	for row in rows:
		values = overtime_values(
			row,
			(list_of.get(row.employee), row.attendance_date) in holidays,
			employees[row.employee].default_shift if row.employee in employees else None,
		)
		if any(flt(row.get(f)) != flt(values[f]) for f in fields):
			frappe.db.set_value("Attendance", row.name, values, update_modified=False)
			changed += 1
	return changed


def validate_shift_type(doc):
	"""Shift Type: the Flexible Shift & Overtime settings."""
	for field in ("custom_required_working_hours", "custom_ot_min_hours", "custom_ot_max_hours"):
		if flt(doc.get(field)) < 0:
			frappe.throw(_("{0} cannot be negative").format(_(doc.meta.get_label(field))))

	if not doc.get("custom_is_flexible_shift"):
		doc.custom_day_start_time = None  # Frappe fills an empty Time field with the current time
	else:
		if not doc.get("custom_day_start_time"):
			frappe.throw(_("Day Start Time is required for a flexible shift"))
		if flt(doc.get("custom_required_working_hours")) <= 0:
			frappe.throw(_("Required Working Hours is required for a flexible shift"))
		if doc.get("shift_mode") == "Flexible":
			frappe.throw(
				_("Use either Timetable Mode Flexible or Is Flexible Shift, not both: they process attendance differently")
			)

	ot_min, ot_max = flt(doc.get("custom_ot_min_hours")), flt(doc.get("custom_ot_max_hours"))
	if ot_min and ot_max and ot_max < ot_min:
		frappe.throw(_("OT Max Hours must be greater than or equal to OT Min Hours"))
