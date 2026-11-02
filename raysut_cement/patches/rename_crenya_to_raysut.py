# Copyright (c) 2026, sammish and contributors
# For license information, please see license.txt

"""The workspace, sidebar and dashboard page are now "Raysut Attendance" / "raysut-dashboard".
Their files moved, so remove the old "Crenya" records that would otherwise linger in the menu."""

import frappe

OLD = (("Page", "crenya-dashboard"), ("Workspace", "Crenya Attendance"), ("Sidebar", "Crenya Attendance"))


def execute():
	for doctype, name in OLD:
		if frappe.db.exists("DocType", doctype) and frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, ignore_missing=True)
	for user in frappe.get_all("User", {"default_workspace": "Crenya Attendance"}, pluck="name"):
		frappe.db.set_value("User", user, "default_workspace", "Raysut Attendance", update_modified=False)
