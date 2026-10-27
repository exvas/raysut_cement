# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Shift Type ("Timetable") with Normal / Flexible modes and Break Timetables."""

from datetime import date
from itertools import groupby

import frappe
from frappe import _
from frappe.utils import cint, create_batch, flt
from hrms.hr.doctype.employee_checkin.employee_checkin import mark_attendance_and_link_log
from hrms.hr.doctype.shift_type.shift_type import EMPLOYEE_CHUNK_SIZE, ShiftType

from raysut_cement.raysut_cement.scheduling.timetable import (
	DAY_OFFSET,
	break_deduction_minutes,
	evaluate_flexible,
	fixed_break_interval,
	get_breaks,
	is_flexible,
	minutes_of,
	required_minutes,
	window_bounds,
	window_minutes,
	worked_intervals,
)
from raysut_cement.raysut_cement.settings import is_enabled

FLEXIBLE_IGNORED_FIELDS = (
	"enable_late_entry_marking",
	"late_entry_grace_period",
	"enable_early_exit_marking",
	"early_exit_grace_period",
	"begin_check_in_before_shift_start_time",
	"allow_check_out_after_shift_end_time",
)


class CustomShiftType(ShiftType):
	def validate(self):
		if not is_enabled("enable_timetable_rules"):
			return super().validate()
		if is_flexible(self):
			self.apply_flexible_window()
		super().validate()
		if is_flexible(self):
			self.validate_flexible_settings()
		self.validate_breaks()

	# ------------------------------------------------------------ validation

	def apply_flexible_window(self):
		"""Mirror the valid window into start/end so core shift lookup and checkin linking keep working."""
		if not (self.valid_period_start and self.valid_period_end):
			frappe.throw(_("Valid Period Start and End are required for a Flexible timetable"))
		self.start_time = self.valid_period_start
		self.end_time = self.valid_period_end
		for field in FLEXIBLE_IGNORED_FIELDS:
			self.set(field, 0)

	def validate_flexible_settings(self):
		start, end = window_minutes(self)
		if self.valid_period_end_day == "Next Day":
			if end - 1440 >= start:
				frappe.throw(_("With an end on the Next Day, Valid Period End must be earlier than Valid Period Start (the window cannot exceed 24 hours)"))
		elif end <= start:
			frappe.throw(_("Valid Period End must be after Valid Period Start, or set the end to Next Day"))

		if not 0 <= cint(self.min_work_minutes) <= 59:
			frappe.throw(_("Minimum work minutes must be between 0 and 59"))
		required = required_minutes(self)
		if required <= 0:
			frappe.throw(_("Minimum work time must be greater than zero"))
		if required > end - start:
			frappe.throw(_("Minimum work time cannot be longer than the valid period"))

		if cint(self.half_day_if_below_min) and not 0 < flt(self.flexible_half_day_hours) < required / 60:
			frappe.throw(_("Half Day threshold must be greater than zero and below the minimum work time"))

		if cint(self.enable_latest_check_in):
			if not self.latest_check_in_time:
				frappe.throw(_("Set the Latest Check-in Time or disable Latest Check-in"))
			latest = DAY_OFFSET.get(self.latest_check_in_day, 0) * 1440 + minutes_of(self.latest_check_in_time)
			if latest < start:
				frappe.throw(_("Latest Check-in must not be before Valid Period Start"))

	def validate_breaks(self):
		window_start, window_end = window_bounds(self, date(2000, 1, 3))
		fixed = []
		for brk in get_breaks(self):
			if brk.break_type != "Fixed":
				continue
			b_start, b_end = fixed_break_interval(brk, window_start)
			if b_start < window_start or b_end > window_end:
				frappe.throw(_("Fixed break {0} must fall inside the timetable time range").format(frappe.bold(brk.name)))
			for other, o_start, o_end in fixed:
				if b_start < o_end and o_start < b_end:
					frappe.throw(_("Breaks {0} and {1} overlap").format(frappe.bold(other), frappe.bold(brk.name)))
			fixed.append((brk.name, b_start, b_end))

	# ------------------------------------------------------------ attendance

	def get_attendance(self, logs):
		"""Normal: core result with breaks deducted. Flexible: minimum-work-time rules."""
		if not is_enabled("enable_timetable_rules"):
			self._last_attendance_details = None
			return super().get_attendance(logs)
		attendance_date = logs[0].shift_start.date()
		breaks = get_breaks(self)

		if is_flexible(self):
			result = evaluate_flexible(self, logs, attendance_date, breaks)
		else:
			status, hours, late_entry, early_exit, in_time, out_time = super().get_attendance(logs)
			result = frappe._dict(
				status=status, working_hours=hours, late_entry=late_entry, early_exit=early_exit,
				in_time=in_time, out_time=out_time, break_minutes=0, required_hours=None, remarks=None,
			)
			if breaks and hours:
				intervals = worked_intervals(logs, self.determine_check_in_and_check_out, self.working_hours_calculation_based_on)
				window_start, _end = window_bounds(self, attendance_date)
				result.break_minutes = break_deduction_minutes(breaks, intervals, window_start)
				result.working_hours = max(0.0, round(hours - result.break_minutes / 60, 2))
				result.status = self.status_for_hours(result.working_hours)

		self._last_attendance_details = result
		return (
			result.status, result.working_hours, bool(result.get("late_entry")),
			bool(result.get("early_exit")), result.in_time, result.out_time,
		)

	def status_for_hours(self, hours):
		if self.working_hours_threshold_for_absent and hours < self.working_hours_threshold_for_absent:
			return "Absent"
		if self.working_hours_threshold_for_half_day and hours < self.working_hours_threshold_for_half_day:
			return "Half Day"
		return "Present"

	def _process(self, logs):
		"""Same flow as core, plus the Raysut fields on each Attendance it creates."""
		if not is_enabled("enable_timetable_rules"):
			return super()._process(logs)
		group_key = lambda x: (x["employee"], x["shift_start"])  # noqa
		for (employee, shift_start), group in groupby(sorted(logs, key=group_key), key=group_key):
			single_shift_logs = list(group)
			attendance_date = shift_start.date()
			if not self.should_mark_attendance(employee, attendance_date):
				continue

			status, hours, late_entry, early_exit, in_time, out_time = self.get_attendance(single_shift_logs)
			attendance = mark_attendance_and_link_log(
				single_shift_logs, status, attendance_date, hours, late_entry, early_exit, in_time, out_time, self.name,
			)
			if attendance:
				self.update_attendance_details(attendance, employee, attendance_date)

		frappe.db.commit()  # nosemgrep - same as core, keep progress between batches

		assigned_employees = self.get_assigned_employees(self.process_attendance_after, True)
		for batch in create_batch(assigned_employees, EMPLOYEE_CHUNK_SIZE):
			for employee in batch:
				self.mark_absent_for_dates_with_no_attendance(employee)
				self.mark_absent_for_half_day_dates(employee)
			frappe.db.commit()  # nosemgrep

	def update_attendance_details(self, attendance, employee, attendance_date):
		details = getattr(self, "_last_attendance_details", None) or frappe._dict()
		frappe.db.set_value(
			"Attendance",
			attendance.name,
			{
				"shift_mode": self.shift_mode or "Normal",
				"shift_pattern": get_shift_pattern(employee, self.name, attendance_date),
				"required_work_hours": details.required_hours,
				"break_deducted_minutes": cint(details.break_minutes),
				"flexible_remarks": details.remarks,
			},
			update_modified=False,
		)


def get_shift_pattern(employee, shift_type, attendance_date):
	"""Shift Pattern behind the generated Shift Assignment for this employee/day, if any."""
	assignment = frappe.db.get_value(
		"Shift Assignment",
		{
			"employee": employee,
			"shift_type": shift_type,
			"docstatus": 1,
			"start_date": ("<=", attendance_date),
			"shift_pattern_assignment": ("is", "set"),
		},
		["shift_pattern_assignment", "end_date"],
		order_by="start_date desc",
		as_dict=True,
	)
	if not assignment or (assignment.end_date and assignment.end_date < attendance_date):
		return None
	return frappe.db.get_value("Shift Pattern Assignment", assignment.shift_pattern_assignment, "shift_pattern")
