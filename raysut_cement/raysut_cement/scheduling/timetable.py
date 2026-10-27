# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Timetable (Shift Type) rules: flexible windows, breaks and worked time.

Kept free of document classes so the same logic serves the Shift Type
override, the validations and the reports.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import cint, flt, get_time, to_timedelta

FLEXIBLE = "Flexible"
ALTERNATING = "Alternating entries as IN and OUT during the same shift"
EVERY_VALID_PAIR = "Every Valid Check-in and Check-out"

DAY_OFFSET = {"Current Day": 0, "Next Day": 1, "Next 2 Days": 2, "Next 3 Days": 3}


def is_flexible(shift):
	return shift.get("shift_mode") == FLEXIBLE


def minutes_of(value):
	"""Time / timedelta / 'HH:MM:SS' -> minutes after midnight."""
	return round(to_timedelta(value).total_seconds() / 60) if value not in (None, "") else None


def window_minutes(shift):
	"""(start, end) of the timetable in minutes from the start day's midnight; end may exceed 1440."""
	if is_flexible(shift):
		start = minutes_of(shift.get("valid_period_start"))
		end = minutes_of(shift.get("valid_period_end"))
		if end is not None and DAY_OFFSET.get(shift.get("valid_period_end_day")) == 1:
			end += 1440
		return start, end

	start, end = minutes_of(shift.get("start_time")), minutes_of(shift.get("end_time"))
	if start is not None and end is not None and end <= start:
		end += 1440
	return start, end


def window_bounds(shift, attendance_date):
	start, end = window_minutes(shift)
	midnight = datetime.combine(attendance_date, datetime.min.time())
	return midnight + timedelta(minutes=start), midnight + timedelta(minutes=end)


def required_minutes(shift):
	return cint(shift.get("min_work_hours")) * 60 + cint(shift.get("min_work_minutes"))


def latest_check_in(shift, attendance_date):
	if not cint(shift.get("enable_latest_check_in")) or not shift.get("latest_check_in_time"):
		return None
	day = attendance_date + timedelta(days=DAY_OFFSET.get(shift.get("latest_check_in_day"), 0))
	return datetime.combine(day, get_time(shift.get("latest_check_in_time")))


# ---------------------------------------------------------------- breaks


def get_breaks(shift):
	"""Break Timetables linked to a Shift Type (doc or name), as dicts."""
	rows = shift.get("timetable_breaks") if not isinstance(shift, str) else None
	if rows is None:
		rows = frappe.get_all(
			"Timetable Break", filters={"parent": shift, "parenttype": "Shift Type"}, fields=["break_timetable"]
		)
	names = [r.get("break_timetable") for r in rows if r.get("break_timetable")]
	if not names:
		return []
	breaks = frappe.get_all(
		"Break Timetable",
		filters={"name": ("in", names)},
		fields=["name", "break_type", "break_start", "break_end", "break_duration_minutes", "deduct_from_work_hours"],
	)
	order = {name: i for i, name in enumerate(names)}
	return sorted(breaks, key=lambda b: order[b.name])


def fixed_break_interval(brk, window_start):
	"""Place a fixed break on the timetable's timeline (next day if it falls before the window start)."""
	start = datetime.combine(window_start.date(), get_time(brk.get("break_start")))
	if start < window_start:
		start += timedelta(days=1)
	end = datetime.combine(start.date(), get_time(brk.get("break_end")))
	if end <= start:
		end += timedelta(days=1)
	return start, end


def overlap_minutes(a_start, a_end, b_start, b_end):
	return max(0.0, (min(a_end, b_end) - max(a_start, b_start)).total_seconds() / 60)


def break_deduction_minutes(breaks, intervals, window_start):
	"""Fixed: only the part of the break that overlaps worked time. Flexible: the whole duration, once,
	if the employee worked longer than it."""
	worked = sum((out - in_).total_seconds() / 60 for in_, out in intervals)
	deducted = 0.0
	for brk in breaks:
		if not cint(brk.get("deduct_from_work_hours")):
			continue
		if brk.get("break_type") == "Flexible":
			duration = cint(brk.get("break_duration_minutes"))
			if worked > duration:
				deducted += duration
		else:
			b_start, b_end = fixed_break_interval(brk, window_start)
			deducted += sum(overlap_minutes(in_, out, b_start, b_end) for in_, out in intervals)
	return round(min(deducted, worked))


# ---------------------------------------------------------------- worked time


def worked_intervals(logs, determine_mode, calculation_mode):
	"""Worked (in, out) intervals from chronologically ordered checkins.

	ANVIZ punches often have no log_type: if strict log-type mode finds no IN/OUT at all,
	fall back to treating the first punch as IN and the last as OUT.
	"""
	if not logs:
		return []

	strict = determine_mode and determine_mode != ALTERNATING
	if strict and not any(log.get("log_type") for log in logs):
		strict = False

	if not strict:
		if calculation_mode == EVERY_VALID_PAIR:
			return [(logs[i].time, logs[i + 1].time) for i in range(0, len(logs) - 1, 2)]
		return [(logs[0].time, logs[-1].time)] if len(logs) > 1 else []

	pairs, open_in = [], None
	for log in logs:
		if log.get("log_type") == "IN" and open_in is None:
			open_in = log.time
		elif log.get("log_type") == "OUT" and open_in is not None:
			pairs.append((open_in, log.time))
			open_in = None
	if calculation_mode == EVERY_VALID_PAIR or not pairs:
		return pairs
	return [(pairs[0][0], pairs[-1][1])]


def evaluate_flexible(shift, logs, attendance_date, breaks=None):
	"""Attendance decision for one employee and one flexible timetable day."""
	breaks = get_breaks(shift) if breaks is None else breaks
	window_start, _window_end = window_bounds(shift, attendance_date)
	required = required_minutes(shift)
	result = frappe._dict(
		status="Absent",
		working_hours=0.0,
		in_time=logs[0].time if logs else None,
		out_time=logs[-1].time if len(logs) > 1 else None,
		break_minutes=0,
		required_hours=round(required / 60, 2),
		remarks=None,
	)

	latest = latest_check_in(shift, attendance_date)
	if latest and logs and logs[0].time > latest:
		result.remarks = "Check-in after latest allowed time"
		return result

	if len(logs) < 2:
		result.remarks = "Missing check-out"
		return result

	intervals = worked_intervals(logs, shift.get("determine_check_in_and_check_out"), shift.get("working_hours_calculation_based_on"))
	gross = sum((out - in_).total_seconds() / 60 for in_, out in intervals)
	result.break_minutes = break_deduction_minutes(breaks, intervals, window_start)
	net = gross - result.break_minutes
	result.working_hours = round(net / 60, 2)

	if net >= required:
		result.status = "Present"
	elif cint(shift.get("half_day_if_below_min")) and result.working_hours >= flt(shift.get("flexible_half_day_hours")):
		result.status = "Half Day"
		result.remarks = "Below minimum work time"
	else:
		result.remarks = "Below minimum work time"
	return result
