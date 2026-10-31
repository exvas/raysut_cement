# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Flexible check-in ("flexi grace period") on a normal Shift Type.

Staff may check in any time from the shift start up to Grace Period Ends At, then work the
Required Working Hours from that check-in: 07:00 -> 15:00, 08:30 -> 16:30, 10:00 -> 18:00.
Core auto attendance still finds the punches (shift window and buffers); this module decides the
day from them. See README.md.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, get_time, to_timedelta

from raysut_cement.raysut_cement.scheduling.timetable import (
	break_deduction_minutes,
	get_breaks,
	window_bounds,
	worked_intervals,
)

GRACE_ACTION_STATUS = {"Mark Half Day": "Half Day", "Mark Absent": "Absent"}


def minutes_after_start(shift, value):
	"""Minutes from the shift start to a time of day, rolling past midnight on an overnight shift."""
	minutes = (to_timedelta(value) - to_timedelta(shift.start_time)).total_seconds() / 60
	return minutes if minutes >= 0 else minutes + 1440


def validate_shift_type(shift):
	if not shift.get("enable_flexible_checkin"):
		shift.flexi_checkin_until = None  # Frappe fills an empty Time field with the current time
		return
	if shift.get("custom_is_flexible_shift") or shift.get("shift_mode") == "Flexible":
		frappe.throw(_("Flexible Check-in works on a normal shift: turn off Is Flexible Shift and Timetable Mode Flexible"))
	if not shift.get("flexi_checkin_until"):
		frappe.throw(_("Grace Period Ends At is required for Flexible Check-in"))
	if flt(shift.get("flexi_required_hours")) <= 0:
		frappe.throw(_("Required Working Hours must be greater than zero"))
	if cint(shift.get("flexi_undertime_tolerance")) < 0:
		frappe.throw(_("Under Time Tolerance cannot be negative"))

	until = minutes_after_start(shift, shift.flexi_checkin_until)
	end = minutes_after_start(shift, shift.end_time)
	if not 0 < until < end:
		frappe.throw(_("Grace Period Ends At must be after the shift start time and before its end time"))

	# core only links punches up to end + "allow check-out after"; the latest expected checkout must fit
	needed = round(until + flt(shift.flexi_required_hours) * 60 - end)
	if cint(shift.allow_check_out_after_shift_end_time) < needed:
		frappe.throw(
			_(
				"Set Allow check-out after shift end time to at least {0} minutes, so a check-in at {1} can still "
				"complete {2} hours"
			).format(needed, str(shift.flexi_checkin_until)[:5], flt(shift.flexi_required_hours))
		)


def evaluate(shift, logs, status_for_hours=None):
	"""The day's result for one employee from the punches core linked to this shift."""
	shift_start = logs[0].shift_start
	until = datetime.combine(shift_start.date(), get_time(shift.flexi_checkin_until))
	if until < shift_start:
		until += timedelta(days=1)
	required = flt(shift.flexi_required_hours)

	intervals = worked_intervals(logs, shift.determine_check_in_and_check_out, shift.working_hours_calculation_based_on)
	check_in = intervals[0][0] if intervals else logs[0].time
	effective_start = shift_start if check_in < shift_start and shift.flexi_count_from == "Shift Start Time" else check_in

	result = frappe._dict(
		status="Present",
		working_hours=0.0,
		late_entry=check_in > until,
		early_exit=False,
		in_time=check_in,
		out_time=intervals[-1][1] if intervals else None,
		late_minutes=max(0, int((check_in - until).total_seconds() // 60)),
		under_time_minutes=0,
		expected_checkout_time=effective_start + timedelta(hours=required),
		required_hours=required,
		break_minutes=0,
		missing_punch=not intervals,
		remarks=None,
		flexi=True,
	)

	if intervals:
		clipped = [(max(start, effective_start), end) for start, end in intervals if end > effective_start]
		worked = sum((end - start).total_seconds() / 60 for start, end in clipped)
		breaks = get_breaks(shift)
		if breaks:
			result.break_minutes = break_deduction_minutes(breaks, clipped, window_bounds(shift, shift_start.date())[0])
		worked -= result.break_minutes
		result.working_hours = round(max(worked, 0) / 60, 2)
		shortfall = required * 60 - worked
		if shortfall > cint(shift.flexi_undertime_tolerance):
			result.under_time_minutes = round(shortfall)
		if status_for_hours:
			result.status = status_for_hours(result.working_hours)
	else:
		result.remarks = "Missing check-out"

	if result.late_entry:
		action_status = GRACE_ACTION_STATUS.get(shift.flexi_after_grace_action)
		if action_status == "Absent" or (action_status == "Half Day" and result.status == "Present"):
			result.status = action_status
	return result
