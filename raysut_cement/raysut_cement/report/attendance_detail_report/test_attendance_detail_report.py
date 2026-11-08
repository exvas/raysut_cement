# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from raysut_cement.raysut_cement.report.attendance_detail_report.attendance_detail_report import (
	exceptions,
	hm,
	leave_code,
)


class TestAttendanceDetailReport(FrappeTestCase):
	def test_hours_minutes_like_tams(self):
		self.assertEqual(hm(487), "8.07")
		self.assertEqual(hm(5932), "98.52")  # the TAMS sample's Reg total
		self.assertEqual(hm(0), "-")
		self.assertEqual(hm(0, blank="0.00"), "0.00")

	def test_in_out_exceptions_against_the_shift(self):
		shift = frappe._dict(start_time="07:30:00", end_time="15:00:00")
		day = datetime.date(2026, 10, 12)
		a = frappe._dict(in_time=datetime.datetime(2026, 10, 12, 7, 10), out_time=datetime.datetime(2026, 10, 12, 12, 1))
		self.assertEqual(exceptions(a, day, shift), ("E 0.20", "E 2.59"))
		a = frappe._dict(in_time=datetime.datetime(2026, 10, 12, 7, 30), out_time=datetime.datetime(2026, 10, 12, 15, 39))
		self.assertEqual(exceptions(a, day, shift), ("", "L 0.39"))

	def test_night_shift_ends_next_day(self):
		shift = frappe._dict(start_time="23:00:00", end_time="07:00:00")
		a = frappe._dict(in_time=datetime.datetime(2026, 10, 12, 23, 5), out_time=datetime.datetime(2026, 10, 13, 6, 50))
		self.assertEqual(exceptions(a, datetime.date(2026, 10, 12), shift), ("L 0.05", "E 0.10"))

	def test_leave_codes(self):
		self.assertEqual(leave_code("Special Leave"), "SPL")
		self.assertEqual(leave_code("Sick Leave - Paid 50%"), "SL50")
		self.assertEqual(leave_code("Some New Leave"), "SNL")
