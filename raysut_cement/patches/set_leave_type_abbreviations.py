# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""Report Abbreviation on the leave types in use: the old TAMS pay codes, and HRMS's defaults."""

import frappe

CODES = {
	"Annual Leave": "AL",
	"Sick Leave": "SL",
	"Casual Leave": "CL",
	"Emergency Leave": "EL",
	"Special Leave": "SPL",
	"Lieu Leave": "LL",
	"Leave Without Pay": "NP",
	"Privilege Leave": "PL",
	"Compensatory Off": "CO",
	"Maternity Leave": "ML",
	"Hajj Leave": "HJL",
}


def execute():
	from frappe.utils.fixtures import sync_fixtures

	sync_fixtures("raysut_cement")  # migrate imports fixtures after patches; the field must exist now
	for leave_type, code in CODES.items():
		if frappe.db.exists("Leave Type", leave_type) and not frappe.db.get_value("Leave Type", leave_type, "report_abbreviation"):
			frappe.db.set_value("Leave Type", leave_type, "report_abbreviation", code, update_modified=False)
