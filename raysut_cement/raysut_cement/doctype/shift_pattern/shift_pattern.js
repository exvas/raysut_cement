// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

// HikCentral-style "Shift" screen: a palette of timetables and one row per day of the cycle.

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MAX_REPEAT = { Week: 4, Day: 31, Month: 3 };

frappe.ui.form.on("Shift Pattern", {
	onload(frm) {
		frm.shift_grid = new ShiftGrid(frm);
	},
	refresh(frm) {
		frm.shift_grid = frm.shift_grid || new ShiftGrid(frm);
		frm.shift_grid.load();
	},
	repeat_mode(frm) {
		frm.shift_grid.on_cycle_change();
	},
	repeat_every(frm) {
		frm.shift_grid.on_cycle_change();
	},
	week_starts_on(frm) {
		frm.shift_grid.render();
	},
	copy_from(frm) {
		if (!frm.doc.copy_from) return;
		frappe.confirm(
			__("Replace the repeat settings and all days with those of {0}?", [frm.doc.copy_from.bold()]),
			() => frm.shift_grid.copy_from(frm.doc.copy_from),
			() => frm.set_value("copy_from", null)
		);
	},
	validate(frm) {
		const errors = frm.shift_grid.find_overlaps();
		if (errors.length) {
			frappe.msgprint({ title: __("Overlapping timetables"), message: errors.join("<br>"), indicator: "red" });
			frappe.validated = false;
		}
		if (!(frm.doc.days || []).length) {
			frappe.msgprint(__("Assign a timetable to at least one day."));
			frappe.validated = false;
		}
	},
});

class ShiftGrid {
	constructor(frm) {
		this.frm = frm;
		this.details = {};
		this.selected = null;
		this.filter = "";
		this.drag = null;
		this.last_cycle = [frm.doc.repeat_mode, frm.doc.repeat_every];
	}

	get $wrapper() {
		return this.frm.get_field("shift_grid").$wrapper;
	}

	// ------------------------------------------------------------ data

	palette() {
		let names = [];
		try {
			names = JSON.parse(this.frm.doc.palette_timetables || "[]");
		} catch (e) {
			names = [];
		}
		(this.frm.doc.days || []).forEach((d) => !names.includes(d.timetable) && names.push(d.timetable));
		return names;
	}

	set_palette(names) {
		this.frm.doc.palette_timetables = JSON.stringify(names);
		this.frm.dirty();
	}

	load() {
		const missing = this.palette().filter((n) => !this.details[n]);
		if (!missing.length) return this.render();
		frappe.call({
			method: "raysut_cement.raysut_cement.doctype.shift_pattern.shift_pattern.get_timetable_details",
			args: { names: missing },
			callback: (r) => {
				(r.message || []).forEach((d) => (this.details[d.name] = d));
				this.render();
			},
		});
	}

	slots() {
		const doc = this.frm.doc;
		const n = Math.max(1, Math.min(cint(doc.repeat_every) || 1, MAX_REPEAT[doc.repeat_mode] || 1));
		const slots = [];
		if (doc.repeat_mode === "Day") {
			for (let i = 1; i <= n; i++) slots.push({ cycle: i, key: `Day ${i}`, label: `Day ${i}` });
		} else if (doc.repeat_mode === "Month") {
			for (let m = 1; m <= n; m++)
				for (let d = 1; d <= 31; d++) slots.push({ cycle: m, key: String(d), label: `${n > 1 ? `M${m} ` : ""}${d}` });
		} else {
			const start = WEEKDAYS.indexOf(doc.week_starts_on || "Sunday");
			const week = WEEKDAYS.slice(start).concat(WEEKDAYS.slice(0, start));
			for (let w = 1; w <= n; w++)
				week.forEach((day) => slots.push({ cycle: w, key: day, label: `${n > 1 ? `W${w} ` : ""}${__(day)}` }));
		}
		return slots;
	}

	timetables_on(slot) {
		return (this.frm.doc.days || [])
			.filter((d) => cint(d.cycle_index) === slot.cycle && d.day_key === slot.key)
			.sort((a, b) => cint(a.sequence) - cint(b.sequence))
			.map((d) => d.timetable);
	}

	range(name) {
		const d = this.details[name];
		return d ? [d.start, d.end] : null;
	}

