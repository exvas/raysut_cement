# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Pioneer Cement and Sohar Cement as companies of their own, set up like Raysut Cement.

Each gets Raysut's country, currency, chart of accounts template and holiday list, and a copy of its
department list; their own shifts, employees and settings follow once the group sends them.
"""

import frappe

COMPANIES = {"Pioneer Cement": "PC", "Sohar Cement": "SC"}


def execute():
	source = frappe.get_all("Company", filters={"company_name": ("like", "Raysut Cement%")}, pluck="name", limit=1)
	if source:
		create_companies(source[0])


def create_companies(source):
	src = frappe.get_doc("Company", source)
	for name, abbr in COMPANIES.items():
		if frappe.db.exists("Company", {"company_name": name}) or frappe.db.exists("Company", {"abbr": abbr}):
			continue
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": name,
				"abbr": abbr,
				"country": src.country,
				"default_currency": src.default_currency,
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": src.chart_of_accounts
				if src.create_chart_of_accounts_based_on == "Standard Template"
				else None,
				"default_holiday_list": src.default_holiday_list,
			}
		).insert(ignore_permissions=True)
		copy_departments(src.name, company.name)


def copy_departments(source, target):
	"""The source company's departments under the same names, parents first."""
	for d in frappe.get_all(
		"Department",
		filters={"company": source},
		fields=["department_name", "parent_department", "is_group"],
		order_by="lft",
	):
		if frappe.db.exists("Department", {"department_name": d.department_name, "company": target}):
			continue
		parent = d.parent_department
		if parent and frappe.db.get_value("Department", parent, "company") == source:
			parent = frappe.db.get_value(
				"Department",
				{"department_name": frappe.db.get_value("Department", parent, "department_name"), "company": target},
			)
		frappe.get_doc(
			{
				"doctype": "Department",
				"department_name": d.department_name,
				"company": target,
				"parent_department": parent or "All Departments",
				"is_group": d.is_group,
			}
		).insert(ignore_permissions=True)
