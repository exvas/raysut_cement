# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Employee x date roster of Shift Assignments, coloured by timetable."""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, getdate
from frappe.utils.nestedset import get_descendants_of
from erpnext.setup.doctype.employee.employee import get_holiday_list_for_employee
from hrms.utils.holiday_list import get_holiday_dates_between

MAX_DAYS = 62


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	if from_date > to_date:
		frappe.throw(_("From Date must be before To Date"))
	if date_diff(to_date, from_date) >= MAX_DAYS:
		frappe.throw(_("Please choose a range of at most {0} days").format(MAX_DAYS))

	dates = [add_days(from_date, i) for i in range(date_diff(to_date, from_date) + 1)]
	employees = get_employees(filters, from_date, to_date)
	assignments = get_assignments([e.name for e in employees], from_date, to_date)
	colors = dict(frappe.get_all("Shift Type", fields=["name", "shift_color"], as_list=True))

	data = []
	for emp in employees:
		holidays = holiday_dates(emp.name, from_date, to_date)
		row = {"employee": emp.name, "employee_name": emp.employee_name, "department": emp.department, "_colors": {}, "_holidays": []}
		for date in dates:
			key = column_key(date)
			shifts = [a.shift_type for a in assignments[emp.name] if covers(a, date)]
			row[key] = ", ".join(shifts)
			if shifts:
				row["_colors"][key] = colors.get(shifts[0]) or "#5e64ff"
			if getdate(date) in holidays:
				row["_holidays"].append(key)
		data.append(row)

	return get_columns(dates), data


def column_key(date):
	return "d_" + getdate(date).strftime("%Y%m%d")


def covers(assignment, date):
	return getdate(assignment.start_date) <= getdate(date) and (not assignment.end_date or getdate(date) <= getdate(assignment.end_date))


def get_columns(dates):
	columns = [
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 160},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 120},
	]
	for date in dates:
		d = getdate(date)
		columns.append({"label": d.strftime("%a %d %b"), "fieldname": column_key(d), "fieldtype": "Data", "width": 110})
	return columns


def get_employees(filters, from_date, to_date):
	conditions = {"company": filters.company, "status": ("in", ["Active", "Left"])}
	if filters.employee:
		conditions["name"] = filters.employee
	if filters.department:
		conditions["department"] = ("in", [filters.department, *get_descendants_of("Department", filters.department)])
	if filters.shift_pattern:
		schedules = frappe.get_all("Shift Pattern Assignment", filters={"shift_pattern": filters.shift_pattern, "docstatus": 1}, pluck="name")
		scheduled = frappe.get_all(
			"Shift Assignment",
			filters={"shift_pattern_assignment": ("in", schedules or [""]), "docstatus": 1, "start_date": ("<=", to_date)},
			pluck="employee",
			distinct=True,
		)
		conditions["name"] = ("in", scheduled or [""]) if not filters.employee else filters.employee

	employees = frappe.get_all(
		"Employee", filters=conditions, fields=["name", "employee_name", "department", "relieving_date"], order_by="employee_name"
	)
	return [e for e in employees if not e.relieving_date or getdate(e.relieving_date) >= from_date]


def get_assignments(employees, from_date, to_date):
	by_employee = defaultdict(list)
	if not employees:
		return by_employee
	sa = frappe.qb.DocType("Shift Assignment")
	rows = (
		frappe.qb.from_(sa)
		.select(sa.employee, sa.shift_type, sa.start_date, sa.end_date)
		.where(
			sa.employee.isin(employees)
			& (sa.docstatus == 1)
			& (sa.status == "Active")
			& (sa.start_date <= to_date)
			& ((sa.end_date >= from_date) | sa.end_date.isnull())
		)
		.orderby(sa.start_date)
	).run(as_dict=True)
	for row in rows:
		by_employee[row.employee].append(row)
	return by_employee


def holiday_dates(employee, from_date, to_date):
	holiday_list = get_holiday_list_for_employee(employee, raise_exception=False)
	if not holiday_list:
		return set()
	return {getdate(d) for d in get_holiday_dates_between(holiday_list, from_date, to_date)}
