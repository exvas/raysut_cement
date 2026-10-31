# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""The report now adds its own Grand Total (with HH:MM durations). Frappe keeps a report's
add_total_row from the database on re-import, so switch Frappe's extra total row off here."""

import frappe


def execute():
	if frappe.db.exists("Report", "Consolidated Attendance"):
		frappe.db.set_value("Report", "Consolidated Attendance", "add_total_row", 0, update_modified=False)
