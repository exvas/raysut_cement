# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Part H of the scheduling spec: timetables, patterns, schedules and attendance."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import frappe
from erpnext.setup.doctype.employee.test_employee import make_employee
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today
from hrms.hr.doctype.shift_assignment.shift_assignment import get_employee_shift
from hrms.hr.doctype.shift_type.shift_type import ShiftType

from raysut_cement.raysut_cement.scheduling import generator
from raysut_cement.raysut_cement.scheduling.pattern import slot_for_date, timetables_for_date
from raysut_cement.raysut_cement.scheduling.timetable import evaluate_flexible

PAST_DAY = date(2026, 9, 7)  # a Monday well before "today" in every run


class SchedulingTestCase(FrappeTestCase):
	def setUp(self):
		for patcher in (patch.object(frappe.db, "commit"), patch.object(frappe, "log_error")):
			patcher.start()
			self.addCleanup(patcher.stop)
		self.addCleanup(frappe.db.rollback)
		self.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		self.holiday_list = self.make_holiday_list()
		self.counter = 0

	# ------------------------------------------------------------ fixtures

	def make_holiday_list(self):
		name = "RC Scheduling Test Holidays"
		if not frappe.db.exists("Holiday List", name):
			frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": name, "from_date": "2025-01-01", "to_date": "2028-12-31"}).insert()
		return name

	def employee(self, **kwargs):
		self.counter += 1
		email = f"rc.sched.{frappe.generate_hash(length=6)}@example.com"
		kwargs.setdefault("company", self.company)
		kwargs.setdefault("date_of_joining", "2025-01-01")
		kwargs.setdefault("holiday_list", self.holiday_list)
		return make_employee(email, **kwargs)

	def timetable(self, name, start, end, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Shift Type",
				"__newname": f"RC {name} {frappe.generate_hash(length=4)}",
				"start_time": start,
				"end_time": end,
				"shift_color": "#3498db",
				"enable_auto_attendance": 1,
				"process_attendance_after": "2025-01-01",
				"determine_check_in_and_check_out": "Alternating entries as IN and OUT during the same shift",
				"working_hours_calculation_based_on": "First Check-in and Last Check-out",
				**kwargs,
			}
		)
		return doc.insert()

	def flexible(self, name, start, end, min_hours, end_day="Current Day", **kwargs):
		return self.timetable(
			name, start, end, shift_mode="Flexible", valid_period_start=start, valid_period_end=end,
			valid_period_end_day=end_day, min_work_hours=min_hours, min_work_minutes=0, **kwargs,
		)

	def break_timetable(self, **kwargs):
		return frappe.get_doc({"doctype": "Break Timetable", "break_name": f"RC Break {frappe.generate_hash(length=4)}", **kwargs}).insert()

	def assign_shift(self, employee, shift, start, end=None):
		doc = frappe.get_doc(
			{"doctype": "Shift Assignment", "employee": employee, "shift_type": shift, "company": self.company,
			 "start_date": start, "end_date": end or start, "status": "Active"}
		).insert()
		doc.submit()
		return doc

	def punch(self, employee, when):
		return frappe.get_doc({"doctype": "Employee Checkin", "employee": employee, "time": when}).insert()

	def process(self, shift_name, until):
		frappe.db.set_value("Shift Type", shift_name, "last_sync_of_checkin", until)
		frappe.get_doc("Shift Type", shift_name).process_auto_attendance()

	def attendance(self, employee, day, shift=None):
		filters = {"employee": employee, "attendance_date": day, "docstatus": 1}
		if shift:
			filters["shift"] = shift
		return frappe.db.get_value(
			"Attendance", filters,
			["status", "working_hours", "late_entry", "early_exit", "flexible_remarks", "break_deducted_minutes",
			 "required_work_hours", "shift_mode", "shift_pattern"],
			as_dict=True,
		)

	def run_flexible_day(self, shift, punches, day=PAST_DAY):
		employee = self.employee()
		self.assign_shift(employee, shift.name, day, add_days(day, 1))
		for hh_mm in punches:
			self.punch(employee, datetime.combine(day, datetime.strptime(hh_mm, "%H:%M").time()))
		self.process(shift.name, datetime.combine(add_days(day, 2), datetime.min.time()))
		return self.attendance(employee, day)

	def pattern(self, mode, every, days, week_starts_on="Sunday"):
		doc = frappe.get_doc(
			{
				"doctype": "Shift Pattern",
				"pattern_name": f"RC Pattern {frappe.generate_hash(length=5)}",
				"repeat_mode": mode,
				"repeat_every": every,
				"week_starts_on": week_starts_on,
				"days": [{"cycle_index": c, "day_key": k, "timetable": t} for c, k, t in days],
			}
		)
		return doc.insert()

	def schedule(self, pattern, start, horizon=14, **target):
		target = target or {"assign_to": "Employee"}
		doc = frappe.get_doc(
			{
				"doctype": "Shift Pattern Assignment",
				"shift_pattern": pattern,
				"company": self.company,
				"start_date": start,
				"generation_horizon_days": horizon,
				**target,
			}
		)
		doc.insert()
		doc.submit()
		return doc

	def generated(self, employee, assignment=None):
		filters = {"employee": employee, "docstatus": 1}
		if assignment:
			filters["shift_pattern_assignment"] = assignment
		return frappe.get_all(
			"Shift Assignment", filters=filters, fields=["name", "shift_type", "start_date", "end_date", "shift_pattern_assignment"],
			order_by="start_date",
		)


