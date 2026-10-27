// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.ui.form.on("Shift Pattern Assignment", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status === "Active") {
			frm.add_custom_button(__("Regenerate Future Shifts"), () => {
				frappe.confirm(
					__("Remove the generated shifts after today and create them again from the current Shift Pattern? Past shifts and manual Shift Assignments are not touched."),
					() =>
						frappe.call({
							method: "raysut_cement.raysut_cement.doctype.shift_pattern_assignment.shift_pattern_assignment.regenerate_now",
							args: { name: frm.doc.name },
							freeze: true,
							callback: () => frm.reload_doc(),
						})
				);
			});
		}
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Shift Assignments"), () =>
				frappe.set_route("List", "Shift Assignment", { shift_pattern_assignment: frm.doc.name })
			, __("View"));
			frm.add_custom_button(__("Shift Roster"), () =>
				frappe.set_route("query-report", "Shift Roster", { company: frm.doc.company, shift_pattern: frm.doc.shift_pattern })
			, __("View"));
		}
	},
	assign_to(frm) {
		["employee", "department", "branch", "designation", "employee_group"].forEach((f) => frm.set_value(f, null));
	},
});
