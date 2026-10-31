// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.query_reports["Consolidated Attendance"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_end() },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
	],
};