def next_weekday(start, weekday):
	"""Next date on/after `start` with python weekday() == weekday."""
	start = getdate(start)
	return start + timedelta(days=(weekday - start.weekday()) % 7)


# ================================================================ Part E: attendance


class TestFlexibleAttendance(SchedulingTestCase):
	def test_01_below_minimum_is_absent_or_half_day(self):
		shift = self.flexible("Flex9", "09:00:00", "18:00:00", 9)
		att = self.run_flexible_day(shift, ["09:05", "18:00"])
		self.assertEqual(att.status, "Absent")
		self.assertAlmostEqual(att.working_hours, 8.92, places=2)
		self.assertEqual(att.flexible_remarks, "Below minimum work time")

		half = self.flexible("Flex9H", "09:00:00", "18:00:00", 9, half_day_if_below_min=1, flexible_half_day_hours=4)
		self.assertEqual(self.run_flexible_day(half, ["09:05", "18:00"]).status, "Half Day")

	def test_02_full_window_is_present_without_late_flag(self):
		shift = self.flexible("Flex9", "09:00:00", "18:00:00", 9)
		att = self.run_flexible_day(shift, ["09:00", "18:00"])
		self.assertEqual(att.status, "Present")
		self.assertEqual(att.late_entry, 0)
		self.assertEqual(att.early_exit, 0)
		self.assertEqual((att.shift_mode, att.required_work_hours), ("Flexible", 9))

	def test_03_check_in_after_latest_time_is_absent(self):
		shift = self.flexible("FlexLatest", "09:00:00", "18:00:00", 4, enable_latest_check_in=1,
			latest_check_in_day="Current Day", latest_check_in_time="12:00:00")
		att = self.run_flexible_day(shift, ["12:30", "18:00"])
		self.assertEqual(att.status, "Absent")
		self.assertEqual(att.flexible_remarks, "Check-in after latest allowed time")

	def test_04_fixed_break_deducted_only_on_overlap(self):
		lunch = self.break_timetable(break_type="Fixed", break_start="13:00:00", break_end="14:00:00")
		shift = self.flexible("FlexBreak", "09:00:00", "18:00:00", 8, timetable_breaks=[{"break_timetable": lunch.name}])
		full = self.run_flexible_day(shift, ["09:00", "18:00"])
		self.assertEqual((full.break_deducted_minutes, full.working_hours, full.status), (60, 8.0, "Present"))
		partial = self.run_flexible_day(shift, ["09:00", "13:30"])
		self.assertEqual(partial.break_deducted_minutes, 30)
		afternoon = self.run_flexible_day(shift, ["14:30", "18:00"])
		self.assertEqual(afternoon.break_deducted_minutes, 0)

	def test_04b_flexible_break_deducted_once_when_worked_longer(self):
		rest = self.break_timetable(break_type="Flexible", break_duration_minutes=45)
		shift = self.flexible("FlexFB", "09:00:00", "18:00:00", 5, timetable_breaks=[{"break_timetable": rest.name}])
		logs = [frappe._dict(time=datetime(2026, 9, 7, 9, 0)), frappe._dict(time=datetime(2026, 9, 7, 9, 30))]
		self.assertEqual(evaluate_flexible(shift, logs, PAST_DAY).break_minutes, 0)
		logs[1].time = datetime(2026, 9, 7, 15, 0)
		self.assertEqual(evaluate_flexible(shift, logs, PAST_DAY).break_minutes, 45)

	def test_05_cross_midnight_flexible(self):
		shift = self.flexible("FlexNight", "20:00:00", "06:00:00", 9, end_day="Next Day")
		employee = self.employee()
		self.assign_shift(employee, shift.name, PAST_DAY)  # one night only
		self.punch(employee, datetime.combine(PAST_DAY, datetime.strptime("20:00", "%H:%M").time()))
		self.punch(employee, datetime.combine(add_days(PAST_DAY, 1), datetime.strptime("05:30", "%H:%M").time()))
		self.process(shift.name, datetime.combine(add_days(PAST_DAY, 3), datetime.min.time()))
		att = self.attendance(employee, PAST_DAY)
		self.assertEqual((att.status, att.working_hours), ("Present", 9.5))
		self.assertIsNone(self.attendance(employee, add_days(PAST_DAY, 1)))

	def test_05b_single_punch_is_missing_checkout(self):
		shift = self.flexible("FlexOne", "09:00:00", "18:00:00", 8)
		att = self.run_flexible_day(shift, ["09:00"])
		self.assertEqual((att.status, att.flexible_remarks), ("Absent", "Missing check-out"))

	def test_06_normal_mode_matches_core(self):
		shift = self.timetable("Normal", "09:00:00", "17:00:00", enable_late_entry_marking=1, late_entry_grace_period=10,
			enable_early_exit_marking=1, early_exit_grace_period=10, working_hours_threshold_for_half_day=6,
			working_hours_threshold_for_absent=3)
		core = ShiftType(shift.as_dict())
		day_start = datetime.combine(PAST_DAY, datetime.min.time())
		for punches in [(9, 0, 17, 0), (9, 30, 16, 0), (9, 0, 13, 0), (9, 0, 11, 0)]:
			logs = [
				frappe._dict(time=day_start.replace(hour=punches[0], minute=punches[1]), log_type=None,
					shift_start=day_start.replace(hour=9), shift_end=day_start.replace(hour=17)),
				frappe._dict(time=day_start.replace(hour=punches[2], minute=punches[3]), log_type=None,
					shift_start=day_start.replace(hour=9), shift_end=day_start.replace(hour=17)),
			]
			self.assertEqual(shift.get_attendance(logs), core.get_attendance(logs), punches)

	def test_06b_normal_mode_with_break_deducts_and_rechecks_threshold(self):
		lunch = self.break_timetable(break_type="Fixed", break_start="13:00:00", break_end="14:00:00")
		shift = self.timetable("NormalBreak", "09:00:00", "17:00:00", working_hours_threshold_for_half_day=7.5,
			timetable_breaks=[{"break_timetable": lunch.name}])
		att = self.run_flexible_day(shift, ["09:00", "17:00"])
		self.assertEqual((att.working_hours, att.break_deducted_minutes, att.status), (7.0, 60, "Half Day"))

	def test_06c_v16_thresholds_passed_in_are_used(self):
		"""HRMS v16 calls get_attendance(logs, absent, half_day), halved on half holidays."""
		lunch = self.break_timetable(break_type="Fixed", break_start="13:00:00", break_end="14:00:00")
		shift = self.timetable("NormalV16", "09:00:00", "17:00:00", working_hours_threshold_for_half_day=7.5,
			timetable_breaks=[{"break_timetable": lunch.name}])
		day_start = datetime.combine(PAST_DAY, datetime.min.time())
		logs = [
			frappe._dict(employee="EMP-X", time=day_start.replace(hour=h), log_type=None,
				shift_start=day_start.replace(hour=9), shift_end=day_start.replace(hour=17))
			for h in (9, 17)
		]
		self.assertEqual(shift.get_attendance(logs)[:2], ("Half Day", 7.0))
		# stand-in for the v16 core method so this also runs on v15
		v16_core = lambda self, logs, *thresholds: ("Present", 8.0, False, False, logs[0].time, logs[-1].time)  # noqa
		with patch.object(ShiftType, "get_attendance", v16_core):
			self.assertEqual(shift.get_attendance(logs, 0, 3.75)[:2], ("Present", 7.0))
			self.assertEqual(shift.get_attendance(logs, 0, 7.5)[:2], ("Half Day", 7.0))


