// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.query_reports["Daily Attendance"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "shift_type", label: __("Shift Type"), fieldtype: "Link", options: "Shift Type" },
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data) return formatted;
		if (column.fieldname === "under_time" && data.under_time_hours) {
			return `<span style="color:var(--orange-600);font-weight:600;">${formatted}</span>`;
		}
		if (column.fieldname === "late" && value !== "00:00") {
			return `<span style="color:var(--red-600);">${formatted}</span>`;
		}
		if (column.fieldname === "flags" && value) {
			return `<span style="color:var(--blue-600);">${formatted}</span>`;
		}
		return formatted;
	},
};
