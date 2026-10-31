# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Attendance for flexible shifts (Shift Type "Is Flexible Shift").

An attendance day runs from Day Start Time to the next day's Day Start Time. Its first punch is
the IN, its last the OUT. Only windows that have already ended are processed, so a day is marked
once, with all of its punches. See README.md.
"""

from collections import defaultdict
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, flt, get_time, getdate, now_datetime, nowdate

from raysut_cement.raysut_cement.settings import is_enabled

LOOKBACK_DAYS = 3


def flexible_shifts(names=None):
	filters = {"custom_is_flexible_shift": 1}
	if names:
		filters["name"] = ("in", names)
	return {
		s.name: s
		for s in frappe.get_all(
			"Shift Type",
			filters=filters,
			fields=[
				"name",
				"custom_day_start_time",
				"process_attendance_after",
				"working_hours_threshold_for_absent",
				"working_hours_threshold_for_half_day",
			],
		)
	}


def window(shift, attendance_date):
	"""[date + day start, next date + day start)"""
	start = datetime.combine(getdate(attendance_date), get_time(shift.custom_day_start_time))
	return start, start + timedelta(days=1)


def attendance_date_for(shift, punch_time):
	"""The attendance date a punch belongs to: before Day Start it is the previous date's."""
	day = punch_time.date()
	return day if punch_time.time() >= get_time(shift.custom_day_start_time) else day - timedelta(days=1)


def shifts_by_day(shifts, from_date, to_date, employee=None):
	"""{(employee, date): shift name} for days whose shift (Shift Assignment, else default) is flexible."""
	employee_filters = {"status": "Active"}
	if employee:
		employee_filters["name"] = employee
	employees = {
		e.name: e
		for e in frappe.get_all(
			"Employee", employee_filters, ["name", "default_shift", "date_of_joining", "relieving_date"]
		)
	}
	assignments = defaultdict(list)
	for a in frappe.get_all(
		"Shift Assignment",
		filters={
			"docstatus": 1,
			"status": "Active",
			"employee": ("in", list(employees)),
			"start_date": ("<=", to_date),
		},
		or_filters=[["end_date", "is", "not set"], ["end_date", ">=", from_date]],
		fields=["employee", "shift_type", "start_date", "end_date"],
		order_by="start_date desc",
	):
		assignments[a.employee].append(a)

	result = {}
	day = getdate(from_date)
	while day <= getdate(to_date):
		for e in employees.values():
			if (e.date_of_joining and day < getdate(e.date_of_joining)) or (
				e.relieving_date and day > getdate(e.relieving_date)
			):
				continue
			assigned = next(
				(a for a in assignments[e.name] if a.start_date <= day and (not a.end_date or a.end_date >= day)), None
			)
			shift = assigned.shift_type if assigned else e.default_shift
			if shift in shifts:
				result[(e.name, day)] = shift
		day += timedelta(days=1)
	return result


@frappe.whitelist(methods=["POST"])
def run_flexible_attendance(from_date, to_date, employee=None, reprocess=0):
	"""The "Process Flexible Attendance" button: one employee runs now, everyone in the background."""
	frappe.only_for(("System Manager", "HR Manager"))
	kwargs = {"from_date": from_date, "to_date": to_date, "employee": employee, "reprocess": reprocess}
	if employee:
		return process_flexible_attendance(**kwargs)
	frappe.enqueue(process_flexible_attendance, queue="long", timeout=3600, **kwargs)
	return {"queued": True}


