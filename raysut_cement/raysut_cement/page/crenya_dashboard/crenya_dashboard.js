// Copyright (c) 2026, sammish and contributors
// For license information, please see license.txt

frappe.pages["crenya-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Crenya Dashboard"), single_column: true });
	wrapper.crenya_dashboard = new CrenyaDashboard(page);
};

frappe.pages["crenya-dashboard"].on_page_show = function (wrapper) {
	wrapper.crenya_dashboard && wrapper.crenya_dashboard.refresh();
};

class CrenyaDashboard {
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

		this.$body = $(`<div class="crenya-dashboard"></div>`).appendTo(page.main);
		// keep "today" fresh while the page is open
		this.timer = setInterval(() => {
			if (frappe.get_route_str() === "crenya-dashboard" && this.date.get_value() === frappe.datetime.get_today()) this.refresh();
		}, 5 * 60 * 1000);
	}

	open_report(name) {
		const date = this.data ? this.data.date : this.date.get_value();
		frappe.set_route("query-report", name, {
			company: this.company.get_value(),
			from_date: frappe.datetime.month_start(date),
			to_date: date,
		});
	}

	refresh() {
		frappe.call({
			method: "raysut_cement.raysut_cement.page.crenya_dashboard.crenya_dashboard.get_dashboard",
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
				${this.kpi(__("Active Employees"), k.active, "", "neutral")}
				${this.kpi(__("Present"), k.present, `${pct(k.present)}%`, "good")}
				${this.kpi(__("Absent"), k.absent, `${pct(k.absent)}%`, "bad")}
				${this.kpi(__("On Leave"), k.on_leave, `${pct(k.on_leave)}%`, "info")}
				${this.kpi(__("Not Marked"), k.not_marked, __("no attendance yet"), "warn")}
				${this.kpi(__("Late"), k.late, "", "warn")}
				${this.kpi(__("Missing Punch"), k.missing_punch, __("needs review"), "warn")}
				${this.kpi(__("Holiday Work"), k.holiday_work, __("paid as OT2"), "info")}
			</div>

			<h4 class="cd-section">${__("Month to date")}</h4>
			<div class="cd-kpis cd-kpis-small">
				${this.kpi(__("Worked Hours"), m.worked_hours, "", "neutral")}
				${this.kpi(__("OT1 Hours"), m.ot1_hours, __("normal days"), "good")}
				${this.kpi(__("OT2 Hours"), m.ot2_hours, __("weekly off / holidays"), "info")}
				${this.kpi(__("Under Time Hours"), m.under_time_hours, "", "bad")}
				${this.kpi(__("Late Days"), m.late_days, "", "warn")}
				${this.kpi(__("Missing Punch Days"), m.missing_punch_days, "", "warn")}
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
				from_date: frappe.datetime.month_start(d.date), to_date: d.date,
			});
		});
	}

	kpi(label, value, sub, tone) {
		return `<div class="cd-kpi cd-${tone}">
			<div class="cd-kpi-label">${label}</div>
			<div class="cd-kpi-value">${format_number(value, null, value % 1 ? 1 : 0)}</div>
			<div class="cd-kpi-sub">${sub || "&nbsp;"}</div>
		</div>`;
	}

	group_table(rows, label) {
		if (!rows.length) return `<div class="text-muted">${__("No employees")}</div>`;
		const body = rows.map((r) => `<tr>
			<td>${frappe.utils.escape_html(r.name)}</td>
			<td class="cd-num">${r.headcount}</td>
			<td class="cd-num cd-good-text">${r.present}</td>
			<td class="cd-num cd-bad-text">${r.absent}</td>
			<td class="cd-num">${r.on_leave}</td>
			<td class="cd-num">${r.not_marked}</td>
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
