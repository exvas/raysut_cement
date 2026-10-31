// "Process Flexible Attendance" on the Attendance list (Flexible Shift & Overtime)

const raysut_attendance_listview = frappe.listview_settings["Attendance"] || {};
const core_attendance_onload = raysut_attendance_listview.onload;

frappe.listview_settings["Attendance"] = Object.assign(raysut_attendance_listview, {
	onload(listview) {
		core_attendance_onload && core_attendance_onload(listview);
		if (frappe.boot.raysut_features?.enable_flexible_overtime === false) return;
		if (!frappe.user.has_role(["System Manager", "HR Manager"])) return;

		listview.page.add_inner_button(__("Process Flexible Attendance"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Process Flexible Attendance"),
				fields: [
					{ fieldname: "from_date", fieldtype: "Date", label: __("From Date"), reqd: 1,
						default: frappe.datetime.add_days(frappe.datetime.get_today(), -3) },
					{ fieldname: "to_date", fieldtype: "Date", label: __("To Date"), reqd: 1,
						default: frappe.datetime.get_today() },
					{ fieldname: "employee", fieldtype: "Link", options: "Employee", label: __("Employee"),
						description: __("Leave empty for every employee on a flexible shift") },
					{ fieldname: "reprocess", fieldtype: "Check", label: __("Re-process submitted attendance"),
						description: __("Cancels and re-creates submitted attendance for these days (On Leave is kept)") },
				],
				primary_action_label: __("Process"),
				primary_action(values) {
					dialog.hide();
					frappe.call({
						method: "raysut_cement.raysut_cement.attendance.flexible.run_flexible_attendance",
						args: values,
						freeze: true,
						callback({ message }) {
							if (message?.queued) {
								frappe.show_alert({ message: __("Processing in the background"), indicator: "blue" });
							} else if (message) {
								frappe.msgprint(__("Created {0}, updated {1}, skipped {2}, errors {3}",
									[message.created, message.updated, message.skipped, message.errors]));
								listview.refresh();
							}
						},
					});
				},
			});
			dialog.show();
		});
	},
});