class TestTimetableValidation(SchedulingTestCase):
	def test_flexible_window_drives_start_end(self):
		shift = self.flexible("FlexSync", "08:00:00", "17:00:00", 8)
		self.assertEqual((str(shift.start_time), str(shift.end_time)), ("08:00:00", "17:00:00"))
		self.assertEqual(shift.begin_check_in_before_shift_start_time, 0)

	def test_invalid_flexible_settings(self):
		with self.assertRaises(frappe.ValidationError):
			self.flexible("Bad1", "18:00:00", "09:00:00", 8)  # end before start on the same day
		with self.assertRaises(frappe.ValidationError):
			self.flexible("Bad2", "09:00:00", "12:00:00", 5)  # minimum longer than window
		with self.assertRaises(frappe.ValidationError):
			self.flexible("Bad3", "09:00:00", "18:00:00", 8, enable_latest_check_in=1,
				latest_check_in_day="Current Day", latest_check_in_time="08:00:00")

	def test_breaks_inside_window_and_not_overlapping(self):
		b1 = self.break_timetable(break_type="Fixed", break_start="12:00:00", break_end="13:00:00")
		b2 = self.break_timetable(break_type="Fixed", break_start="12:30:00", break_end="13:30:00")
		outside = self.break_timetable(break_type="Fixed", break_start="19:00:00", break_end="19:30:00")
		with self.assertRaises(frappe.ValidationError):
			self.timetable("Overlap", "09:00:00", "18:00:00", timetable_breaks=[{"break_timetable": b1.name}, {"break_timetable": b2.name}])
		with self.assertRaises(frappe.ValidationError):
			self.timetable("Outside", "09:00:00", "18:00:00", timetable_breaks=[{"break_timetable": outside.name}])


