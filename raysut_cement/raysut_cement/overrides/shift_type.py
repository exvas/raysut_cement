# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Shift Type ("Timetable") with Normal / Flexible modes and Break Timetables."""

from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, get_time
from hrms.hr.doctype.shift_type.shift_type import ShiftType

from raysut_cement.raysut_cement.attendance import flexi_checkin
from raysut_cement.raysut_cement.attendance.flexible import process_flexible_attendance
from raysut_cement.raysut_cement.attendance.overtime import validate_shift_type
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
		if is_enabled("enable_flexible_overtime"):
			validate_shift_type(self)
			flexi_checkin.validate_shift_type(self)
			if self.get("custom_is_flexible_shift"):
				self.apply_day_start_window()
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

	def apply_day_start_window(self):
		"""A day-start flexible shift spans a whole day: Day Start to one minute before the next one.
		Core still needs start/end (and no buffers, or the shift would overlap itself)."""
		start = datetime.combine(date(2000, 1, 3), get_time(self.custom_day_start_time))
		self.start_time = start.time().strftime("%H:%M:%S")
		self.end_time = (start - timedelta(minutes=1)).time().strftime("%H:%M:%S")
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

	def is_day_start_flexible(self):
		return bool(self.get("custom_is_flexible_shift")) and is_enabled("enable_flexible_overtime")

	def is_flexi_checkin(self):
		return bool(self.get("enable_flexible_checkin")) and is_enabled("enable_flexible_overtime")

	def process_auto_attendance(self, *args, **kwargs):
		"""A flexible shift marks its days from punches first, so core's absent marking that follows
		only sees days that really had no punches."""
		if self.is_day_start_flexible():
			process_flexible_attendance(shift_types=[self.name])
		return super().process_auto_attendance(*args, **kwargs)

	def should_mark_attendance(self, employee, attendance_date):
		"""Punches on a weekly off or public holiday still make an Attendance (their hours are OT2)."""
		if is_enabled("enable_flexible_overtime"):
			return True
		return super().should_mark_attendance(employee, attendance_date)

	def get_attendance(self, logs, *thresholds):
		"""Flexible check-in: expected end follows the check-in. Normal: core result with breaks
		deducted. Flexible timetable: minimum-work-time rules.

		HRMS v16 passes (absent, half day) thresholds, already halved on half holidays; v15 passes none.
		"""
		attendance_date = logs[0].shift_start.date()

		if self.is_flexi_checkin():
			result = flexi_checkin.evaluate(self, logs, lambda hours: self.status_for_hours(hours, *thresholds))
		elif not is_enabled("enable_timetable_rules"):
			status, hours, late_entry, early_exit, in_time, out_time = super().get_attendance(logs, *thresholds)
			result = frappe._dict(
				status=status, working_hours=hours, late_entry=late_entry, early_exit=early_exit,
				in_time=in_time, out_time=out_time, break_minutes=0, required_hours=None, remarks=None,
			)
		elif is_flexible(self):
			result = evaluate_flexible(self, logs, attendance_date, get_breaks(self))
		else:
			breaks = get_breaks(self)
			status, hours, late_entry, early_exit, in_time, out_time = super().get_attendance(logs, *thresholds)
			result = frappe._dict(
				status=status, working_hours=hours, late_entry=late_entry, early_exit=early_exit,
				in_time=in_time, out_time=out_time, break_minutes=0, required_hours=None, remarks=None,
			)
			if breaks and hours:
				intervals = worked_intervals(logs, self.determine_check_in_and_check_out, self.working_hours_calculation_based_on)
				window_start, _end = window_bounds(self, attendance_date)
				result.break_minutes = break_deduction_minutes(breaks, intervals, window_start)
				result.working_hours = max(0.0, round(hours - result.break_minutes / 60, 2))
				result.status = self.status_for_hours(result.working_hours, *thresholds)

		if not result.get("flexi") and result.late_entry and result.in_time:
			# minutes late against the shift start, for the attendance reports
			result.late_minutes = max(0, int((result.in_time - logs[0].shift_start).total_seconds() // 60))

		self.__dict__.setdefault("_attendance_details", {})[(logs[0].employee, attendance_date)] = result
		return (
			result.status, result.working_hours, bool(result.get("late_entry")),
			bool(result.get("early_exit")), result.in_time, result.out_time,
		)

	def status_for_hours(self, hours, absent_threshold=None, half_day_threshold=None):
		if absent_threshold is None:
			absent_threshold = flt(self.working_hours_threshold_for_absent)
		if half_day_threshold is None:
			half_day_threshold = flt(self.working_hours_threshold_for_half_day)
		if absent_threshold and hours < absent_threshold:
			return "Absent"
		if half_day_threshold and hours < half_day_threshold:
			return "Half Day"
		return "Present"

	def _process(self, logs):
		"""Core flow (v15 or v16) unchanged, then the Raysut fields on the Attendance it created."""
		if self.is_day_start_flexible():
			return  # attendance/flexible.py marks these days from the Day Start windows
		self._attendance_details = {}
		super()._process(logs)
		self.update_attendance_details()

	def update_attendance_details(self):
		for (employee, attendance_date), details in self._attendance_details.items():
			attendance, holiday_work = frappe.db.get_value(
				"Attendance",
				{"employee": employee, "attendance_date": attendance_date, "shift": self.name, "docstatus": 1},
				["name", "custom_is_holiday_work"],
			) or (None, 0)
			if not attendance:
				continue
			values = {"late_minutes": cint(details.get("late_minutes"))}
			if is_enabled("enable_timetable_rules") or details.get("flexi"):
				values.update(
					{
						"shift_mode": self.shift_mode or "Normal",
						"shift_pattern": get_shift_pattern(employee, self.name, attendance_date),
						"required_work_hours": details.required_hours,
						"break_deducted_minutes": cint(details.break_minutes),
						"flexible_remarks": details.remarks,
					}
				)
			if details.get("flexi"):
				values.update(
					{
						"flexi_shift_applied": 1,
						"expected_checkout_time": details.expected_checkout_time,
						# work on a weekly off or holiday is all OT2, never short
						"under_time_minutes": 0 if holiday_work else details.under_time_minutes,
						"custom_missing_punch": 1 if details.missing_punch else 0,
					}
				)
			frappe.db.set_value("Attendance", attendance, values, update_modified=False)
		self._attendance_details = {}
		if not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep - core commits the attendance itself; keep the details with it


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
