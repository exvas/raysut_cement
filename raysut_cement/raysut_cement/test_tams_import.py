# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from raysut_cement.raysut_cement.tams_import import import_checkins, import_employees, import_timesheet, rebuild_imported_hours


class TestTamsImport(FrappeTestCase):
	def setUp(self):
		patcher = patch.object(frappe.db, "commit")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.db.rollback)
		self.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		tag = frappe.generate_hash(length=5).upper()
		self.code, self.card = f"T{tag}", f"9{tag}"
		import_employees([[self.code, "Said Omar Salim Fadhil", self.card, "Staff", "2020-01-05", "1113", "Active"]], self.company)
		self.employee = frappe.db.get_value("Employee", {"employee_number": self.code})

	def test_employee_fields_and_rerun(self):
		employee = frappe.get_doc("Employee", self.employee)
		self.assertEqual(
			(employee.first_name, employee.middle_name, employee.last_name, employee.attendance_device_id),
			("Said", "Omar Salim", "Fadhil", self.card),
		)
		self.assertEqual((str(employee.date_of_joining), employee.date_of_birth, employee.gender), ("2020-01-05", None, None))
		rows = [[self.code, "Said Omar Salim Fadhil", self.card, "Staff", "2020-01-05", "1113", "Active"]]
		self.assertEqual(import_employees(rows, self.company)["created"], 0)

	def test_checkins_map_mode_and_skip_duplicates(self):
		rows = [
			[self.card, "2026-03-01 07:01:32", "0701", "i CLOCK MAIN GATE"],
			[self.card, "2026-03-01 19:03:44", "0703", "i CLOCK MAIN GATE"],
			[self.card, "2026-03-01 19:03:44", "0703", "Workshop"],
			[self.card, "2026-03-01 20:00:00", "400 ", ""],
			["no-such-card", "2026-03-01 07:00:00", "0701", "RECEPTION"],
		]
		self.assertEqual(import_checkins(rows)["created"], 3)
		checkins = frappe.get_all(
			"Employee Checkin", {"employee": self.employee}, ["log_type", "device_id", "skip_auto_attendance"], order_by="time"
		)
		self.assertEqual([c.log_type for c in checkins], ["IN", "OUT", None])
		self.assertTrue(all(c.skip_auto_attendance for c in checkins))
		self.assertEqual(import_checkins(rows)["created"], 0)

	def test_timesheet_days_become_attendance(self):
		rows = [
			[self.code, "2026-03-01", "PR", "2026-03-01 07:01:00", "", "5.30", "0"],
			[self.code, "2026-03-01", "AB", "", "2026-03-01 19:03:00", "6.30", "0"],
			[self.code, "2026-03-02", "AL", "", "", "0", "0"],
			[self.code, "2026-03-03", "OF", "", "", "0", "0"],
			[self.code, "2026-03-04", "AB", "", "", "0", "0"],
		]
		self.assertEqual(import_timesheet(rows, self.company)["created"], 3)
		attendance = frappe.get_all(
			"Attendance",
			{"employee": self.employee, "docstatus": 1},
			["attendance_date", "status", "leave_type", "working_hours", "in_time", "out_time"],
			order_by="attendance_date",
		)
		present, leave, absent = attendance
		self.assertEqual((present.status, present.working_hours), ("Present", 12.0))
		self.assertEqual((str(present.in_time), str(present.out_time)), ("2026-03-01 07:01:00", "2026-03-01 19:03:00"))
		self.assertEqual((leave.status, leave.leave_type), ("On Leave", "Annual Leave"))
		self.assertEqual((str(absent.attendance_date), absent.status), ("2026-03-04", "Absent"))
		self.assertEqual(import_timesheet(rows, self.company)["created"], 0)

	def test_hours_are_tams_h_mm_and_nights_pair_with_next_morning(self):
		rows = [
			[self.code, "2026-03-01", "PR", "2026-03-01 07:08:00", "2026-03-01 15:03:00", "7.55", "0"],  # 7 h 55 min
			# TAMS night: each date holds the evening IN and the previous night's morning OUT
			[self.code, "2026-03-02", "PR", "", "2026-03-02 06:57:00", "0", "0"],
			[self.code, "2026-03-02", "PR", "2026-03-02 18:56:00", "", "0", "0"],
			[self.code, "2026-03-03", "PR", "", "2026-03-03 06:59:00", "0", "0"],
			[self.code, "2026-03-03", "PR", "2026-03-03 18:55:00", "", "0", "0"],
			[self.code, "2026-03-05", "PR", "2026-03-05 08:00:00", "", "0", "0"],  # forgot to punch out...
			[self.code, "2026-03-06", "PR", "2026-03-06 07:00:00", "2026-03-06 15:00:00", "8.00", "0"],  # ...not this day's OUT
			[self.code, "2026-03-08", "PR", "2026-03-08 18:57:00", "", "0", "0"],  # night with only the IN on its date
			[self.code, "2026-03-09", "PR", "2026-03-09 18:56:00", "2026-03-09 06:57:00", "0", "0"],
		]
		import_timesheet(rows, self.company)
		self.assertEqual(frappe.db.get_value("Attendance", {"employee": self.employee, "attendance_date": "2026-03-01"}, "working_hours"), 7.92)

		self.assertEqual(rebuild_imported_hours("2026-03-01", "2026-03-09", self.employee), 5)  # 1 and 6 March were already right
		days = {
			str(a.attendance_date): (a.working_hours, a.out_time and str(a.out_time), a.custom_missing_punch)
			for a in frappe.get_all(
				"Attendance", {"employee": self.employee}, ["attendance_date", "working_hours", "out_time", "custom_missing_punch"]
			)
		}
		self.assertEqual(days["2026-03-01"], (7.92, "2026-03-01 15:03:00", 0))
		self.assertEqual(days["2026-03-02"], (12.05, "2026-03-03 06:59:00", 0))  # 18:56 to next morning 06:59
		self.assertEqual(days["2026-03-03"], (0, None, 1))  # the next morning is not in TAMS
		self.assertEqual(days["2026-03-05"], (0, None, 1))
		self.assertEqual(days["2026-03-06"], (8, "2026-03-06 15:00:00", 0))
		self.assertEqual(days["2026-03-08"], (12.0, "2026-03-09 06:57:00", 0))
		self.assertEqual(rebuild_imported_hours("2026-03-01", "2026-03-09", self.employee), 0)
