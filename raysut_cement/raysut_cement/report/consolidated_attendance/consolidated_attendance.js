// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.query_reports["Consolidated Attendance"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", reqd: 1, default: frappe.datetime.month_end() },
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1, default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "department", label: __("Department"), fieldtype: "Link", options: "Department" },
		{ fieldname: "shift_type", label: __("Shift Type"), fieldtype: "Link", options: "Shift Type" },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "employment_type", label: __("Employment Type"), fieldtype: "Link", options: "Employment Type" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "Active\nInactive\nLeft\nAll", default: "Active" },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "\nDepartment\nBranch" },
		{ fieldname: "show_zero_leave_columns", label: __("Show zero leave columns"), fieldtype: "Check" },
		{ fieldname: "paper_size", label: __("PDF Paper Size"), fieldtype: "Select", options: "A3\nA4", default: "A3" },
	],

	formatter(value, row, column, data, default_formatter) {
		let formatted = default_formatter(value, row, column, data);
		if (!data) return formatted;
		if (data.is_total) return `<b>${formatted}</b>`;
		if (column.fieldname === "employee_name" && data.employee) {
			// drill-down: the employee's days in the Daily Attendance report
			formatted = `<a class="rc-daily-attendance" data-employee="${encodeURIComponent(data.employee)}">${formatted}</a>`;
		}
		if (!data.balanced) {
			return `<span style="color:var(--red-600);font-weight:600;">${formatted}</span>`;
		}
		if (column.fieldname === "nm" && data.nm) {
			return `<span style="background:var(--yellow-100);color:var(--yellow-800);padding:0 4px;">${formatted}</span>`;
		}
		return formatted;
	},

	onload(report) {
		$(report.page.wrapper).on("click", ".rc-daily-attendance", (e) => {
			const filters = report.get_values();
			frappe.set_route("query-report", "Daily Attendance", {
				company: filters.company,
				employee: decodeURIComponent($(e.currentTarget).data("employee")),
				from_date: filters.from_date,
				to_date: filters.to_date,
			});
		});

		report.page.add_inner_button(__("SAP Export"), () => {
			const filters = report.get_values();
			const columns = report.columns || [];
			const leave_fields = columns.filter((c) => c.fieldname.startsWith("leave_"));
			const rows = (report.data || []).filter((r) => r.employee && !r.is_total);
			if (!rows.length) {
				frappe.msgprint(__("Run the report first"));
				return;
			}
			const csv = [
				["Employee ID", "From Date", "To Date", "PR", "AB", ...leave_fields.map((c) => c.label),
					"Leave Total", "OT1 Hours", "OT2 Hours", "Under Time Hours"],
			];
			for (const r of rows) {
				const leaves = leave_fields.map((c) => r[c.fieldname] || 0);
				csv.push([r.employee, filters.from_date, filters.to_date, r.pr, r.ab, ...leaves,
					leaves.reduce((a, b) => a + b, 0), r.ot1_hours, r.ot2_hours, r.under_time_hours]);
			}
			frappe.tools.downloadify(csv, null, `SAP Attendance ${filters.from_date} to ${filters.to_date}`);
		});
	},
};
