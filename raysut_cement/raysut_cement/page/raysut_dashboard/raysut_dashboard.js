// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.pages["raysut-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Raysut Dashboard"), single_column: true });
	wrapper.raysut_dashboard = new RaysutDashboard(page);
};

frappe.pages["raysut-dashboard"].on_page_show = function (wrapper) {
	wrapper.raysut_dashboard && wrapper.raysut_dashboard.refresh();
};

class RaysutDashboard {
	constructor(page) {
		this.page = page;
		this.charts = {};
		this.date = page.add_field({
			fieldname: "date", label: __("Date"), fieldtype: "Date", default: frappe.datetime.get_today(),
			change: () => this.refresh(),
		});
		this.company = page.add_field({
			fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), change: () => this.refresh(),
		});
		page.set_primary_action(__("Refresh"), () => this.refresh(), "refresh");
		page.add_inner_button(__("Daily Attendance"), () => this.open_report("Daily Attendance"));
		page.add_inner_button(__("Consolidated Attendance"), () => this.open_report("Consolidated Attendance"));

		this.$body = $(`<div class="raysut-dashboard"></div>`).appendTo(page.main);
		// keep "today" fresh while the page is open
		this.timer = setInterval(() => {
			if (frappe.get_route_str() === "raysut-dashboard" && this.date.get_value() === frappe.datetime.get_today()) this.refresh();
		}, 5 * 60 * 1000);
	}

	open_report(name, one_day = false) {
		const date = this.data ? this.data.date : this.date.get_value();
		frappe.set_route("query-report", name, {
			company: this.company.get_value(),
			from_date: one_day ? date : month_start(date),
			to_date: date,
		});
	}

	refresh() {
		frappe.call({
			method: "raysut_cement.raysut_cement.page.raysut_dashboard.raysut_dashboard.get_dashboard",
			args: { date: this.date.get_value(), company: this.company.get_value() },
			callback: ({ message }) => {
				if (!message) return;
				this.data = message;
				this.render(message);
			},
		});
	}

	render(d) {
		const k = d.kpi, m = d.month;
		const pct = (n) => (k.active ? Math.round((100 * n) / k.active) : 0);
		const day_label = frappe.datetime.str_to_user(d.date);
		const notice = d.date !== d.requested_date
			? `<div class="cd-notice">${__("No attendance marked for {0} yet (a day is marked once it has ended). Showing {1}, the latest marked day.",
				[frappe.datetime.str_to_user(d.requested_date), day_label])}</div>`
			: "";
		const holiday = d.is_holiday ? `<span class="cd-chip">${__("Weekly off / holiday")}</span>` : "";

		this.$body.html(`
			${notice}
			<div class="cd-head">
				<div>
					<div class="cd-eyebrow">${frappe.utils.escape_html(d.company)}</div>
					<h3 class="cd-title">${__("Attendance on {0}", [day_label])} ${holiday}</h3>
				</div>
				<div class="cd-sync">${__("Punches that day")}: <b>${format_number(d.punches.on_day, null, 0)}</b>
					${d.punches.last_sync ? ` · ${__("Last device sync")}: ${frappe.datetime.prettyDate(d.punches.last_sync)}` : ""}</div>
			</div>

			<div class="cd-kpis">
				${this.kpi(__("Active Employees"), k.active, "", "neutral", "day:active")}
				${this.kpi(__("Present"), k.present, `${pct(k.present)}%`, "good", "day:present")}
				${this.kpi(__("Absent"), k.absent, `${pct(k.absent)}%`, "bad", "day:absent")}
				${this.kpi(__("On Leave"), k.on_leave, `${pct(k.on_leave)}%`, "info", "day:on_leave")}
				${this.kpi(__("Not Marked"), k.not_marked, __("no attendance yet"), "warn", "day:not_marked")}
				${this.kpi(__("Late"), k.late, "", "warn", "day:late")}
				${this.kpi(__("Missing Punch"), k.missing_punch, __("needs review"), "warn", "day:missing_punch")}
				${this.kpi(__("Holiday Work"), k.holiday_work, __("paid as OT2"), "info", "day:holiday_work")}
			</div>

			<h4 class="cd-section">${__("Month to date")}</h4>
			<div class="cd-kpis cd-kpis-small">
				${this.kpi(__("Worked Hours"), m.worked_hours, "", "neutral", "month:worked_hours")}
				${this.kpi(__("OT1 Hours"), m.ot1_hours, __("normal days"), "good", "month:ot1_hours")}
				${this.kpi(__("OT2 Hours"), m.ot2_hours, __("weekly off / holidays"), "info", "month:ot2_hours")}
				${this.kpi(__("Under Time Hours"), m.under_time_hours, "", "bad", "month:under_time_hours")}
				${this.kpi(__("Late Days"), m.late_days, "", "warn", "month:late_days")}
				${this.kpi(__("Missing Punch Days"), m.missing_punch_days, "", "warn", "month:missing_punch_days")}
			</div>

			<div class="cd-grid">
				<div class="cd-card cd-wide">
					<div class="cd-card-title">${__("By location")}</div>
					${this.group_table(d.locations, __("Location"))}
				</div>
				<div class="cd-card cd-wide">
					<div class="cd-card-title">${__("Last {0} days", [d.trend.labels.length])}</div>
					<div class="cd-chart" data-chart="trend"></div>
				</div>
				<div class="cd-card">
					<div class="cd-card-title">${__("By department")}</div>
					<div class="cd-chart" data-chart="departments"></div>
				</div>
				<div class="cd-card">
					<div class="cd-card-title">${__("Overtime hours by month")}</div>
					<div class="cd-chart" data-chart="ot"></div>
				</div>
				<div class="cd-card">
					<div class="cd-card-title">${__("Top overtime this month")}</div>
					${this.people_table(d.top_overtime, (r) => `<td class="cd-num">${r.ot1}</td><td class="cd-num">${r.ot2}</td>`, [__("OT1"), __("OT2")])}
				</div>
				<div class="cd-card">
					<div class="cd-card-title">${__("Follow up today")}</div>
					${this.people_table(d.exceptions, (r) => `<td><span class="cd-chip cd-chip-warn">${frappe.utils.escape_html(r.issue)}</span></td>`, [__("Issue")])}
				</div>
			</div>
		`);

		this.chart("trend", {
			type: "bar", height: 240, barOptions: { stacked: 1, spaceRatio: 0.35 },
			colors: ["#2e9e5b", "#e05252", "#4a90d9"],
			data: { labels: d.trend.labels, datasets: [
				{ name: __("Present"), values: d.trend.present },
				{ name: __("Absent"), values: d.trend.absent },
				{ name: __("On Leave"), values: d.trend.on_leave },
			] },
		});
		this.chart("departments", {
			type: "bar", height: 260, barOptions: { stacked: 1, spaceRatio: 0.3 },
			colors: ["#2e9e5b", "#e05252", "#c7cdd4"],
			data: { labels: d.departments.map((r) => r.name.replace(/ - [A-Z]+$/, "")), datasets: [
				{ name: __("Present"), values: d.departments.map((r) => r.present) },
				{ name: __("Absent"), values: d.departments.map((r) => r.absent) },
				{ name: __("Not Marked"), values: d.departments.map((r) => r.not_marked) },
			] },
		});
		this.chart("ot", {
			type: "bar", height: 260, barOptions: { spaceRatio: 0.4 },
			colors: ["#2e9e5b", "#4a90d9"],
			data: { labels: d.ot_by_month.labels, datasets: [
				{ name: __("OT1"), values: d.ot_by_month.ot1 },
				{ name: __("OT2"), values: d.ot_by_month.ot2 },
			] },
		});

		this.$body.find(".cd-person").on("click", (e) => {
			frappe.set_route("query-report", "Daily Attendance", {
				company: d.company, employee: $(e.currentTarget).data("employee"),
				from_date: month_start(d.date), to_date: d.date,
			});
		});
		this.$body.find("[data-drill]").on("click", (e) => {
			const $el = $(e.currentTarget);
			const [scope, key] = $el.data("drill").split(":");
			if (scope === "day") this.show_employees(key, $el.data("label"), $el.data("location"));
			else this.open_month(key);
		});
	}

	// the employees behind a figure of the day, counted exactly as on the card
	show_employees(kpi, label, location) {
		const d = this.data;
		frappe.call({
			method: "raysut_cement.raysut_cement.page.raysut_dashboard.raysut_dashboard.get_kpi_employees",
			args: { date: d.date, company: d.company, kpi, location: location || null },
			freeze: true,
			callback: ({ message: rows = [] }) => {
				const dialog = new frappe.ui.Dialog({
					title: `${label} · ${frappe.datetime.str_to_user(d.date)} (${rows.length})`,
					size: "extra-large",
					fields: [
						{ fieldtype: "Data", fieldname: "search", placeholder: __("Search name, ID, department or designation") },
						{ fieldtype: "HTML", fieldname: "list" },
					],
				});
				const marked = rows.some((r) => r.attendance);
				const time = (v) => (v ? frappe.datetime.str_to_user(v).split(" ")[1].slice(0, 5) : "");
				const $list = dialog.fields_dict.list.$wrapper;
				$list.html(rows.length ? `<div class="raysut-dashboard"><div class="cd-table-wrap cd-dialog-list"><table class="cd-table cd-people">
					<thead><tr><th>#</th><th>${__("Employee")}</th><th>${__("Designation")}</th><th>${__("Status")}</th>
						<th class="cd-num">${__("In")}</th><th class="cd-num">${__("Out")}</th><th class="cd-num">${__("Hours")}</th></tr></thead>
					<tbody>${rows.map((r, i) => `<tr class="cd-row" data-attendance="${r.attendance || ""}" data-employee="${r.employee}"
						data-search="${frappe.utils.escape_html(`${r.employee} ${r.employee_name} ${r.department || ""} ${r.designation || ""}`.toLowerCase())}">
						<td class="text-muted">${i + 1}</td>
						<td><div class="cd-name">${frappe.utils.escape_html(r.employee_name)} <span class="text-muted">${r.employee}</span></div>
							<div class="cd-dept">${frappe.utils.escape_html((r.department || "").replace(/ - [A-Z]+$/, ""))}</div></td>
						<td>${frappe.utils.escape_html(r.designation || "")}</td>
						<td>${frappe.utils.escape_html(r.leave_type || r.status)}${r.missing_punch ? ` <span class="cd-chip cd-chip-warn">${__("Missing Punch")}</span>` : ""}
							${r.late_minutes ? ` <span class="cd-chip cd-chip-warn">${__("Late {0} min", [r.late_minutes])}</span>` : ""}</td>
						<td class="cd-num">${time(r.in_time)}</td><td class="cd-num">${time(r.out_time)}</td>
						<td class="cd-num">${r.working_hours ? format_number(r.working_hours, null, 2) : ""}</td>
					</tr>`).join("")}</tbody></table></div></div>`
					: `<div class="text-muted cd-empty">${__("Nobody")}</div>`);
				$list.find(".cd-row").on("click", (e) => {
					const $row = $(e.currentTarget);
					dialog.hide();
					$row.data("attendance") ? frappe.set_route("Form", "Attendance", $row.data("attendance"))
						: frappe.set_route("Form", "Employee", $row.data("employee"));
				});
				dialog.fields_dict.search.$input.on("input", (e) => {
					const q = e.target.value.toLowerCase();
					$list.find(".cd-row").each((_, tr) => $(tr).toggle(tr.dataset.search.includes(q)));
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

	kpi(label, value, sub, tone, drill) {
		return `<div class="cd-kpi cd-${tone} cd-click" data-drill="${drill}" data-label="${frappe.utils.escape_html(label)}"
			title="${__("Click to see the list")}">
			<div class="cd-kpi-label">${label}</div>
			<div class="cd-kpi-value">${format_number(value, null, value % 1 ? 1 : 0)}</div>
			<div class="cd-kpi-sub">${sub || "&nbsp;"}</div>
		</div>`;
	}

	group_table(rows, label) {
		if (!rows.length) return `<div class="text-muted">${__("No employees")}</div>`;
		const cell = (r, kpi, label, cls = "") => `<td class="cd-num cd-cell ${cls}" data-drill="day:${kpi}"
			data-location="${frappe.utils.escape_html(r.name)}" data-label="${frappe.utils.escape_html(`${label} · ${r.name}`)}">${r[kpi === "active" ? "headcount" : kpi]}</td>`;
		const body = rows.map((r) => `<tr>
			<td>${frappe.utils.escape_html(r.name)}</td>
			${cell(r, "active", __("Staff"))}
			${cell(r, "present", __("Present"), "cd-good-text")}
			${cell(r, "absent", __("Absent"), "cd-bad-text")}
			${cell(r, "on_leave", __("On Leave"))}
			${cell(r, "not_marked", __("Not Marked"))}
			<td><div class="cd-bar"><span style="width:${r.present_pct}%"></span></div><span class="cd-pct">${r.present_pct}%</span></td>
		</tr>`).join("");
		return `<div class="cd-table-wrap"><table class="cd-table">
			<thead><tr><th>${label}</th><th class="cd-num">${__("Staff")}</th><th class="cd-num">${__("Present")}</th>
				<th class="cd-num">${__("Absent")}</th><th class="cd-num">${__("Leave")}</th><th class="cd-num">${__("Not Marked")}</th>
				<th>${__("Attendance")}</th></tr></thead>
			<tbody>${body}</tbody></table></div>
			${rows.some((r) => r.name === __("Not Set")) ? `<div class="cd-hint">${__("Set Branch on the Employee to split staff by location (e.g. Raysut Plant, Duqm, Muscat).")}</div>` : ""}`;
	}

	people_table(rows, cells, headings) {
		if (!rows.length) return `<div class="text-muted cd-empty">${__("Nothing to show")}</div>`;
		const body = rows.map((r) => `<tr class="cd-person" data-employee="${frappe.utils.escape_html(r.employee)}">
			<td><div class="cd-name">${frappe.utils.escape_html(r.employee_name)}</div>
				<div class="cd-dept">${frappe.utils.escape_html((r.department || "").replace(/ - [A-Z]+$/, ""))}</div></td>
			${cells(r)}</tr>`).join("");
		return `<div class="cd-table-wrap"><table class="cd-table cd-people">
			<thead><tr><th>${__("Employee")}</th>${headings.map((h) => `<th class="cd-num">${h}</th>`).join("")}</tr></thead>
			<tbody>${body}</tbody></table></div>`;
	}

	chart(key, options) {
		const el = this.$body.find(`[data-chart="${key}"]`)[0];
		if (!el) return;
		if (!options.data.labels.length) {
			$(el).html(`<div class="text-muted cd-empty">${__("No data")}</div>`);
			return;
		}
		this.charts[key] = new frappe.Chart(el, { axisOptions: { xIsSeries: 1 }, ...options });
	}
}

// frappe.datetime.month_start() always uses today, so take the month of the given date
function month_start(date) {
	return moment(date).startOf("month").format("YYYY-MM-DD");
}
