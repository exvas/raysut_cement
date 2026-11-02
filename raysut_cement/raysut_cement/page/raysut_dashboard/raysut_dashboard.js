// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

// one scope, so the helpers below do not clash with other desk scripts
(() => {
	frappe.pages["raysut-dashboard"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Attendance Dashboard"), single_column: true });
		$(wrapper).addClass("rd-page");
		if (!document.getElementById("rd-font")) {
			$("head").append(`<link id="rd-font" rel="stylesheet"
				href="https://fonts.googleapis.com/css2?family=Nunito:wght@500;600;700;800;900&display=swap">`);
		}
		wrapper.raysut_dashboard = new RaysutDashboard(page);
	};

	frappe.pages["raysut-dashboard"].on_page_show = function (wrapper) {
		wrapper.raysut_dashboard && wrapper.raysut_dashboard.refresh();
	};

	const METHOD = "raysut_cement.raysut_cement.page.raysut_dashboard.raysut_dashboard";

	// status colours, the same on the donut, tiles, table and bars
	const TONES = {
		present: { main: "#22B07D", label: __("Present") },
		absent: { main: "#FF7A6E", label: __("Absent") },
		on_leave: { main: "#5AA9F5", label: __("On leave") },
		not_marked: { main: "#FFC145", label: __("Not marked") },
	};

	// line icons (Lucide style, 24px grid)
	const ICON_PATHS = {
		grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
		clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
		calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
		left: '<path d="m15 18-6-6 6-6"/>',
		right: '<path d="m9 18 6-6-6-6"/>',
		refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
		fingerprint: '<path d="M12 11v3a8 8 0 0 1-1.5 4.7"/><path d="M8.5 7.5A5 5 0 0 1 17 11v1.5"/><path d="M7 11a5 5 0 0 1 .3-1.7"/><path d="M7 14.5a12 12 0 0 1-.8 3.5"/><path d="M16.8 16a15 15 0 0 1-1 3.5"/><path d="M5 5.5A9 9 0 0 1 21 11v1"/><path d="M3 9.5a9 9 0 0 1 .7-2"/>',
		timer: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M10 2h4"/>',
		star: '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>',
		briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18"/>',
		moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
		down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
		info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
	};
	const icon = (name, size = 18) => `<svg class="rd-icon" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"
		stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name]}</svg>`;

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const num = (v, decimals = 0) => Number(v || 0).toLocaleString("en-US", { maximumFractionDigits: decimals });
	const hours = (v) => num(v, 1);
	const as_date = (s) => moment(s, "YYYY-MM-DD");

	class RaysutDashboard {
		constructor(page) {
			this.page = page;
			this.charts = {};
			this.date = frappe.datetime.get_today();
			this.company = frappe.defaults.get_user_default("Company");
			this.$body = $(`<div class="rd"></div>`).appendTo(page.main);
			this.$body.on("click", "[data-drill]", (e) => {
				const $el = $(e.currentTarget);
				const [scope, key] = String($el.data("drill")).split(":");
				if (scope === "day") this.show_employees(key, $el.data("label"), $el.data("location"));
				else this.open_month(key);
			});
			this.$body.on("click", "[data-action]", (e) => {
				const action = $(e.currentTarget).data("action");
				if (action === "refresh") this.refresh();
				if (action === "daily") this.open_report("Daily Attendance", true);
				if (action === "consolidated") this.open_report("Consolidated Attendance");
				if (action === "prev") this.go(-1);
				if (action === "next") this.go(1);
				if (action === "pick") {
					const input = this.$body.find(".rd-date-input")[0];
					try {
						input.showPicker();
					} catch (e) {
						input.focus();
					}
				}
			});
			this.$body.on("change", ".rd-date-input", (e) => e.target.value && this.set_date(e.target.value));
			this.$body.on("change", ".rd-company", (e) => {
				this.company = e.target.value;
				this.refresh();
			});
			this.$body.on("click", ".rd-person", (e) => {
				const d = this.data;
				frappe.set_route("query-report", "Daily Attendance", {
					company: d.company, employee: $(e.currentTarget).data("employee"),
					from_date: month_start(d.date), to_date: d.date,
				});
			});
			// keep "today" fresh while the page is open
			this.timer = setInterval(() => {
				if (frappe.get_route_str().endsWith("raysut-dashboard") && this.date === frappe.datetime.get_today()) this.refresh();
			}, 5 * 60 * 1000);
		}

		go(days) {
			this.set_date(frappe.datetime.add_days(this.data ? this.data.date : this.date, days));
		}

		set_date(date) {
			this.date = date;
			this.refresh();
		}

		open_report(name, one_day = false) {
			const date = this.data ? this.data.date : this.date;
			frappe.set_route("query-report", name, {
				company: this.company,
				from_date: one_day ? date : month_start(date),
				to_date: date,
			});
		}

		refresh() {
			if (!this.data) this.$body.html(this.skeleton());
			else this.$body.addClass("rd-loading");
			frappe.call({
				method: `${METHOD}.get_dashboard`,
				args: { date: this.date, company: this.company },
				callback: ({ message }) => {
					this.$body.removeClass("rd-loading");
					if (!message) return;
					this.data = message;
					this.company = message.company;
					this.render(message);
				},
				error: () => this.$body.removeClass("rd-loading"),
			});
		}

		skeleton() {
			const block = (h, cls = "") => `<div class="rd-skel ${cls}" style="height:${h}px"></div>`;
			return `${block(64)}<div class="rd-row">${block(260, "rd-grow")}${block(260, "rd-side")}</div>${block(220)}${block(160)}`;
		}

		render(d) {
			const k = d.kpi;
			const pct = (n) => (k.active ? Math.round((100 * n) / k.active) : 0);
			this.$body.html(`
				${this.header(d)}
				${this.notice(d)}
				<div class="rd-daterow">
					<div class="rd-datenav">
						<button class="rd-btn rd-btn-round" data-action="prev" title="${__("Previous day")}">${icon("left")}</button>
						<span class="rd-datewrap">
							<button class="rd-btn rd-datepill" data-action="pick">${icon("calendar")}<span>${as_date(d.date).format("dddd, DD MMM YYYY")}</span></button>
							<input type="date" class="rd-date-input" value="${d.date}" max="${frappe.datetime.get_today()}" tabindex="-1" aria-label="${__("Date")}">
						</span>
						<button class="rd-btn rd-btn-round" data-action="next" title="${__("Next day")}">${icon("right")}</button>
					</div>
					<div class="rd-facts">
						<button class="rd-fact" data-drill="day:active" data-label="${__("Active employees")}">${__("Active employees")} <b>${num(k.active)}</b></button>
						<span class="rd-fact">${__("Punches that day")} <b>${num(d.punches.on_day)}</b></span>
					</div>
				</div>

				<div class="rd-row">
					<section class="rd-card rd-grow">
						<div class="rd-who">
							${this.donut(k)}
							<div class="rd-who-tiles">
								<h3 class="rd-card-title">${__("Who was where")}</h3>
								<div class="rd-tiles">
									${["present", "absent", "on_leave", "not_marked"].map((key) => `
										<button class="rd-tile rd-t-${key}" data-drill="day:${key}" data-label="${TONES[key].label}">
											<span class="rd-tile-label"><i class="rd-dot"></i>${TONES[key].label}</span>
											<span class="rd-tile-value">${num(k[key])}</span>
											<span class="rd-tile-sub">${key === "not_marked" ? __("no attendance yet") : __("{0}% of staff", [pct(k[key])])}</span>
										</button>`).join("")}
								</div>
							</div>
						</div>
					</section>

					<section class="rd-card rd-side">
						<h3 class="rd-card-title">${__("Needs a look")}</h3>
						<div class="rd-looks">
							${this.look("missing_punch", "fingerprint", __("Missing punch"), k.missing_punch,
								k.missing_punch ? `<span class="rd-pill rd-pill-solid">${__("Review")}</span>` : `<span class="rd-pill">${__("All complete")}</span>`)}
							${this.look("late", "timer", __("Late arrivals"), k.late,
								`<span class="rd-pill">${k.late ? __("View list") : __("All on time")}</span>`)}
							${this.look("holiday_work", "star", __("Holiday work"), k.holiday_work, `<span class="rd-pill">${__("Paid as OT2")}</span>`)}
						</div>
					</section>
				</div>

				${this.month(d)}
				${this.locations(d.locations)}

				<div class="rd-grid">
					<section class="rd-card rd-wide">
						<h3 class="rd-card-title">${__("Last {0} days", [d.trend.labels.length])}</h3>
						<div class="rd-chart" data-chart="trend"></div>
					</section>
					<section class="rd-card">
						<h3 class="rd-card-title">${__("By department")}</h3>
						<div class="rd-chart" data-chart="departments"></div>
					</section>
					<section class="rd-card">
						<h3 class="rd-card-title">${__("Overtime hours by month")}</h3>
						<div class="rd-chart" data-chart="ot"></div>
					</section>
					<section class="rd-card">
						<h3 class="rd-card-title">${__("Top overtime this month")}</h3>
						${this.people(d.top_overtime, (r) => `<td class="rd-num">${hours(r.ot1)}</td><td class="rd-num">${hours(r.ot2)}</td>`, [__("OT1"), __("OT2")])}
					</section>
					<section class="rd-card">
						<h3 class="rd-card-title">${__("Follow up that day")}</h3>
						${this.people(d.exceptions, (r) => `<td class="rd-num"><span class="rd-pill rd-pill-missing">${esc(r.issue)}</span></td>`, [__("Issue")])}
					</section>
				</div>
			`);
			this.charts_render(d);
		}

		header(d) {
			const company = d.companies.length > 1
				? `<select class="rd-eyebrow rd-company" aria-label="${__("Company")}">${d.companies.map((c) =>
					`<option value="${esc(c)}" ${c === d.company ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`
				: `<span class="rd-eyebrow">${esc(d.company)}</span>`;
			return `<header class="rd-header">
				<div class="rd-brand">
					<span class="rd-brand-icon">${icon("grid", 22)}</span>
					<div>${company}<h1 class="rd-title">${__("Attendance Dashboard")}</h1></div>
				</div>
				<nav class="rd-actions">
					<button class="rd-btn rd-btn-primary" data-action="daily">${__("Daily")}</button>
					<button class="rd-btn" data-action="consolidated">${__("Consolidated")}</button>
					<button class="rd-btn rd-btn-soft" data-action="refresh">${icon("refresh", 16)}<span>${__("Refresh")}</span></button>
				</nav>
			</header>`;
		}

		notice(d) {
			const lines = [];
			if (d.date !== d.requested_date) {
				const requested = as_date(d.requested_date);
				const what = d.requested_date === frappe.datetime.get_today()
					? __("Today ({0})", [requested.format("DD MMM")]) : requested.format("ddd, DD MMM YYYY");
				lines.push(__("{0} isn't marked yet — a day is marked once it ends. You're seeing <b>{1}</b>, the latest marked day.",
					[what, as_date(d.date).format("ddd, DD MMM YYYY")]));
			}
			// a day whose punches stop early (devices not synced since) shows everyone without a check-out
			const last = d.punches.last && moment(d.punches.last);
			if (last && last.hours() < 12 && d.kpi.missing_punch) {
				lines.push(__("Punches for this day stop at {0}: check-outs after that have not reached the system, so they show as missing punch.",
					[last.format("HH:mm")]));
			}
			return lines.map((l) => `<div class="rd-notice"><span class="rd-notice-icon">${icon("clock")}</span><span>${l}</span></div>`).join("");
		}

		donut(k) {
			const keys = ["present", "absent", "on_leave", "not_marked"];
			const total = keys.reduce((s, key) => s + (k[key] || 0), 0) || 1;
			const r = 70, c = 2 * Math.PI * r;
			const gap = keys.filter((key) => k[key]).length > 1 ? 14 : 0;  // room for the round caps
			let offset = 0;
			const arcs = keys.map((key) => {
				const len = (c * (k[key] || 0)) / total;
				const arc = len ? `<circle r="${r}" cx="90" cy="90" fill="none" stroke="${TONES[key].main}" stroke-width="20"
					stroke-linecap="round" stroke-dasharray="${Math.max(len - gap, 0.1)} ${c}" stroke-dashoffset="${-(offset + gap / 2)}"
					transform="rotate(-90 90 90)" class="rd-arc" data-drill="day:${key}" data-label="${TONES[key].label}">
					<title>${TONES[key].label}: ${num(k[key])}</title></circle>` : "";
				offset += len;
				return arc;
			}).join("");
			const pct = k.active ? Math.round((100 * k.present) / k.active) : 0;
			return `<div class="rd-donut">
				<svg viewBox="0 0 180 180" role="img" aria-label="${__("{0}% came to work", [pct])}">
					<circle r="${r}" cx="90" cy="90" fill="none" stroke="#EEEBFB" stroke-width="20"/>${arcs}
				</svg>
				<div class="rd-donut-centre"><b>${pct}%</b><span>${__("came to work")}</span></div>
			</div>`;
		}

		look(key, icon_name, label, value, pill) {
			return `<button class="rd-look rd-l-${key}" data-drill="day:${key}" data-label="${label}">
				<span class="rd-look-icon">${icon(icon_name, 20)}</span>
				<span class="rd-look-text"><span>${label}</span><b>${num(value)}</b></span>
				${pill}
			</button>`;
		}

		month(d) {
			const m = d.month;
			const tiles = [
				["worked_hours", "briefcase", __("Worked hours"), hours(m.worked_hours), "worked"],
				["ot1_hours", "clock", __("OT1 hours · normal days"), hours(m.ot1_hours), "ot1"],
				["ot2_hours", "moon", __("OT2 hours · off days & holidays"), hours(m.ot2_hours), "ot2"],
				["under_time_hours", "down", __("Under-time hours"), hours(m.under_time_hours), "under"],
				["late_days", "timer", __("Late days"), num(m.late_days), "late"],
				["missing_punch_days", "fingerprint", __("Missing-punch days"), num(m.missing_punch_days), "missing"],
			];
			const parts = [
				["worked", __("Worked"), m.worked_hours], ["ot1", __("OT1"), m.ot1_hours],
				["ot2", __("OT2"), m.ot2_hours], ["under", __("Under time"), m.under_time_hours],
			];
			const total = parts.reduce((s, p) => s + (p[2] || 0), 0);
			const share = (v) => (total ? (100 * (v || 0)) / total : 0);
			const from = as_date(month_start(d.date)), to = as_date(d.date);
			return `<section class="rd-card">
				<div class="rd-card-head">
					<h3 class="rd-card-title">${__("This month so far")}</h3>
					<span class="rd-range">${from.format("DD")} – ${to.format("DD MMM YYYY")}</span>
				</div>
				<div class="rd-stats">
					${tiles.map(([key, icon_name, label, value, tone]) => `
						<button class="rd-stat" data-drill="month:${key}" title="${__("Open the list")}">
							<span class="rd-stat-icon rd-s-${tone}">${icon(icon_name, 18)}</span>
							<span class="rd-stat-label">${label}</span>
							<span class="rd-stat-value">${value}</span>
						</button>`).join("")}
				</div>
				${total ? `<div class="rd-hours">
					<div class="rd-sub-title">${__("Where the hours went")}</div>
					<div class="rd-stack rd-stack-lg">${parts.map(([tone, label, v]) => (v ? `<span class="rd-b-${tone}"
						style="width:${share(v)}%" title="${label}: ${hours(v)}"></span>` : "")).join("")}</div>
					<div class="rd-legend">${parts.map(([tone, label, v]) => `<span><i class="rd-b-${tone}"></i>${label} ${Math.round(share(v))}%</span>`).join("")}</div>
				</div>` : ""}
			</section>`;
		}

		locations(rows) {
			const not_set = __("Not Set");
			const place = (r) => (r.name === not_set ? __("Not set") : r.name);
			const cell = (r, key, label, value) => `<td><button class="rd-count rd-c-${key}" data-drill="day:${key}" data-location="${esc(r.name)}"
				data-label="${esc(`${label} · ${place(r)}`)}">${num(value)}</button></td>`;
			const body = rows.map((r) => {
				const split = ["present", "absent", "on_leave", "not_marked"].map((key) => r[key]
					? `<span style="width:${(100 * r[key]) / r.headcount}%;background:${TONES[key].main}"></span>` : "").join("");
				return `<tr>
					<td class="rd-loc">${esc(place(r))}</td>
					${cell(r, "active", __("Staff"), r.headcount)}
					${cell(r, "present", __("Present"), r.present)}${cell(r, "absent", __("Absent"), r.absent)}
					${cell(r, "on_leave", __("On leave"), r.on_leave)}${cell(r, "not_marked", __("Not marked"), r.not_marked)}
					<td><div class="rd-split"><div class="rd-stack">${split}</div><b>${r.present_pct}%</b></div></td>
				</tr>`;
			}).join("");
			return `<section class="rd-card">
				<h3 class="rd-card-title">${__("By location")}</h3>
				${rows.length ? `<div class="rd-table-wrap"><table class="rd-table rd-loc-table">
					<thead><tr><th>${__("Location")}</th><th>${__("Staff")}</th><th>${__("Present")}</th><th>${__("Absent")}</th>
						<th>${__("Leave")}</th><th>${__("Not marked")}</th><th>${__("Split")}</th></tr></thead>
					<tbody>${body}</tbody></table></div>` : `<div class="rd-empty">${__("No employees")}</div>`}
				${rows.some((r) => r.name === not_set) ? `<div class="rd-tip">${icon("info", 16)}
					<span>${__("Tip: set a Branch on each employee to split staff by site — e.g. Raysut Plant, Duqm, Muscat.")}</span></div>` : ""}
			</section>`;
		}

		people(rows, cells, headings) {
			if (!rows.length) return `<div class="rd-empty">${__("Nothing to show")}</div>`;
			const body = rows.map((r) => `<tr class="rd-person" data-employee="${esc(r.employee)}">
				<td><div class="rd-name">${esc(r.employee_name)}</div>
					<div class="rd-dept">${esc((r.department || "").replace(/ - [A-Z]+$/, ""))}</div></td>
				${cells(r)}</tr>`).join("");
			return `<div class="rd-table-wrap"><table class="rd-table">
				<thead><tr><th>${__("Employee")}</th>${headings.map((h) => `<th class="rd-num">${h}</th>`).join("")}</tr></thead>
				<tbody>${body}</tbody></table></div>`;
		}

		charts_render(d) {
			this.chart("trend", {
				type: "bar", height: 240, barOptions: { stacked: 1, spaceRatio: 0.35 },
				colors: [TONES.present.main, TONES.absent.main, TONES.on_leave.main],
				data: { labels: d.trend.labels, datasets: [
					{ name: TONES.present.label, values: d.trend.present },
					{ name: TONES.absent.label, values: d.trend.absent },
					{ name: TONES.on_leave.label, values: d.trend.on_leave },
				] },
			});
			this.chart("departments", {
				type: "bar", height: 260, barOptions: { stacked: 1, spaceRatio: 0.3 },
				colors: [TONES.present.main, TONES.absent.main, TONES.not_marked.main],
				data: { labels: d.departments.map((r) => r.name.replace(/ - [A-Z]+$/, "")), datasets: [
					{ name: TONES.present.label, values: d.departments.map((r) => r.present) },
					{ name: TONES.absent.label, values: d.departments.map((r) => r.absent) },
					{ name: TONES.not_marked.label, values: d.departments.map((r) => r.not_marked) },
				] },
			});
			this.chart("ot", {
				type: "bar", height: 260, barOptions: { spaceRatio: 0.4 },
				colors: ["#22B07D", "#5AA9F5"],
				data: { labels: d.ot_by_month.labels, datasets: [
					{ name: __("OT1"), values: d.ot_by_month.ot1 },
					{ name: __("OT2"), values: d.ot_by_month.ot2 },
				] },
			});
		}

		chart(key, options) {
			const el = this.$body.find(`[data-chart="${key}"]`)[0];
			if (!el) return;
			if (!options.data.labels.length) {
				$(el).html(`<div class="rd-empty">${__("No data")}</div>`);
				return;
			}
			this.charts[key] = new frappe.Chart(el, { axisOptions: { xIsSeries: 1 }, ...options });
		}

		// the employees behind a figure of the day, counted exactly as on the card
		show_employees(kpi, label, location) {
			const d = this.data;
			frappe.call({
				method: `${METHOD}.get_kpi_employees`,
				args: { date: d.date, company: d.company, kpi, location: location || null },
				freeze: true,
				callback: ({ message: rows = [] }) => {
					const dialog = new frappe.ui.Dialog({
						title: `${label} · ${as_date(d.date).format("ddd, DD MMM YYYY")} (${rows.length})`,
						size: "extra-large",
						fields: [
							{ fieldtype: "Data", fieldname: "search", placeholder: __("Search name, ID, department or designation") },
							{ fieldtype: "HTML", fieldname: "list" },
						],
					});
					dialog.$wrapper.addClass("rd-dialog");
					const marked = rows.some((r) => r.attendance);
					const time = (v) => (v ? moment(v).format("HH:mm") : "");
					const $list = dialog.fields_dict.list.$wrapper;
					$list.html(rows.length ? `<div class="rd-dialog-list rd-table-wrap"><table class="rd-table">
						<thead><tr><th>#</th><th>${__("Employee")}</th><th>${__("Designation")}</th><th>${__("Status")}</th>
							<th class="rd-num">${__("In")}</th><th class="rd-num">${__("Out")}</th><th class="rd-num">${__("Hours")}</th></tr></thead>
						<tbody>${rows.map((r, i) => `<tr class="rd-row" data-attendance="${esc(r.attendance || "")}" data-employee="${esc(r.employee)}"
							data-search="${esc(`${r.employee} ${r.employee_name} ${r.department || ""} ${r.designation || ""}`.toLowerCase())}">
							<td class="rd-muted">${i + 1}</td>
							<td><div class="rd-name">${esc(r.employee_name)} <span class="rd-muted">${esc(r.employee)}</span></div>
								<div class="rd-dept">${esc((r.department || "").replace(/ - [A-Z]+$/, ""))}</div></td>
							<td>${esc(r.designation || "")}</td>
							<td>${esc(r.leave_type || r.status)}${r.missing_punch ? ` <span class="rd-pill rd-pill-missing">${__("Missing punch")}</span>` : ""}
								${r.late_minutes ? ` <span class="rd-pill rd-pill-late">${__("Late {0} min", [r.late_minutes])}</span>` : ""}</td>
							<td class="rd-num">${time(r.in_time)}</td><td class="rd-num">${time(r.out_time)}</td>
							<td class="rd-num">${r.working_hours ? num(r.working_hours, 2) : ""}</td>
						</tr>`).join("")}</tbody></table></div>`
						: `<div class="rd-empty">${__("Nobody")}</div>`);
					$list.find(".rd-row").on("click", (e) => {
						const $row = $(e.currentTarget);
						dialog.hide();
						$row.data("attendance") ? frappe.set_route("Form", "Attendance", $row.data("attendance"))
							: frappe.set_route("Form", "Employee", $row.data("employee"));
					});
					dialog.fields_dict.search.$input.on("input", (e) => {
						const q = e.target.value.toLowerCase();
						$list.find(".rd-row").each((_, tr) => $(tr).toggle(tr.dataset.search.includes(q)));
					});
					if (rows.length) {
						dialog.set_primary_action(marked ? __("Open in Attendance List") : __("Open in Employee List"), () => {
							dialog.hide();
							marked ? frappe.set_route("List", "Attendance", { name: ["in", rows.map((r) => r.attendance)] })
								: frappe.set_route("List", "Employee", { name: ["in", rows.map((r) => r.employee)] });
						});
						dialog.set_secondary_action_label(__("Daily Attendance Report"));
						dialog.set_secondary_action(() => { dialog.hide(); this.open_report("Daily Attendance", true); });
					}
					dialog.show();
				},
			});
		}

		// month figures: the matching attendance records, or the report that adds them up
		open_month(key) {
			const reports = { worked_hours: "Consolidated Attendance", under_time_hours: "Under Time" };
			if (reports[key]) return this.open_report(reports[key]);
			const d = this.data;
			const filters = {
				ot1_hours: { custom_ot1_hours: [">", 0] },
				ot2_hours: { custom_ot2_hours: [">", 0] },
				late_days: { late_entry: 1 },
				missing_punch_days: { custom_missing_punch: 1 },
			}[key];
			frappe.set_route("List", "Attendance", {
				company: d.company, docstatus: 1,
				attendance_date: ["between", [month_start(d.date), d.date]],
				...filters,
			});
		}
	}

	// frappe.datetime.month_start() always uses today, so take the month of the given date
	function month_start(date) {
		return moment(date).startOf("month").format("YYYY-MM-DD");
	}
})();
