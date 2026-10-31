# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Worked hours, OT1 (normal overtime) and OT2 (holiday overtime) on every Attendance.

The rules are in README.md next to this file.
"""

import frappe
from erpnext.setup.doctype.employee.employee import is_holiday
from frappe import _
from frappe.utils import flt, to_timedelta

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


def required_hours(shift):
	"""Required Working Hours, else the start-end duration of a fixed shift."""
	if flt(shift.get("custom_required_working_hours")) > 0:
		return flt(shift.custom_required_working_hours)
	if shift.get("custom_is_flexible_shift") or not (shift.get("start_time") and shift.get("end_time")):
		return 0.0
	seconds = (to_timedelta(shift.end_time) - to_timedelta(shift.start_time)).total_seconds()
	return round((seconds if seconds > 0 else seconds + 86400) / 3600, 2)


def get_shift(name):
	return frappe.get_cached_value("Shift Type", name, SHIFT_FIELDS, as_dict=True) if name else None


def set_overtime(doc, method=None):
	"""Attendance before_save / before_submit."""
	if not is_enabled("enable_flexible_overtime"):
		return

	worked = 0.0 if doc.get("custom_missing_punch") else max(flt(doc.working_hours), 0.0)
	if doc.status not in WORKED_STATUSES:
		worked = 0.0
	holiday_work = doc.status in WORKED_STATUSES and is_holiday(doc.employee, doc.attendance_date, raise_exception=False)

	ot1 = ot2 = 0.0
	if worked and not doc.get("custom_missing_punch"):
		shift = get_shift(doc.shift) or frappe._dict()
		ot1, ot2 = calculate_overtime(
			worked, required_hours(shift), shift.get("custom_ot_min_hours"), shift.get("custom_ot_max_hours"), holiday_work
		)

	doc.custom_worked_hours = round(worked, 2)
	doc.custom_is_holiday_work = 1 if holiday_work else 0
	doc.custom_ot1_hours = ot1
	doc.custom_ot2_hours = ot2


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
