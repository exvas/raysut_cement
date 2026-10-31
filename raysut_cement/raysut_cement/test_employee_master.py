# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from raysut_cement.raysut_cement.employee_master import import_employee_master, set_employee_status
from raysut_cement.raysut_cement.tams_import import import_employees


class TestEmployeeMaster(FrappeTestCase):
	def setUp(self):
		patcher = patch.object(frappe.db, "commit")
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.db.rollback)
		self.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		self.tag = frappe.generate_hash(length=5).upper()

	def test_master_updates_tams_employee_and_creates_new_ones(self):
		code = f"M{self.tag}"
		import_employees([[code, "Robil", code, "Staff", "2020-01-05", "1113", "Active"]], self.company)
		group, section = f"Tech {self.tag}", f"Stores {self.tag}"
		rows = [
			[code, "Robal  Mofij Meah", "Fitter", group, section, "Flexible (8 hrs/day)", "83212083"],
			[f"N{self.tag}", "New Joiner", "Helper", "Contractor", f"Agency {self.tag}", "07:30 - 15:00 (Fixed)", None],
			[None, f"No Number {self.tag}", "Helper", "Contractor", f"Agency {self.tag}", "07:30 - 15:00 (Fixed)", None],
		]

		result = import_employee_master(rows, self.company)
		self.assertEqual((result["updated"], result["created"], result["errors"]), (1, 2, []))
		self.assertEqual(result["renamed"], [[code, "Robil", "Robal Mofij Meah"]])

		employee = frappe.get_doc("Employee", {"employee_number": code})
		self.assertEqual(
			(employee.employee_name, employee.designation, employee.default_shift, employee.custom_id_card_no, employee.attendance_device_id),
			("Robal Mofij Meah", frappe.db.exists("Designation", "Fitter"), "Flexible 8 Hours", "83212083", code),
		)
		department = frappe.get_doc("Department", employee.department)
		self.assertEqual(department.department_name, section)
		self.assertEqual(frappe.db.get_value("Department", department.parent_department, ["department_name", "is_group"]), (group, 1))
		self.assertTrue(frappe.db.get_value("Shift Type", "Flexible 8 Hours", "custom_is_flexible_shift"))

		joiner = frappe.get_doc("Employee", {"employee_number": f"N{self.tag}"})
		self.assertEqual((joiner.attendance_device_id, joiner.default_shift), (f"N{self.tag}", "Fixed 07:30-15:00"))

		again = import_employee_master(rows, self.company)
		self.assertEqual((again["updated"], again["created"], again["renamed"]), (3, 0, []))

	def test_set_status_without_date_of_birth(self):
		code = f"S{self.tag}"
		import_employees([[code, "Status Test", code, "Staff", "2020-01-05", "", "Active"]], self.company)
		name = frappe.db.get_value("Employee", {"employee_number": code})
		self.assertEqual(set_employee_status([name], "Inactive"), {"updated": 1, "errors": []})
		self.assertEqual(frappe.db.get_value("Employee", name, "status"), "Inactive")
		self.assertEqual(set_employee_status([name], "Inactive")["updated"], 0)
		self.assertRaises(frappe.ValidationError, set_employee_status, [name], "Gone")