	// ------------------------------------------------------------ editing

	add(slot, name) {
		if (this.timetables_on(slot).includes(name)) return;
		const row = this.frm.add_child("days", {
			cycle_index: slot.cycle,
			day_key: slot.key,
			timetable: name,
			sequence: this.timetables_on(slot).length + 1,
		});
		return row;
	}

	remove(slot, name) {
		this.frm.doc.days = (this.frm.doc.days || []).filter(
			(d) => !(cint(d.cycle_index) === slot.cycle && d.day_key === slot.key && d.timetable === name)
		);
		this.after_change();
	}

	after_change() {
		(this.frm.doc.days || []).forEach((d, i) => (d.idx = i + 1));
		this.frm.refresh_field("days");
		this.frm.dirty();
		this.render();
	}

	apply_selected(slots) {
		if (!this.selected) {
			frappe.show_alert({ message: __("Select a timetable in the palette first"), indicator: "orange" });
			return;
		}
		slots.forEach((slot) => this.add(slot, this.selected));
		this.after_change();
	}

	on_cycle_change() {
		const valid = new Set(this.slots().map((s) => `${s.cycle}|${s.key}`));
		const dropped = (this.frm.doc.days || []).filter((d) => !valid.has(`${cint(d.cycle_index)}|${d.day_key}`));
		const keep = () => {
			this.last_cycle = [this.frm.doc.repeat_mode, this.frm.doc.repeat_every];
			this.frm.doc.days = (this.frm.doc.days || []).filter((d) => valid.has(`${cint(d.cycle_index)}|${d.day_key}`));
			this.after_change();
		};
		if (!dropped.length) return keep();
		frappe.confirm(
			__("Changing the repetition removes {0} timetable assignment(s) that no longer fit the cycle. Continue?", [dropped.length]),
			keep,
			() => {
				const [mode, every] = this.last_cycle;
				this.frm.doc.repeat_mode = mode;
				this.frm.doc.repeat_every = every;
				this.frm.refresh_fields(["repeat_mode", "repeat_every"]);
				this.render();
			}
		);
	}

	copy_from(name) {
		frappe.db.get_doc("Shift Pattern", name).then((src) => {
			["repeat_mode", "repeat_every", "week_starts_on", "palette_timetables"].forEach((f) => (this.frm.doc[f] = src[f]));
			this.frm.doc.days = [];
			(src.days || []).forEach((d) =>
				this.frm.add_child("days", { cycle_index: d.cycle_index, day_key: d.day_key, timetable: d.timetable, sequence: d.sequence })
			);
			this.frm.doc.copy_from = null;
			this.frm.refresh_fields(["repeat_mode", "repeat_every", "week_starts_on", "copy_from"]);
			this.after_change();
			this.load();
		});
	}

	add_timetables_dialog() {
		new frappe.ui.form.MultiSelectDialog({
			doctype: "Shift Type",
			target: this.frm,
			setters: { shift_mode: null },
			add_filters_group: 1,
			primary_action_label: __("Add to Palette"),
			action: (selections) => {
				const names = this.palette();
				selections.forEach((s) => !names.includes(s) && names.push(s));
				this.set_palette(names);
				this.selected = selections[0] || this.selected;
				cur_dialog && cur_dialog.hide();
				this.load();
			},
		});
	}

	delete_selected() {
		if (!this.selected) return;
		const name = this.selected;
		frappe.confirm(__("Remove {0} from the palette and from every day?", [name.bold()]), () => {
			this.set_palette(this.palette().filter((n) => n !== name));
			this.frm.doc.days = (this.frm.doc.days || []).filter((d) => d.timetable !== name);
			this.selected = null;
			this.after_change();
		});
	}

	clear_all() {
		frappe.confirm(__("Remove all timetables from every day?"), () => {
			this.frm.doc.days = [];
			this.after_change();
		});
	}

	// ------------------------------------------------------------ validation