def process_flexible_attendance(from_date=None, to_date=None, employee=None, reprocess=0, shift_types=None):
	"""Mark attendance for flexible-shift days whose window has ended. Returns counts."""
	if not is_enabled("enable_flexible_overtime"):
		return {"skipped": True}

	shifts = flexible_shifts(shift_types)
	to_date = getdate(to_date or nowdate())
	from_date = getdate(from_date or add_days(to_date, -LOOKBACK_DAYS))
	if from_date > to_date:
		frappe.throw(_("From Date must be before To Date"))

	days = shifts_by_day(shifts, from_date, to_date, employee)
	if not days:
		return {"created": 0, "updated": 0, "skipped": 0, "errors": 0}

	punches = punches_by_day(days, shifts, from_date, to_date)
	now = now_datetime()
	counts = defaultdict(int)
	for (emp, day), shift_name in sorted(days.items(), key=lambda item: (item[0][1], item[0][0])):
		shift = shifts[shift_name]
		if shift.process_attendance_after and day < getdate(shift.process_attendance_after):
			continue
		if window(shift, day)[1] > now:
			continue  # the day is not over yet
		logs = punches.get((emp, day))
		if not logs:
			continue  # no punches: left to absent marking, which skips holidays
		try:
			counts[mark_day(emp, day, shift, logs, frappe.utils.cint(reprocess))] += 1
			if not frappe.flags.in_test:
				frappe.db.commit()  # nosemgrep - one employee-day at a time, like core auto attendance
		except Exception:
			frappe.db.rollback()
			frappe.log_error(f"Flexible attendance failed for {emp} on {day}")
			counts["errors"] += 1
	return {key: counts[key] for key in ("created", "updated", "skipped", "errors")}


def punches_by_day(days, shifts, from_date, to_date):
	employees = sorted({emp for emp, _day in days})
	logs = frappe.get_all(
		"Employee Checkin",
		filters={
			"employee": ("in", employees),
			"time": ("between", [from_date, add_days(to_date, 2)]),
			"skip_auto_attendance": 0,
		},
		fields=["name", "employee", "time", "attendance"],
		order_by="employee, time",
	)
	grouped = defaultdict(list)
	for log in logs:
		for day in (log.time.date(), log.time.date() - timedelta(days=1)):
			shift_name = days.get((log.employee, day))
			if shift_name and attendance_date_for(shifts[shift_name], log.time) == day:
				grouped[(log.employee, day)].append(log)
				break
	return grouped


def mark_day(employee, day, shift, logs, reprocess=False):
	existing = frappe.db.get_value(
		"Attendance",
		{"employee": employee, "attendance_date": day, "docstatus": ("!=", 2)},
		["name", "docstatus", "status"],
		as_dict=True,
	)
	if existing and existing.docstatus == 1:
		if not reprocess or existing.status == "On Leave":
			return "skipped"
		frappe.get_doc("Attendance", existing.name).cancel()

	attendance = (
		frappe.get_doc("Attendance", existing.name)
		if existing and existing.docstatus == 0
		else frappe.new_doc("Attendance")
	)
	if existing and existing.docstatus == 1:
		attendance.amended_from = existing.name

	missing_punch = len(logs) < 2
	hours = 0.0 if missing_punch else round((logs[-1].time - logs[0].time).total_seconds() / 3600, 2)
	attendance.update(
		{
			"employee": employee,
			"attendance_date": day,
			"company": frappe.db.get_value("Employee", employee, "company"),
			"shift": shift.name,
			"status": "Present" if missing_punch else status_for_hours(shift, hours),
			"in_time": logs[0].time,
			"out_time": None if missing_punch else logs[-1].time,
			"working_hours": hours,
			"custom_missing_punch": 1 if missing_punch else 0,
		}
	)
	attendance.flags.ignore_permissions = True
	attendance.save()
	attendance.submit()

	frappe.db.set_value(
		"Employee Checkin", {"name": ("in", [log.name for log in logs])}, "attendance", attendance.name, update_modified=False
	)
	return "updated" if existing else "created"


def status_for_hours(shift, hours):
	absent, half_day = flt(shift.working_hours_threshold_for_absent), flt(shift.working_hours_threshold_for_half_day)
	if absent and hours < absent:
		return "Absent"
	if half_day and hours < half_day:
		return "Half Day"
	return "Present"


def hourly_flexible_attendance():
	process_flexible_attendance()