# ================================================================ Part C/D: patterns and schedules


class TestShiftPatterns(SchedulingTestCase):
	def setUp(self):
		super().setUp()
		self.day_shift = self.flexible("PatDay", "09:00:00", "18:00:00", 9).name

	def week_pattern(self, every=1, rest=("Friday",)):
		days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
		return self.pattern("Week", every, [(1, d, self.day_shift) for d in days if d not in rest])

	def test_07_week_pattern_friday_rest(self):
		pattern = self.week_pattern()
		employee = self.employee()
		anchor = next_weekday(add_days(today(), 1), 6)  # next Sunday
		spa = self.schedule(pattern.name, anchor, horizon=21, assign_to="Employee", employee=employee)

		sas = self.generated(employee, spa.name)
		self.assertTrue(sas)
		for sa in sas:
			for offset in range((sa.end_date - sa.start_date).days + 1):
				self.assertNotEqual(add_days(sa.start_date, offset).weekday(), 4, "nothing on Friday")
		# Sun-Thu merged into one assignment, then Sat + next Sun-Thu merged
		self.assertEqual((sas[0].start_date, sas[0].end_date), (anchor, add_days(anchor, 4)))
		self.assertEqual((sas[1].start_date, sas[1].end_date), (add_days(anchor, 6), add_days(anchor, 11)))

		friday = datetime.combine(add_days(anchor, 5), datetime.min.time()).replace(hour=10)
		self.assertEqual(get_employee_shift(employee, friday, True), {}, "rest day: no shift, so never Absent")

	def test_08_alternating_weeks(self):
		pattern = self.pattern("Week", 2, [(1, "Monday", self.day_shift), (2, "Tuesday", self.day_shift)])
		anchor = date(2026, 1, 4)  # Sunday
		self.assertEqual(slot_for_date(pattern, anchor, date(2026, 1, 5)), (1, "Monday"))
		self.assertEqual(slot_for_date(pattern, anchor, date(2026, 1, 13)), (2, "Tuesday"))
		self.assertEqual(slot_for_date(pattern, anchor, date(2026, 1, 19)), (1, "Monday"))
		self.assertEqual(timetables_for_date(pattern, anchor, date(2026, 1, 12)), [])  # week 2 Monday = rest
		# anchor mid-week: week 1 is still the calendar week that contains the anchor
		self.assertEqual(slot_for_date(pattern, date(2026, 1, 7), date(2026, 1, 11)), (2, "Sunday"))

		employee = self.employee()
		start = next_weekday(add_days(today(), 1), 6)
		spa = self.schedule(pattern.name, start, horizon=28, assign_to="Employee", employee=employee)
		weekdays = {(sa.start_date - start).days for sa in self.generated(employee, spa.name)}
		self.assertEqual(weekdays, {1, 9, 15, 23})  # Mon wk1, Tue wk2, Mon wk3, Tue wk4

	def test_09_day_cycle_across_month_boundary(self):
		pattern = self.pattern("Day", 4, [(1, "Day 1", self.day_shift), (2, "Day 2", self.day_shift)])
		anchor = date(2026, 1, 30)
		on_days = [d for d in range(8) if timetables_for_date(pattern, anchor, add_days(anchor, d))]
		self.assertEqual(on_days, [0, 1, 4, 5])  # Jan 30-31 on, Feb 1-2 off, Feb 3-4 on

		employee = self.employee()
		start = add_days(today(), 1)
		spa = self.schedule(pattern.name, start, horizon=12, assign_to="Employee", employee=employee)
		runs = [((sa.start_date - getdate(start)).days, (sa.end_date - sa.start_date).days + 1) for sa in self.generated(employee, spa.name)]
		self.assertEqual(runs[:3], [(0, 2), (4, 2), (8, 2)])

	def test_10_month_pattern_skips_missing_31st(self):
		pattern = self.pattern("Month", 1, [(1, "31", self.day_shift)])
		anchor = date(2026, 4, 1)
		self.assertEqual(timetables_for_date(pattern, anchor, date(2026, 4, 30)), [])
		self.assertEqual(timetables_for_date(pattern, anchor, date(2026, 5, 31)), [self.day_shift])
		self.assertEqual(timetables_for_date(pattern, anchor, date(2026, 6, 30)), [])

	def test_11_department_joiners_and_leavers(self):
		dept = frappe.get_doc({"doctype": "Department", "department_name": f"RC Dept {frappe.generate_hash(length=4)}", "company": self.company}).insert()
		first = self.employee(department=dept.name)
		pattern = self.pattern("Day", 1, [(1, "Day 1", self.day_shift)])
		spa = self.schedule(pattern.name, add_days(today(), 1), horizon=10, assign_to="Department", department=dept.name)
		self.assertTrue(self.generated(first, spa.name))

		joiner = self.employee(department=dept.name)
		self.assertFalse(self.generated(joiner, spa.name))
		relieving = add_days(today(), 4)
		frappe.db.set_value("Employee", first, "relieving_date", relieving)

		generator.daily_generation()

		self.assertTrue(self.generated(joiner, spa.name), "new joiner picked up by the daily run")
		self.assertTrue(all(getdate(sa.end_date) <= getdate(relieving) for sa in self.generated(first, spa.name)))

	def test_12_pattern_edit_regenerates_future_only(self):
		other_shift = self.flexible("PatOther", "07:00:00", "16:00:00", 9).name
		pattern = self.pattern("Day", 1, [(1, "Day 1", self.day_shift)])
		employee = self.employee()
		spa = self.schedule(pattern.name, add_days(today(), -5), horizon=10, assign_to="Employee", employee=employee)

		# a past generated shift and a manual shift elsewhere
		past = self.assign_shift(employee, self.day_shift, add_days(today(), -5), add_days(today(), -1))
		frappe.db.set_value("Shift Assignment", past.name, "shift_pattern_assignment", spa.name)
		manual = self.assign_shift(employee, other_shift, add_days(today(), 30), add_days(today(), 31))

		pattern.reload()
		pattern.days[0].timetable = other_shift
		pattern.save()

		future = [sa for sa in self.generated(employee, spa.name) if getdate(sa.start_date) > getdate(today())]
		self.assertTrue(future)
		self.assertTrue(all(sa.shift_type == other_shift for sa in future))
		self.assertEqual(frappe.db.get_value("Shift Assignment", past.name, ["docstatus", "end_date"]), (1, getdate(add_days(today(), -1))))
		self.assertEqual(frappe.db.get_value("Shift Assignment", manual.name, "docstatus"), 1)
		today_sa = [sa for sa in self.generated(employee, spa.name) if getdate(sa.start_date) <= getdate(today()) <= getdate(sa.end_date)]
		self.assertEqual([sa.shift_type for sa in today_sa], [self.day_shift], "today keeps its original timetable")

	def test_12b_manual_assignment_is_never_overridden(self):
		pattern = self.pattern("Day", 1, [(1, "Day 1", self.day_shift)])
		employee = self.employee()
		manual = self.assign_shift(employee, self.day_shift, add_days(today(), 3), add_days(today(), 3))
		spa = self.schedule(pattern.name, add_days(today(), 1), horizon=6, assign_to="Employee", employee=employee)
		covered = [add_days(sa.start_date, i) for sa in self.generated(employee, spa.name) for i in range((sa.end_date - sa.start_date).days + 1)]
		self.assertNotIn(getdate(add_days(today(), 3)), covered)
		self.assertEqual(frappe.db.get_value("Shift Assignment", manual.name, "docstatus"), 1)
		spa.reload()
		self.assertTrue(any(row.employee == employee for row in spa.generation_log))

	def test_13_two_timetables_one_day(self):
		frappe.db.set_single_value("HR Settings", "allow_multiple_shift_assignments", 1)
		morning = self.timetable("AM", "06:00:00", "10:00:00", begin_check_in_before_shift_start_time=0, allow_check_out_after_shift_end_time=0).name
		evening = self.timetable("PM", "14:00:00", "18:00:00", begin_check_in_before_shift_start_time=0, allow_check_out_after_shift_end_time=0).name
		pattern = self.pattern("Day", 1, [(1, "Day 1", morning), (1, "Day 1", evening)])
		employee = self.employee()
		day = getdate(today())
		spa = self.schedule(pattern.name, day, horizon=0 + 1, assign_to="Employee", employee=employee)
		self.assertEqual(sorted(sa.shift_type for sa in self.generated(employee, spa.name)), sorted([morning, evening]))

		for hour in (6, 10, 14, 18):
			self.punch(employee, datetime.combine(day, datetime.min.time()).replace(hour=hour))
		until = datetime.combine(add_days(day, 1), datetime.min.time()).replace(hour=1)
		self.process(morning, until)
		self.process(evening, until)
		self.assertEqual(self.attendance(employee, day, morning).status, "Present")
		self.assertEqual(self.attendance(employee, day, evening).status, "Present")
		self.assertEqual(self.attendance(employee, day, morning).shift_pattern, pattern.name)

	def test_overlapping_timetables_rejected(self):
		late = self.flexible("PatLate", "12:00:00", "21:00:00", 8).name
		with self.assertRaises(frappe.ValidationError):
			self.pattern("Day", 1, [(1, "Day 1", self.day_shift), (1, "Day 1", late)])

	def test_cross_midnight_overlaps_next_day(self):
		night = self.flexible("PatNight", "20:00:00", "10:00:00", 9, end_day="Next Day").name
		with self.assertRaises(frappe.ValidationError):
			self.pattern("Day", 2, [(1, "Day 1", night), (2, "Day 2", self.day_shift)])

	def test_two_active_schedules_for_one_employee_rejected(self):
		pattern = self.pattern("Day", 1, [(1, "Day 1", self.day_shift)])
		employee = self.employee()
		self.schedule(pattern.name, add_days(today(), 1), horizon=3, assign_to="Employee", employee=employee)
		with self.assertRaises(frappe.ValidationError):
			self.schedule(pattern.name, add_days(today(), 2), horizon=3, assign_to="Employee", employee=employee)

	def test_cancel_removes_future_generated_shifts(self):
		pattern = self.pattern("Day", 1, [(1, "Day 1", self.day_shift)])
		employee = self.employee()
		spa = self.schedule(pattern.name, add_days(today(), 1), horizon=5, assign_to="Employee", employee=employee)
		self.assertTrue(self.generated(employee, spa.name))
		spa.cancel()
		self.assertFalse(self.generated(employee, spa.name))


