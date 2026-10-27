// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.query_reports["Flexible Shift Work Hours"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.add_days(frappe.datetime.get_today(), -7) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "shift_pattern", label: __("Shift Pattern"), fieldtype: "Link", options: "Shift Pattern" },
		{ fieldname: "timetable", label: __("Timetable"), fieldtype: "Link", options: "Shift Type" },
	],
	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!data) return formatted;
		if (data.below_required && ["net_hours", "difference", "status"].includes(column.fieldname)) {
			return `<span style="color:var(--red-600);font-weight:600;">${formatted}</span>`;
		}
		if (data.status === "Rest Day Work" && column.fieldname === "status") {
			return `<span style="color:var(--blue-600);">${formatted}</span>`;
		}
		return formatted;
	},
};
