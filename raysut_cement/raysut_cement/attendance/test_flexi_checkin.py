# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Flexible check-in ("flexi grace") and OT Policy: the spec's test table, through core auto attendance."""

from datetime import date, datetime

import frappe

from raysut_cement.raysut_cement.attendance.overtime import calculate_policy_overtime
from raysut_cement.raysut_cement.scheduling.test_scheduling import SchedulingTestCase

DAY = date(2026, 9, 7)  # a Monday


def at(hh_mm):
	return datetime.combine(DAY, datetime.strptime(hh_mm, "%H:%M").time())


class TestFlexiCheckin(SchedulingTestCase):
	def setUp(self):
		super().setUp()
		self.policy = frappe.get_doc(
			{"doctype": "OT Policy", "policy_name": f"RC OT {frappe.generate_hash(length=4)}", "min_ot_minutes": 30}
		).insert()

	def general_shift(self, **kwargs):
		settings = {
			"enable_flexible_checkin": 1,
			"flexi_checkin_until": "10:00:00",
			"flexi_required_hours": 8,
			"flexi_count_from": "Actual Check-in",
			"flexi_after_grace_action": "Mark Late",
			"flexi_undertime_tolerance": 5,
			"allow_check_out_after_shift_end_time": 240,
			"ot_policy": self.policy.name,
		}
		settings.update(kwargs)
		return self.timetable("General", "07:00:00", "15:00:00", **settings)

	def day(self, shift, *punches):
		employee = self.employee()
		self.assign_shift(employee, shift.name, DAY)
		for hh_mm in punches:
			self.punch(employee, at(hh_mm))
		self.process(shift.name, datetime(2026, 9, 9))
		return frappe.db.get_value(
			"Attendance",
			{"employee": employee, "attendance_date": DAY, "docstatus": 1},
			["status", "working_hours", "late_entry", "late_minutes", "under_time_minutes", "custom_ot1_hours",
			 "custom_ot2_hours", "expected_checkout_time", "required_work_hours", "flexi_shift_applied",
			 "custom_missing_punch", "out_time"],
			as_dict=True,
		)

	def assertDay(self, attendance, status, late, under_time, ot1, expected_checkout=None):
		self.assertEqual(
			(attendance.status, attendance.late_entry, attendance.late_minutes, attendance.under_time_minutes, attendance.custom_ot1_hours),
			(status, int(late > 0), late, under_time, ot1),
		)
		self.assertEqual(attendance.flexi_shift_applied, 1)
		if expected_checkout:
			self.assertEqual(attendance.expected_checkout_time, at(expected_checkout))

	# ------------------------------------------------------------ the spec's table

	def test_01_to_03_any_check_in_up_to_grace_works_eight_hours(self):
		shift = self.general_shift()
		for check_in, check_out in (("07:00", "15:00"), ("09:00", "17:00"), ("10:00", "18:00")):
			with self.subTest(check_in=check_in):
				attendance = self.day(shift, check_in, check_out)
				self.assertDay(attendance, "Present", 0, 0, 0, expected_checkout=check_out)
				self.assertEqual((attendance.working_hours, attendance.required_work_hours), (8, 8))

	def test_04_short_day_is_under_time(self):
		self.assertDay(self.day(self.general_shift(), "08:00", "15:30"), "Present", 0, 30, 0, expected_checkout="16:00")

	def test_04b_shortfall_within_tolerance_is_ignored(self):
		self.assertDay(self.day(self.general_shift(), "08:00", "15:56"), "Present", 0, 0, 0)

	def test_05_extra_hours_are_ot1_per_policy(self):
		self.assertDay(self.day(self.general_shift(), "07:30", "17:30"), "Present", 0, 0, 2)

	def test_06_check_in_after_grace_applies_the_action(self):
		self.assertDay(self.day(self.general_shift(), "10:20", "18:20"), "Present", 20, 0, 0, expected_checkout="18:20")
		half_day = self.general_shift(flexi_after_grace_action="Mark Half Day")
		self.assertDay(self.day(half_day, "10:20", "18:20"), "Half Day", 20, 0, 0)
		absent = self.general_shift(flexi_after_grace_action="Mark Absent")
		self.assertEqual(self.day(absent, "10:20", "18:20").status, "Absent")

	def test_07_early_check_in_counts_from_the_chosen_start(self):
		actual = self.day(self.general_shift(), "06:40", "15:00")
		self.assertEqual((actual.working_hours, actual.custom_ot1_hours), (8.33, 0))  # 20 min extra < 30 min policy minimum
		self.assertEqual(actual.expected_checkout_time, at("14:40"))

		from_start = self.day(self.general_shift(flexi_count_from="Shift Start Time"), "06:40", "15:00")
		self.assertEqual((from_start.working_hours, from_start.under_time_minutes), (8, 0))
		self.assertEqual(from_start.expected_checkout_time, at("15:00"))

	def test_08_missing_check_out_is_flagged_without_under_time_or_ot(self):
		attendance = self.day(self.general_shift(), "08:00")
		self.assertEqual(
			(attendance.custom_missing_punch, attendance.working_hours, attendance.under_time_minutes, attendance.custom_ot1_hours, attendance.out_time),
			(1, 0, 0, 0, None),
		)

	def test_09_shift_without_flexible_check_in_is_standard(self):
		shift = self.timetable("Standard", "07:00:00", "15:00:00", enable_late_entry_marking=1, late_entry_grace_period=15)
		attendance = self.day(shift, "08:00", "15:00")
		self.assertEqual((attendance.status, attendance.late_entry, attendance.working_hours), ("Present", 1, 7))
		# status and late marking are core's; under time (7 of 8 hours) is reported for every shift
		self.assertEqual((attendance.flexi_shift_applied, attendance.under_time_minutes, attendance.late_minutes), (0, 60, 60))

	def test_weekly_off_work_is_ot2_without_under_time(self):
		friday = date(2026, 9, 11)
		holidays = frappe.get_doc(
			{"doctype": "Holiday List", "holiday_list_name": f"RC Flexi Holidays {frappe.generate_hash(length=4)}",
			 "from_date": "2026-01-01", "to_date": "2026-12-31",
			 "holidays": [{"holiday_date": friday, "description": "Friday", "weekly_off": 1}]}
		).insert()
		shift = self.general_shift()
		employee = self.employee(holiday_list=holidays.name)
		self.assign_shift(employee, shift.name, friday)
		for hh_mm in ("07:00", "13:00"):
			self.punch(employee, datetime.combine(friday, datetime.strptime(hh_mm, "%H:%M").time()))
		self.process(shift.name, datetime(2026, 9, 13))
		attendance = frappe.db.get_value(
			"Attendance", {"employee": employee, "attendance_date": friday, "docstatus": 1},
			["custom_is_holiday_work", "custom_ot2_hours", "custom_ot1_hours", "under_time_minutes"], as_dict=True,
		)
		self.assertEqual(
			(attendance.custom_is_holiday_work, attendance.custom_ot2_hours, attendance.custom_ot1_hours, attendance.under_time_minutes),
			(1, 6, 0, 0),
		)

	# ------------------------------------------------------------ settings

	def test_flexible_check_in_validation(self):
		for bad in (
			{"flexi_checkin_until": "06:00:00"},  # before the start
			{"flexi_checkin_until": "16:00:00"},  # after the end
			{"flexi_required_hours": 0},
			{"allow_check_out_after_shift_end_time": 60},  # a 10:00 check-in could not finish 8 hours
			{"custom_is_flexible_shift": 1, "custom_day_start_time": "05:00:00", "custom_required_working_hours": 8},
		):
			with self.subTest(bad=bad):
				self.assertRaises(frappe.ValidationError, self.general_shift, **bad)

	def test_ot_policy_rules(self):
		policy = frappe._dict(min_ot_minutes=30, rounding_minutes="15", rounding_method="Down", ot2_on_holidays=1)
		self.assertEqual(calculate_policy_overtime(8.4, 8, policy), (0.0, 0.0))  # 24 min < 30 min minimum
		self.assertEqual(calculate_policy_overtime(9.7, 8, policy), (1.5, 0.0))  # 1h42 rounded down to 1h30
		self.assertEqual(calculate_policy_overtime(9.7, 8, frappe._dict(policy, rounding_method="Up")), (1.75, 0.0))
		self.assertEqual(calculate_policy_overtime(9.625, 8, frappe._dict(policy, rounding_method="Nearest")), (1.75, 0.0))
		self.assertEqual(calculate_policy_overtime(13, 8, frappe._dict(policy, move_to_ot2_after_hours=3)), (3.0, 2.0))
		self.assertEqual(calculate_policy_overtime(13, 8, frappe._dict(policy, max_ot1_hours=4)), (4.0, 0.0))
		self.assertEqual(calculate_policy_overtime(6, 8, policy, holiday=True), (0.0, 6.0))
		self.assertEqual(calculate_policy_overtime(11, 8, frappe._dict(policy, max_ot2_hours=10), holiday=True), (0.0, 10.0))
		self.assertEqual(calculate_policy_overtime(10, 8, frappe._dict(policy, ot2_on_holidays=0), holiday=True), (2.0, 0.0))
		self.assertRaises(
			frappe.ValidationError,
			frappe.get_doc({"doctype": "OT Policy", "policy_name": "RC bad", "max_ot1_hours": 5, "move_to_ot2_after_hours": 3}).insert,
		)