	find_overlaps() {
		const slots = this.slots();
		const errors = [];
		slots.forEach((slot, i) => {
			const ranges = this.timetables_on(slot)
				.map((n) => [this.range(n), n])
				.filter((r) => r[0])
				.sort((a, b) => a[0][0] - b[0][0]);
			for (let j = 1; j < ranges.length; j++) {
				if (ranges[j][0][0] < ranges[j - 1][0][1])
					errors.push(__("{0}: {1} and {2} overlap", [slot.label, ranges[j - 1][1], ranges[j][1]]));
			}
			const next = this.next_slot(slots, i);
			const overnight = ranges.filter((r) => r[0][1] > 1440);
			if (!next || !overnight.length) return;
			const first = this.timetables_on(next)
				.map((n) => [this.range(n), n])
				.filter((r) => r[0])
				.sort((a, b) => a[0][0] - b[0][0])[0];
			overnight.forEach((r) => {
				if (first && first[0][0] + 1440 < r[0][1])
					errors.push(__("{0}: {1} runs past midnight into {2} on {3}", [slot.label, r[1], first[1], next.label]));
			});
		});
		return errors;
	}

	next_slot(slots, i) {
		if (this.frm.doc.repeat_mode === "Month") {
			const slot = slots[i];
			return cint(slot.key) < 31 ? slots[i + 1] : null;
		}
		return slots[(i + 1) % slots.length];
	}

	// ------------------------------------------------------------ rendering

	render() {
		if (!this.frm.get_field("shift_grid")) return;
		const palette = this.palette();
		const errors = this.find_overlaps();
		const slots = this.slots();

		const chips = palette
			.filter((n) => !this.filter || n.toLowerCase().includes(this.filter.toLowerCase()))
			.map((n) => {
				const color = (this.details[n] || {}).color || "#999";
				const active = n === this.selected ? `box-shadow:0 0 0 2px ${color};` : "";
				return `<span class="sp-chip" data-name="${frappe.utils.escape_html(n)}"
					style="display:inline-flex;align-items:center;gap:6px;margin:0 6px 6px 0;padding:3px 10px;border:1px solid var(--border-color);border-radius:14px;cursor:pointer;font-size:12px;${active}">
					<span style="width:10px;height:10px;border-radius:2px;background:${color};"></span>${frappe.utils.escape_html(n)}</span>`;
			})
			.join("");

		const ticks = [];
		for (let h = 0; h <= 24; h += 2)
			ticks.push(`<span style="position:absolute;left:${(h / 24) * 100}%;transform:translateX(-50%);font-size:10px;color:var(--text-muted);">${String(h).padStart(2, "0")}</span>`);

		const carry = {};
		slots.forEach((slot, i) => {
			const next = this.next_slot(slots, i);
			if (!next) return;
			this.timetables_on(slot).forEach((n) => {
				const r = this.range(n);
				if (r && r[1] > 1440) (carry[`${next.cycle}|${next.key}`] = carry[`${next.cycle}|${next.key}`] || []).push([n, r[1] - 1440]);
			});
		});

		const rows = slots
			.map((slot, i) => {
				const bars = this.timetables_on(slot)
					.map((n) => {
						const r = this.range(n);
						if (!r) return "";
						const color = this.details[n].color;
						const left = (r[0] / 1440) * 100;
						const width = ((Math.min(r[1], 1440) - r[0]) / 1440) * 100;
						return `<div class="sp-bar" data-name="${frappe.utils.escape_html(n)}" title="${frappe.utils.escape_html(n)} - ${__("right-click to remove")}"
							style="position:absolute;top:3px;bottom:3px;left:${left}%;width:${width}%;background:${color};border-radius:3px;color:#fff;font-size:10px;overflow:hidden;white-space:nowrap;padding:0 4px;">
							${frappe.utils.escape_html(n)}<span class="sp-x" style="position:absolute;right:3px;cursor:pointer;display:none;">&times;</span></div>`;
					})
					.join("");
				const carried = (carry[`${slot.cycle}|${slot.key}`] || [])
					.map(([n, end]) => `<div title="${frappe.utils.escape_html(n)} (${__("from previous day")})"
						style="position:absolute;top:3px;bottom:3px;left:0;width:${(end / 1440) * 100}%;background:${this.details[n].color};opacity:.45;border-radius:3px;"></div>`)
					.join("");
				const rest = this.timetables_on(slot).length ? "" : `<span style="position:absolute;left:6px;top:4px;font-size:10px;color:var(--text-light);">${__("Rest day")}</span>`;
				return `<div class="sp-row" data-index="${i}" style="display:flex;align-items:center;border-bottom:1px solid var(--border-color);user-select:none;">
					<div style="width:110px;font-size:12px;padding:4px 8px;">${slot.label}</div>
					<div class="sp-track" style="position:relative;flex:1;height:26px;background:var(--control-bg);cursor:copy;">${rest}${carried}${bars}</div>
				</div>`;
			})
			.join("");

		this.$wrapper.html(`
			<div class="sp-grid">
				<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
					<b>${__("Timetable")}</b>
					<button class="btn btn-xs btn-default sp-add">${frappe.utils.icon("add", "xs")} ${__("Add Timetable")}</button>
					<input class="form-control input-xs sp-filter" placeholder="${__("Filter")}" style="width:140px;" value="${frappe.utils.escape_html(this.filter)}">
					<button class="btn btn-xs btn-default sp-delete" ${this.selected ? "" : "disabled"}>${frappe.utils.icon("delete", "xs")}</button>
					<button class="btn btn-xs btn-default sp-clear" style="margin-left:auto;">${__("Clear All")}</button>
				</div>
				<div>${chips || `<span class="text-muted small">${__("Add timetables, select one, then click or drag across days.")}</span>`}</div>
				${errors.length ? `<div class="alert alert-danger small" style="margin:6px 0;">${errors.join("<br>")}</div>` : ""}
				<div style="display:flex;margin-top:6px;"><div style="width:110px;"></div><div style="position:relative;flex:1;height:14px;">${ticks.join("")}</div></div>
				<div style="border-top:1px solid var(--border-color);max-height:520px;overflow:auto;">${rows}</div>
			</div>`);
		this.bind(slots);
	}

