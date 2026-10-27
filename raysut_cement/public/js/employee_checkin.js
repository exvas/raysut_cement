frappe.ui.form.on("Employee Checkin", {
	refresh(frm) {
		const enabled = frappe.boot.raysut_features?.enable_checkin_summary !== false;
		frm.toggle_display("checkin_summary_html", enabled);
		if (enabled && !frm.is_new()) {
			show_checkin_summary(frm);
		}
	},
});

// All punches of the same employee on the same day, shown in checkin_summary_html
function show_checkin_summary(frm) {
	const field = frm.get_field("checkin_summary_html");
	if (!field || !frm.doc.employee || !frm.doc.time) return;

	const date = frm.doc.time.split(" ")[0];
	frappe.db
		.get_list("Employee Checkin", {
			filters: { employee: frm.doc.employee, time: ["between", [`${date} 00:00:00`, `${date} 23:59:59`]] },
			fields: ["name", "time", "log_type", "device_id"],
			order_by: "time asc",
			limit: 50,
		})
		.then((rows) => {
			if (!rows.length) return;
			const body = rows
				.map((row) => {
					const color = row.log_type === "IN" ? "green" : "red";
					const current = row.name === frm.doc.name ? ' style="font-weight: bold;"' : "";
					return `<tr${current}>
						<td>${frappe.datetime.str_to_user(row.time)}</td>
						<td><span class="indicator-pill ${color}">${frappe.utils.escape_html(row.log_type || "-")}</span></td>
						<td>${frappe.utils.escape_html(row.device_id || "-")}</td>
					</tr>`;
				})
				.join("");
			field.$wrapper.html(`
				<table class="table table-bordered table-sm" style="margin: 0;">
					<thead><tr><th>${__("Time")}</th><th>${__("Type")}</th><th>${__("Device")}</th></tr></thead>
					<tbody>${body}</tbody>
				</table>`);
		});
}