# ================================================================ Part F: reports


class TestReports(SchedulingTestCase):
	def test_shift_roster_colours_rest_days_and_holidays(self):
		from raysut_cement.raysut_cement.report.shift_roster.shift_roster import column_key, execute

		shift = self.flexible("Roster", "09:00:00", "18:00:00", 8, shift_color="#ff0000")
		pattern = self.pattern("Day", 2, [(1, "Day 1", shift.name)])
		employee = self.employee()
		start = getdate(add_days(today(), 1))
		self.schedule(pattern.name, start, horizon=6, assign_to="Employee", employee=employee)
		holiday_list = frappe.get_doc("Holiday List", self.holiday_list)
		holiday_list.append("holidays", {"holiday_date": add_days(start, 2), "description": "Test"})
		holiday_list.save()

		_columns, data = execute({"company": self.company, "from_date": start, "to_date": add_days(start, 3), "employee": employee})
		row = data[0]
		self.assertEqual(row[column_key(start)], shift.name)
		self.assertEqual(row["_colors"][column_key(start)], "#ff0000")
		self.assertEqual(row[column_key(add_days(start, 1))], "", "rest day is blank")
		self.assertIn(column_key(add_days(start, 2)), row["_holidays"])

	def test_work_hours_report_flags_shortfall_and_rest_day_work(self):
		from raysut_cement.raysut_cement.report.flexible_shift_work_hours.flexible_shift_work_hours import execute

		shift = self.flexible("Report", "09:00:00", "18:00:00", 9)
		employee = self.employee()
		self.assign_shift(employee, shift.name, PAST_DAY)
		self.punch(employee, datetime(2026, 9, 7, 9, 30))
		self.punch(employee, datetime(2026, 9, 7, 18, 0))
		self.process(shift.name, datetime(2026, 9, 9))
		self.punch(employee, datetime(2026, 9, 8, 10, 0))  # no shift that day
		self.punch(employee, datetime(2026, 9, 8, 12, 0))

		_columns, data = execute({"company": self.company, "from_date": "2026-09-07", "to_date": "2026-09-08", "employee": employee})
		worked, rest = data
		self.assertEqual((worked["net_hours"], worked["required_hours"], worked["difference"]), (8.5, 9, -0.5))
		self.assertEqual(worked["below_required"], 1)
		self.assertEqual((rest["status"], rest["gross_hours"]), ("Rest Day Work", 2.0))
