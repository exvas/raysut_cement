# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from datetime import date, datetime

import frappe

from raysut_cement.api import successfactors as api
from raysut_cement.raysut_cement.scheduling.test_scheduling import SchedulingTestCase

DAY = date(2026, 9, 7)


class TestSuccessFactorsAPI(SchedulingTestCase):
	def setUp(self):
		super().setUp()
		self.emp = self.employee()
		frappe.db.set_value("Employee", self.emp, {"employee_number": "SF653", "sf_user_id": None})
		shift = self.timetable("SF", "07:00:00", "15:00:00", custom_required_working_hours=8)
		attendance = frappe.get_doc(
			{"doctype": "Attendance", "employee": self.emp, "attendance_date": DAY, "status": "Present", "shift": shift.name,
			 "working_hours": 10, "in_time": datetime(2026, 9, 7, 7, 8), "out_time": datetime(2026, 9, 7, 17, 8),
			 "company": self.company}
		).insert()
		attendance.submit()
		self.punch(self.emp, datetime(2026, 9, 7, 7, 8))
		self.offset = datetime(2026, 9, 7).astimezone(api.ZoneInfo(api.get_system_timezone())).strftime("%z")
		self.offset = f"{self.offset[:3]}:{self.offset[3:]}"

	def as_integration_user(self):
		user = frappe.get_doc(
			{"doctype": "User", "email": f"sf.api.{frappe.generate_hash(length=5)}@example.com", "first_name": "SF API",
			 "roles": [{"role": api.ROLE}]}
		).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		self.addCleanup(frappe.set_user, "Administrator")

	def test_attendance_record_for_sap(self):
		self.as_integration_user()
		result = api.attendance("2026-09-07", "2026-09-07", employee="SF653")
		self.assertEqual((result["total"], result["has_more"]), (1, False))
		row = result["data"][0]
		self.assertEqual((row["employee_id"], row["employee_number"], row["sf_user_id"]), (self.emp, "SF653", "SF653"))
		self.assertEqual((row["date"], row["status"], row["worked_hours"], row["ot1_hours"], row["ot2_hours"]), ("2026-09-07", "Present", 10, 2, 0))
		self.assertEqual((row["check_in"], row["check_out"]), (f"2026-09-07T07:08:00{self.offset}", f"2026-09-07T17:08:00{self.offset}"))

	def test_sf_user_id_wins_and_finds_the_employee(self):
		frappe.db.set_value("Employee", self.emp, "sf_user_id", "rc.ahmed")
		row = api.attendance("2026-09-07", "2026-09-07", employee="rc.ahmed")["data"][0]
		self.assertEqual(row["sf_user_id"], "rc.ahmed")
		self.assertEqual(api.employees(status="All", page_size=1000)["data"][0].keys() >= {"sf_user_id", "employee_number"}, True)

	def test_punches_and_paging(self):
		self.punch(self.emp, datetime(2026, 9, 7, 17, 8))
		first = api.punches("2026-09-07", "2026-09-07", employee=self.emp, page_size=1)
		second = api.punches("2026-09-07", "2026-09-07", employee=self.emp, page=2, page_size=1)
		self.assertEqual((first["total"], first["has_more"], second["has_more"]), (2, True, False))
		self.assertEqual([first["data"][0]["time"], second["data"][0]["time"]], [f"2026-09-07T07:08:00{self.offset}", f"2026-09-07T17:08:00{self.offset}"])

	def test_modified_since_and_limits(self):
		later = api.attendance("2026-09-07", "2026-09-07", employee=self.emp, modified_since="2099-01-01T00:00:00Z")
		self.assertEqual(later["total"], 0)
		self.assertRaises(frappe.ValidationError, api.attendance, "2026-09-07", "2026-09-06")
		self.assertRaises(frappe.ValidationError, api.attendance, "2026-01-01", "2026-03-31")  # more than 62 days
		self.assertRaises(frappe.DoesNotExistError, api.attendance, "2026-09-07", "2026-09-07", employee="nobody")

	def test_only_the_integration_role_gets_in(self):
		user = frappe.get_doc(
			{"doctype": "User", "email": f"hr.{frappe.generate_hash(length=5)}@example.com", "first_name": "HR",
			 "roles": [{"role": "HR User"}]}
		).insert(ignore_permissions=True)
		frappe.set_user(user.name)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertRaises(frappe.PermissionError, api.attendance, "2026-09-07", "2026-09-07")
