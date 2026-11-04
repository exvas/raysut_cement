# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Pioneer Cement and Sohar Cement as companies of their own, set up like Raysut Cement.

A company already there under a longer name (e.g. "Pioneer Cement Industries") is used as it is;
otherwise it is created with Raysut's country, currency and chart of accounts template. Either way it
gets Raysut's holiday list when it has none, and the Raysut departments it doesn't have yet. Their own
shifts, employees and settings follow once the group sends them.
"""

import frappe

# name to look for (and to create with), abbreviation for a new one
COMPANIES = {"Pioneer Cement": "PC", "Sohar Cement": "SC"}


def execute():
	source = frappe.get_all("Company", filters={"company_name": ("like", "Raysut Cement%")}, pluck="name", limit=1)
	if source:
		create_companies(source[0])


def create_companies(source):
	src = frappe.get_doc("Company", source)
	for name, abbr in COMPANIES.items():
		company = frappe.get_all("Company", filters={"company_name": ("like", f"{name}%")}, pluck="name", limit=1)
		company = company[0] if company else new_company(src, name, abbr)
		if src.default_holiday_list and not frappe.db.get_value("Company", company, "default_holiday_list"):
			frappe.db.set_value("Company", company, "default_holiday_list", src.default_holiday_list)
		copy_departments(src.name, company)


def new_company(src, name, abbr):
	return (
		frappe.get_doc(
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
		)
		.insert(ignore_permissions=True)
		.name
	)


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
