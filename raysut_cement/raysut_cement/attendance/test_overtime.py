# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Flexible Shift & Overtime: day-start windows, OT1 / OT2 and holiday work."""

from datetime import date, datetime

import frappe

from raysut_cement.raysut_cement.attendance.flexible import attendance_date_for, process_flexible_attendance
from raysut_cement.raysut_cement.attendance.overtime import calculate_overtime, recalculate_overtime, required_hours
from raysut_cement.raysut_cement.scheduling.test_scheduling import SchedulingTestCase

MONDAY, TUESDAY, WEDNESDAY, THURSDAY = date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)
FRIDAY = date(2026, 9, 11)
PUBLIC_HOLIDAY = WEDNESDAY


def at(day, hh_mm, days_later=0):
	return datetime.combine(frappe.utils.add_days(day, days_later), datetime.strptime(hh_mm, "%H:%M").time())


class TestOvertime(SchedulingTestCase):
	def setUp(self):
		super().setUp()
		self.holidays = self.make_ot_holiday_list()
		self.flex = self.timetable(
			"Flex OT", "05:00:00", "04:59:00",
			custom_is_flexible_shift=1, custom_day_start_time="05:00:00",
			custom_required_working_hours=8, custom_ot_min_hours=1, custom_ot_max_hours=3,
		)
		self.emp = self.employee(holiday_list=self.holidays)
		frappe.db.set_value("Employee", self.emp, "default_shift", self.flex.name)

	def make_ot_holiday_list(self):
		name = "RC Overtime Test Holidays"
		if not frappe.db.exists("Holiday List", name):
			frappe.get_doc(
				{
					"doctype": "Holiday List",
					"holiday_list_name": name,
					"from_date": "2026-01-01",
					"to_date": "2026-12-31",
					"holidays": [
						{"holiday_date": "2026-09-04", "description": "Friday", "weekly_off": 1},
						{"holiday_date": "2026-09-11", "description": "Friday", "weekly_off": 1},
						{"holiday_date": "2026-09-09", "description": "Public holiday", "weekly_off": 0},
					],
				}
			).insert()
		return name

	def work(self, day, *punches, employee=None):
		employee = employee or self.emp
		for when in punches:
			self.punch(employee, when)
		return self.process_and_get(day, employee)

	def process_and_get(self, day, employee=None, **kwargs):
		employee = employee or self.emp
		process_flexible_attendance(day, frappe.utils.add_days(day, 1), employee=employee, **kwargs)
		return frappe.db.get_value(
			"Attendance",
			{"employee": employee, "attendance_date": day, "docstatus": 1},
			["name", "status", "in_time", "out_time", "working_hours", "custom_worked_hours", "custom_ot1_hours",
			 "custom_ot2_hours", "custom_is_holiday_work", "custom_missing_punch"],
			as_dict=True,
		)

	# ------------------------------------------------------------ rules

	def test_calculate_overtime_rules(self):
		self.assertEqual(calculate_overtime(8.5, 8, 1, 3), (0.0, 0.0))  # extra below OT min
		self.assertEqual(calculate_overtime(10, 8, 1, 3), (2.0, 0.0))
		self.assertEqual(calculate_overtime(13, 8, 1, 3), (3.0, 0.0))  # capped at OT max
		self.assertEqual(calculate_overtime(13, 8, 1, 0), (5.0, 0.0))  # no max
		self.assertEqual(calculate_overtime(6, 8, 0, 0), (0.0, 0.0))
		self.assertEqual(calculate_overtime(13.456, 8, 1, 3, holiday=True), (0.0, 13.46))

	def test_fixed_shift_required_hours_fall_back_to_duration(self):
		shift = frappe._dict(start_time="07:30:00", end_time="15:00:00")
		self.assertEqual(required_hours(shift), 7.5)
		self.assertEqual(required_hours(frappe._dict(start_time="22:00:00", end_time="06:00:00")), 8)
		self.assertEqual(required_hours(frappe._dict(start_time="07:30:00", end_time="15:00:00", custom_required_working_hours=8)), 8)

	# ------------------------------------------------------------ flexible days

	def test_night_punch_before_day_start_goes_to_previous_date(self):
		self.assertEqual(attendance_date_for(self.flex, at(TUESDAY, "02:30")), MONDAY)
		self.assertEqual(attendance_date_for(self.flex, at(TUESDAY, "05:00")), TUESDAY)

		monday = self.work(MONDAY, at(MONDAY, "21:00"), at(TUESDAY, "02:30"), at(TUESDAY, "06:00"))
		self.assertEqual((monday.in_time, monday.out_time), (at(MONDAY, "21:00"), at(TUESDAY, "02:30")))
		self.assertEqual((monday.status, monday.custom_worked_hours, monday.custom_ot1_hours), ("Present", 5.5, 0))

		tuesday = self.process_and_get(TUESDAY)
		self.assertEqual((tuesday.in_time, tuesday.custom_missing_punch), (at(TUESDAY, "06:00"), 1))
		linked = frappe.get_all("Employee Checkin", {"employee": self.emp}, ["time", "attendance"], order_by="time")
		self.assertEqual([c.attendance for c in linked], [monday.name, monday.name, tuesday.name])

	def test_extra_below_ot_min_gives_no_ot1(self):
		attendance = self.work(MONDAY, at(MONDAY, "07:00"), at(MONDAY, "15:30"))
		self.assertEqual((attendance.custom_worked_hours, attendance.custom_ot1_hours, attendance.custom_ot2_hours), (8.5, 0, 0))

	def test_extra_above_ot_max_is_capped(self):
		attendance = self.work(MONDAY, at(MONDAY, "07:00"), at(MONDAY, "20:00"))
		self.assertEqual((attendance.custom_worked_hours, attendance.custom_ot1_hours), (13, 3))

	def test_friday_work_is_all_ot2(self):
		attendance = self.work(FRIDAY, at(FRIDAY, "07:00"), at(FRIDAY, "12:00"))
		self.assertEqual(
			(attendance.status, attendance.custom_is_holiday_work, attendance.custom_ot1_hours, attendance.custom_ot2_hours),
			("Present", 1, 0, 5),
		)

	def test_public_holiday_work_is_all_ot2_without_cap(self):
		attendance = self.work(PUBLIC_HOLIDAY, at(PUBLIC_HOLIDAY, "07:00"), at(PUBLIC_HOLIDAY, "20:00"))
		self.assertEqual((attendance.custom_is_holiday_work, attendance.custom_ot1_hours, attendance.custom_ot2_hours), (1, 0, 13))

	def test_single_punch_is_missing_punch_without_ot(self):
		attendance = self.work(THURSDAY, at(THURSDAY, "07:00"))
		self.assertEqual(
			(attendance.custom_missing_punch, attendance.working_hours, attendance.custom_ot1_hours, attendance.out_time),
			(1, 0, 0, None),
		)

	def test_no_punches_marks_nothing(self):
		self.assertIsNone(self.process_and_get(MONDAY))

	def test_submitted_attendance_changes_only_on_reprocess(self):
		first = self.work(MONDAY, at(MONDAY, "07:00"), at(MONDAY, "15:00"))
		self.punch(self.emp, at(MONDAY, "18:00"))
		self.assertEqual(self.process_and_get(MONDAY).name, first.name)

		again = self.process_and_get(MONDAY, reprocess=1)
		self.assertNotEqual(again.name, first.name)
		self.assertEqual((again.custom_worked_hours, again.custom_ot1_hours), (11, 3))
		self.assertEqual(frappe.db.get_value("Attendance", first.name, "docstatus"), 2)

	def test_shift_assignment_wins_over_default_shift(self):
		fixed = self.timetable("Fixed OT", "07:30:00", "15:00:00")
		self.assign_shift(self.emp, fixed.name, MONDAY)
		self.assertIsNone(self.work(MONDAY, at(MONDAY, "07:00"), at(MONDAY, "15:30")))

	def test_core_auto_attendance_runs_the_flexible_days_first(self):
		# core's hourly run looks back a few days, so use a recent day
		day = frappe.utils.getdate(frappe.utils.add_days(frappe.utils.nowdate(), -2))
		self.punch(self.emp, at(day, "07:00"))
		self.punch(self.emp, at(day, "16:00"))
		self.process(self.flex.name, frappe.utils.now_datetime())
		attendance = frappe.db.get_value(
			"Attendance", {"employee": self.emp, "attendance_date": day, "docstatus": 1}, ["status", "custom_worked_hours"], as_dict=True
		)
		self.assertEqual((attendance.status, attendance.custom_worked_hours), ("Present", 9))

	def test_recalculate_imported_history_uses_default_shift(self):
		from raysut_cement.raysut_cement.tams_import import import_timesheet

		code = f"R{frappe.generate_hash(length=5)}"
		frappe.db.set_value("Employee", self.emp, "employee_number", code)
		import_timesheet(
			[
				[code, str(MONDAY), "PR", f"{MONDAY} 07:00:00", f"{MONDAY} 20:00:00", "13", "0"],
				[code, str(FRIDAY), "PR", f"{FRIDAY} 07:00:00", f"{FRIDAY} 12:00:00", "5", "0"],
				[code, str(THURSDAY), "AB", "", "", "0", "0"],
			],
			self.company,
		)
		self.assertEqual(recalculate_overtime(MONDAY, FRIDAY, self.emp), 2)  # the Absent day has nothing to fill
		values = {
			str(a.attendance_date): (a.custom_worked_hours, a.custom_ot1_hours, a.custom_ot2_hours, a.custom_is_holiday_work)
			for a in frappe.get_all(
				"Attendance", {"employee": self.emp},
				["attendance_date", "custom_worked_hours", "custom_ot1_hours", "custom_ot2_hours", "custom_is_holiday_work"],
			)
		}
		self.assertEqual(values[str(MONDAY)], (13, 3, 0, 0))
		self.assertEqual(values[str(FRIDAY)], (5, 0, 5, 1))
		self.assertEqual(recalculate_overtime(MONDAY, FRIDAY, self.emp), 0)

	def test_employee_without_a_shift_gets_no_ot1(self):
		employee = self.employee(holiday_list=self.holidays)
		values = {}
		for day in (MONDAY, FRIDAY):
			doc = frappe.get_doc(
				{"doctype": "Attendance", "employee": employee, "attendance_date": day, "status": "Present",
				 "working_hours": 9, "company": self.company}
			).insert()
			values[day] = (doc.custom_worked_hours, doc.custom_ot1_hours, doc.custom_ot2_hours)
		self.assertEqual(values[MONDAY], (9, 0, 0))  # no shift: no basic hours to be over
		self.assertEqual(values[FRIDAY], (9, 0, 9))  # holiday work is still OT2

	def test_under_time_on_a_short_working_day_only(self):
		fixed = self.timetable("UT", "07:00:00", "15:00:00", flexi_undertime_tolerance=5)
		with_shift = self.employee(holiday_list=self.holidays, default_shift=fixed.name)
		without_shift = self.employee(holiday_list=self.holidays)

		def under_time(employee, day, hours, status="Present"):
			return frappe.get_doc(
				{"doctype": "Attendance", "employee": employee, "attendance_date": day, "status": status,
				 "working_hours": hours, "company": self.company}
			).insert().under_time_minutes

		self.assertEqual(under_time(with_shift, MONDAY, 7), 60)
		self.assertEqual(under_time(with_shift, TUESDAY, 7.95), 0)  # 3 minutes short: within tolerance
		self.assertEqual(under_time(with_shift, THURSDAY, 4, "Half Day"), 0)
		self.assertEqual(under_time(with_shift, FRIDAY, 3), 0)  # holiday work is never short
		self.assertEqual(under_time(without_shift, MONDAY, 7), 0)  # no shift: no required hours

	# ------------------------------------------------------------ fixed shifts

	def test_fixed_shift_ot_and_holiday_punches_are_not_skipped(self):
		fixed = self.timetable(
			"Fixed OT", "07:30:00", "15:00:00", custom_ot_min_hours=0.5, allow_check_out_after_shift_end_time=180
		)
		employee = self.employee(holiday_list=self.holidays)
		for day in (MONDAY, FRIDAY):
			self.assign_shift(employee, fixed.name, day)
			self.punch(employee, at(day, "07:30"))
			self.punch(employee, at(day, "17:00"))
		self.process(fixed.name, at(FRIDAY, "23:00", days_later=1))

		monday, friday = (
			frappe.db.get_value(
				"Attendance", {"employee": employee, "attendance_date": day, "docstatus": 1},
				["custom_worked_hours", "custom_ot1_hours", "custom_ot2_hours", "custom_is_holiday_work"], as_dict=True,
			)
			for day in (MONDAY, FRIDAY)
		)
		self.assertEqual((monday.custom_worked_hours, monday.custom_ot1_hours, monday.custom_ot2_hours), (9.5, 2, 0))
		self.assertEqual((friday.custom_is_holiday_work, friday.custom_ot1_hours, friday.custom_ot2_hours), (1, 0, 9.5))

	# ------------------------------------------------------------ validation

	def test_shift_type_validation(self):
		# Frappe fills every empty Time field of a new document with the current time, so the
		# missing Day Start can only happen on a saved shift
		self.flex.custom_day_start_time = None
		self.assertRaises(frappe.ValidationError, self.flex.save)
		self.flex.reload()
		self.assertRaises(
			frappe.ValidationError, self.timetable, "Bad", "05:00:00", "04:59:00",
			custom_is_flexible_shift=1, custom_day_start_time="05:00:00",
		)
		self.assertRaises(
			frappe.ValidationError, self.timetable, "Bad", "07:00:00", "15:00:00", custom_ot_min_hours=2, custom_ot_max_hours=1
		)
		self.assertRaises(frappe.ValidationError, self.timetable, "Bad", "07:00:00", "15:00:00", custom_ot_min_hours=-1)
		self.assertRaises(
			frappe.ValidationError, self.flexible, "Bad", "05:00:00", "23:00:00", 8,
			custom_is_flexible_shift=1, custom_day_start_time="05:00:00", custom_required_working_hours=8,
		)
