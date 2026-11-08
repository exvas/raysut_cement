// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.query_reports["Attendance Detail Report"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{
			fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
		{
			fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department",
			get_query: () => ({ filters: { company: frappe.query_report.get_filter_value("company") } }),
		},
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data) return formatted;
		if (data.is_total) return `<b>${formatted}</b>`;
		if (column.fieldname === "code" && value) {
			const tone = { PR: "", WFH: "", AB: "red", OF: "blue", MP: "purple", NM: "orange", HD: "orange" }[value];
			const color = tone === undefined ? "green" : tone;
			return color ? `<span style="color:var(--${color}-600);font-weight:600;">${formatted}</span>` : formatted;
		}
		if (data.is_off && ["day", "date", "remarks"].includes(column.fieldname)) {
			return `<span style="color:var(--text-muted);">${formatted}</span>`;
		}
		return formatted;
	},
};
