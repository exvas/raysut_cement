// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.query_reports["Shift Roster"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.add_days(frappe.datetime.get_today(), 13) },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "shift_pattern", label: __("Shift Pattern"), fieldtype: "Link", options: "Shift Pattern" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data || !column.fieldname.startsWith("d_")) return formatted;
		if ((data._holidays || []).includes(column.fieldname)) {
			return `<div style="background:var(--gray-200);color:var(--text-muted);padding:0 4px;">${value || __("Holiday")}</div>`;
		}
		const color = (data._colors || {})[column.fieldname];
		if (!color) return "";
		return `<div title="${frappe.utils.escape_html(value)}" style="background:${color};color:#fff;border-radius:3px;padding:0 4px;overflow:hidden;white-space:nowrap;">${frappe.utils.escape_html(value)}</div>`;
	},
};