	bind(slots) {
		const $w = this.$wrapper;
		$w.find(".sp-add").on("click", () => this.add_timetables_dialog());
		$w.find(".sp-delete").on("click", () => this.delete_selected());
		$w.find(".sp-clear").on("click", () => this.clear_all());
		$w.find(".sp-filter").on("input", frappe.utils.debounce((e) => {
			this.filter = e.target.value;
			this.render();
			this.$wrapper.find(".sp-filter").focus();
		}, 300));
		$w.find(".sp-chip").on("click", (e) => {
			const name = $(e.currentTarget).attr("data-name");
			this.selected = this.selected === name ? null : name;
			this.render();
		});

		const slot_of = (el) => slots[cint($(el).closest(".sp-row").attr("data-index"))];
		$w.find(".sp-bar")
			.on("mouseenter", (e) => $(e.currentTarget).find(".sp-x").show())
			.on("mouseleave", (e) => $(e.currentTarget).find(".sp-x").hide())
			.on("contextmenu", (e) => {
				e.preventDefault();
				this.remove(slot_of(e.currentTarget), $(e.currentTarget).attr("data-name"));
			})
			.on("mousedown", (e) => e.stopPropagation());
		$w.find(".sp-x").on("click", (e) => {
			e.stopPropagation();
			const bar = $(e.currentTarget).closest(".sp-bar");
			this.remove(slot_of(bar), bar.attr("data-name"));
		});

		$w.find(".sp-track")
			.on("mousedown", (e) => {
				if (e.button !== 0) return;
				this.drag = { from: cint($(e.currentTarget).closest(".sp-row").attr("data-index")) };
				this.drag.to = this.drag.from;
				this.highlight();
			})
			.on("mouseenter", (e) => {
				if (!this.drag) return;
				this.drag.to = cint($(e.currentTarget).closest(".sp-row").attr("data-index"));
				this.highlight();
			});
		$(document).off("mouseup.shift_grid").on("mouseup.shift_grid", () => {
			if (!this.drag) return;
			const [a, b] = [Math.min(this.drag.from, this.drag.to), Math.max(this.drag.from, this.drag.to)];
			this.drag = null;
			this.apply_selected(slots.slice(a, b + 1));
		});
	}

	highlight() {
		const [a, b] = [Math.min(this.drag.from, this.drag.to), Math.max(this.drag.from, this.drag.to)];
		this.$wrapper.find(".sp-row").each((i, el) => {
			$(el).find(".sp-track").css("outline", i >= a && i <= b ? "2px dashed var(--primary)" : "none");
		});
	}
}
