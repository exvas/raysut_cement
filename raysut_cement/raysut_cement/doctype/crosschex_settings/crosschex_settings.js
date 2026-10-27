// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

const CROSSCHEX_METHOD = "raysut_cement.raysut_cement.doctype.crosschex_settings.crosschex_settings";

frappe.ui.form.on("Crosschex Settings", {
	refresh(frm) {
		const status = frm.doc.connection_status || "Disconnected";
		frm.page.set_indicator(__(status), status === "Connected" ? "green" : "orange");
		if (frm.doc.enable_realtime_sync && frm.doc.last_sync_time) {
			frm.dashboard.set_headline(__("Last sync: {0}", [moment(frm.doc.last_sync_time).fromNow()]));
		}
		frm.add_custom_button(__("CrossChex Logs"), () => frappe.set_route("List", "CrossChex Log"));
	},
});

frappe.ui.form.on("CrossChex API Configuration", {
	test_connection(frm, cdt, cdn) {
		run_row_action(frm, locals[cdt][cdn], "test_individual_api_config", __("Testing connection..."));
	},
	sync_now(frm, cdt, cdn) {
		run_row_action(frm, locals[cdt][cdn], "sync_individual_device", __("Syncing punches..."));
	},
});

function run_row_action(frm, row, method, busy_message) {
	if (frm.is_dirty() || !row.name || row.name.startsWith("new-")) {
		frappe.msgprint(__("Please save Crosschex Settings first. The API Secret is only stored after saving."));
		return;
	}
	frappe.call({
		method: `${CROSSCHEX_METHOD}.${method}`,
		args: { config_row_name: row.name },
		freeze: true,
		freeze_message: busy_message,
		callback(r) {
			const result = r.message || {};
			frappe.msgprint({
				title: result.success ? __("Success") : __("Error"),
				message: result.success ? result.message : result.error || __("Request failed"),
				indicator: result.success ? "green" : "red",
			});
			frm.reload_doc();
		},
	});
}
