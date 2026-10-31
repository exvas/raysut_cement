# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

from datetime import date, timedelta

import frappe

from raysut_cement.raysut_cement.report.consolidated_attendance.consolidated_attendance import execute
from raysut_cement.raysut_cement.scheduling.test_scheduling import SchedulingTestCase

SEPTEMBER = [date(2026, 9, 1) + timedelta(days=i) for i in range(30)]
FRIDAYS = [d for d in SEPTEMBER if d.weekday() == 4]
PUBLIC_HOLIDAY = date(2026, 9, 23)


class TestConsolidatedAttendance(SchedulingTestCase):
	def setUp(self):
		super().setUp()
		self.holidays = self.make_holidays()
		self.shift = self.timetable("Report", "07:00:00", "15:00:00", custom_required_working_hours=8)
		if not frappe.db.exists("Leave Type", "Sick Leave"):
			frappe.get_doc({"doctype": "Leave Type", "leave_type_name": "Sick Leave"}).insert()
		frappe.db.set_value("Leave Type", "Sick Leave", "report_abbreviation", "SL")

	def make_holidays(self):
		name = f"RC Report Holidays {frappe.generate_hash(length=4)}"
		frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": name,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [{"holiday_date": d, "description": "Friday", "weekly_off": 1} for d in FRIDAYS]
				+ [{"holiday_date": PUBLIC_HOLIDAY, "description": "Public holiday", "weekly_off": 0}],
			}
		).insert()
		return name

	def staff(self, **kwargs):
		kwargs.setdefault("holiday_list", self.holidays)
		return self.employee(**kwargs)

	def mark(self, employee, day, status="Present", hours=8, **kwargs):
		doc = frappe.get_doc(
			{"doctype": "Attendance", "employee": employee, "attendance_date": day, "status": status,
			 "working_hours": hours, "company": self.company, "shift": self.shift.name, **kwargs}
		)
		doc.insert()
		doc.submit()
		return doc

	def working_days(self, start=SEPTEMBER[0]):
		return [d for d in SEPTEMBER if d >= start and d not in FRIDAYS and d != PUBLIC_HOLIDAY]

	def report(self, employee, **filters):
		filters = {"company": self.company, "from_date": "2026-09-01", "to_date": "2026-09-30", "employee": employee, **filters}
		columns, data = execute(filters)
		return {c["fieldname"]: c for c in columns}, data[0], data[-1]

	def test_present_every_working_day_balances(self):
		employee = self.staff()
		for day in self.working_days():
			self.mark(employee, day)
		_columns, row, total = self.report(employee)
		self.assertEqual((row.pr, row.ab, row.wo, row.hl, row.nm), (25, 0, 4, 1, 0))
		self.assertEqual((row.pr + row.wo + row.hl, row.total_days, row.balanced), (30, 30, 1))
		self.assertEqual((row.worked, row.worked_hours), ("200:00", 200))
		self.assertEqual((total.employee_name, total.pr), ("Grand Total", 25))

	def test_joined_mid_month_is_not_employed_before_joining(self):
		employee = self.staff(date_of_joining="2026-09-15")
		for day in self.working_days(start=date(2026, 9, 15)):
			self.mark(employee, day)
		_columns, row, _total = self.report(employee)
		self.assertEqual((row.days_not_employed, row.ab, row.nm, row.balanced), (14, 0, 0, 1))
		self.assertEqual(row.total_days, 16)

	def test_half_day_with_sick_leave_and_unmarked_days(self):
		employee = self.staff()
		self.mark(employee, SEPTEMBER[0], "Half Day", 4, leave_type="Sick Leave")
		self.mark(employee, SEPTEMBER[1], "Absent", 0)
		columns, row, _total = self.report(employee)
		self.assertEqual((row.pr, row.leave_sl, row.ab), (0.5, 0.5, 1))
		self.assertEqual(columns["leave_sl"]["label"], "SL")
		self.assertEqual(row.nm, 30 - 2 - 5)  # every other non-holiday day is Not Marked
		self.assertEqual(row.balanced, 1)

	def test_ot1_ot2_and_under_time_in_hh_mm(self):
		employee = self.staff()
		self.mark(employee, date(2026, 9, 7), hours=10)  # Monday: 2 h over the required 8
		self.mark(employee, FRIDAYS[1], hours=6)  # weekly off: all OT2
		for day in (date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)):
			frappe.db.set_value("Attendance", self.mark(employee, day, hours=7.5).name, "under_time_minutes", 30)
		_columns, row, _total = self.report(employee)
		self.assertEqual((row.ot1, row.ot2, row.under_time), ("02:00", "06:00", "01:30"))
		self.assertEqual((row.ot1_hours, row.ot2_hours, row.under_time_hours), (2, 6, 1.5))
		self.assertEqual((row.pr, row.wo), (5, 3))  # the worked Friday is a PR day, not a WO

	def test_empty_department_shows_not_set_and_groups(self):
		employee = self.staff()
		frappe.db.set_value("Employee", employee, "department", None)
		self.mark(employee, SEPTEMBER[0])
		_columns, row, _total = self.report(employee)
		self.assertEqual(row.department, "Not Set")
		_columns, data = execute(
			{"company": self.company, "from_date": "2026-09-01", "to_date": "2026-09-30", "employee": employee, "group_by": "Department"}
		)
		self.assertEqual([r.employee_name for r in data[1:]], ["Subtotal: Not Set", "Grand Total"])

	def test_period_across_two_months(self):
		employee = self.staff()
		self.mark(employee, date(2026, 9, 30))
		columns, data = execute(
			{"company": self.company, "from_date": "2026-09-15", "to_date": "2026-10-14", "employee": employee}
		)
		row = data[0]
		self.assertEqual((row.pr, row.total_days + row.days_not_employed, row.balanced), (1, 30, 1))

	def test_branch_restricted_user_sees_only_their_branch(self):
		branches = []
		for name in (f"RC North {frappe.generate_hash(length=4)}", f"RC South {frappe.generate_hash(length=4)}"):
			branches.append(frappe.get_doc({"doctype": "Branch", "branch": name}).insert().name)
		north, south = self.staff(branch=branches[0]), self.staff(branch=branches[1])
		for employee in (north, south):
			self.mark(employee, SEPTEMBER[0])

		user = frappe.get_doc(
			{"doctype": "User", "email": f"rc.branch.{frappe.generate_hash(length=5)}@example.com", "first_name": "Branch",
			 "roles": [{"role": "HR User"}]}
		).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "User Permission", "user": user.name, "allow": "Branch", "for_value": branches[0]}).insert(
			ignore_permissions=True
		)
		frappe.set_user(user.name)
		self.addCleanup(frappe.set_user, "Administrator")
		_columns, data = execute({"company": self.company, "from_date": "2026-09-01", "to_date": "2026-09-30"})
		self.assertEqual([r.employee for r in data if not r.get("is_total")], [north])
