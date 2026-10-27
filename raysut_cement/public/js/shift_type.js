// Shift Type shown as a HikCentral-style "Timetable": overview bar + flexible window sync.

const TIMETABLE_FIELDS = [
	"shift_mode", "shift_color", "start_time", "end_time", "valid_period_start", "valid_period_end",
	"valid_period_end_day", "enable_latest_check_in", "latest_check_in_day", "latest_check_in_time",
];
const DAY_OFFSET = { "Current Day": 0, "Next Day": 1, "Next 2 Days": 2, "Next 3 Days": 3 };

const timetable_handlers = {
	refresh: (frm) => render_timetable_overview(frm),
	valid_period_start: (frm) => sync_flexible_window(frm),
	valid_period_end: (frm) => sync_flexible_window(frm),
	shift_mode: (frm) => sync_flexible_window(frm),
};
TIMETABLE_FIELDS.forEach((field) => {
	const existing = timetable_handlers[field];
	timetable_handlers[field] = (frm) => {
		existing && existing(frm);
		render_timetable_overview(frm);
	};
});
frappe.ui.form.on("Shift Type", timetable_handlers);

frappe.ui.form.on("Timetable Break", {
	break_timetable: (frm) => setTimeout(() => render_timetable_overview(frm), 300),
	timetable_breaks_remove: (frm) => render_timetable_overview(frm),
});

function sync_flexible_window(frm) {
	if (frm.doc.shift_mode !== "Flexible") return;
	if (frm.doc.valid_period_start && frm.doc.start_time !== frm.doc.valid_period_start) {
		frm.set_value("start_time", frm.doc.valid_period_start);
	}
	if (frm.doc.valid_period_end && frm.doc.end_time !== frm.doc.valid_period_end) {
		frm.set_value("end_time", frm.doc.valid_period_end);
	}
}

function to_minutes(value) {
	if (!value) return null;
	const [h, m, s] = String(value).split(":").map((x) => parseInt(x || 0, 10));
	return h * 60 + m + Math.round((s || 0) / 60);
}

function fmt(minutes) {
	const m = ((minutes % 1440) + 1440) % 1440;
	const label = `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
	return minutes >= 1440 ? `${label} (+${Math.floor(minutes / 1440)})` : label;
}

function timetable_range(doc) {
	if (doc.shift_mode === "Flexible") {
		const start = to_minutes(doc.valid_period_start);
		let end = to_minutes(doc.valid_period_end);
		if (end !== null && doc.valid_period_end_day === "Next Day") end += 1440;
		return [start, end];
	}
	const start = to_minutes(doc.start_time);
	let end = to_minutes(doc.end_time);
	if (start !== null && end !== null && end <= start) end += 1440;
	return [start, end];
}

function render_timetable_overview(frm) {
	const field = frm.get_field("timetable_overview");
	if (!field) return;
	const doc = frm.doc;
	const [start, end] = timetable_range(doc);
	if (start === null || end === null) {
		field.$wrapper.html(`<div class="text-muted small">${__("Set the time range to see the overview.")}</div>`);
		return;
	}

	const latest = doc.shift_mode === "Flexible" && doc.enable_latest_check_in && doc.latest_check_in_time
		? DAY_OFFSET[doc.latest_check_in_day || "Current Day"] * 1440 + to_minutes(doc.latest_check_in_time)
		: null;
	const span = Math.max(end, latest || 0) > 1440 ? 2880 : 1440;
	const pct = (m) => `${Math.min(100, Math.max(0, (m / span) * 100))}%`;
	const color = doc.shift_color || "#5e64ff";

	const ticks = [];
	const step = span === 1440 ? 120 : 240;
	for (let m = 0; m <= span; m += step) {
		ticks.push(`<div style="position:absolute;left:${pct(m)};top:46px;transform:translateX(-50%);font-size:10px;color:var(--text-muted);">${fmt(m)}</div>
			<div style="position:absolute;left:${pct(m)};top:36px;height:6px;border-left:1px solid var(--border-color);"></div>`);
	}

	const breaks = (doc.timetable_breaks || [])
		.filter((b) => b.break_type === "Fixed" && b.break_start && b.break_end)
		.map((b) => {
			let b_start = to_minutes(b.break_start);
			if (b_start < start) b_start += 1440;
			let b_end = b_start + ((to_minutes(b.break_end) - to_minutes(b.break_start) + 1440) % 1440);
			return `<div title="${frappe.utils.escape_html(b.break_timetable)} ${fmt(b_start)}-${fmt(b_end)}"
				style="position:absolute;left:${pct(b_start)};width:calc(${pct(b_end)} - ${pct(b_start)});top:16px;height:20px;background:#f39c12;opacity:.9;border-radius:2px;"></div>`;
		})
		.join("");

	const marker = latest === null ? "" : `
		<div title="${__("Latest check-in")} ${fmt(latest)}" style="position:absolute;left:${pct(latest)};top:10px;height:32px;border-left:3px solid #28a745;"></div>
		<div style="position:absolute;left:${pct(latest)};top:-6px;transform:translateX(-50%);font-size:10px;color:#28a745;white-space:nowrap;">${__("Latest check-in")} ${fmt(latest)}</div>`;

	const title = doc.shift_mode === "Flexible"
		? `<div style="font-size:11px;font-weight:600;margin-bottom:14px;">${__("Flexible Shift Time Range")}</div>` : "";

	field.$wrapper.html(`
		${title}
		<div style="position:relative;height:64px;margin:8px 24px 4px;">
			<div style="position:absolute;left:0;right:0;top:16px;height:20px;background:var(--control-bg);border-radius:3px;"></div>
			<div style="position:absolute;left:${pct(start)};width:calc(${pct(end)} - ${pct(start)});top:16px;height:20px;background:${color};border-radius:3px;"></div>
			<div style="position:absolute;left:${pct(start)};top:0;font-size:10px;font-weight:600;transform:translateX(-50%);">${fmt(start)}</div>
			<div style="position:absolute;left:${pct(end)};top:0;font-size:10px;font-weight:600;transform:translateX(-50%);">${fmt(end)}</div>
			${breaks}${marker}${ticks.join("")}
		</div>
		<div class="small text-muted" style="margin:0 24px;">
			<span style="display:inline-block;width:10px;height:10px;background:${color};"></span> ${__("Time range")}
			&nbsp; <span style="display:inline-block;width:10px;height:10px;background:#f39c12;"></span> ${__("Fixed break")}
			${latest === null ? "" : `&nbsp; <span style="display:inline-block;width:10px;height:10px;background:#28a745;"></span> ${__("Latest check-in")}`}
		</div>`);
}
