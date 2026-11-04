// Desktop (/desk) shortcuts for the group companies: Raysut, Pioneer and Sohar each get a tile
// that opens the same Attendance Dashboard with the Company filter set to that company.
// The Apps screen shows one tile per app, so the Pioneer and Sohar tiles are added next to the
// Raysut tile when the desktop is drawn ("desktop_screen" is fired by the v16 desktop page).

const RC_SHORTCUTS = [
	{ label: "Raysut Cement", company: "Raysut Cement", logo: "raysut-cement-logo.png" },
	{ label: "Pioneer Cement", company: "Pioneer Cement", logo: "pioneer-cement-logo.png" },
	{ label: "Sohar Cement", company: "Sohar Cement", logo: "sohar-cement-logo.png" },
];

const rc_route = (company) => `/desk/raysut-dashboard?company=${encodeURIComponent(company)}`;

$(document).on("desktop_screen", (e, { desktop } = {}) => {
	// only the Apps screen; the Desktop Icons grid has its own icons
	if (!desktop || frappe.boot.desktop_page === "Desktop Icons" || !desktop.add_icon) return;
	const $grid = desktop.wrapper && desktop.wrapper.find(".icons").first();
	if (!$grid || !$grid.length || $grid.find(".rc-shortcut").length) return;

	// the Raysut app tile is there only for users allowed into the app
	const $raysut = $grid
		.children(".desktop-icon")
		.filter((i, el) => ($(el).find("img.app-icon").attr("src") || "").includes(RC_SHORTCUTS[0].logo))
		.first();
	if (!$raysut.length) return;

	$raysut.addClass("rc-shortcut").find(".icon-link, .icon-title").attr("href", rc_route(RC_SHORTCUTS[0].company));

	let $after = $raysut;
	RC_SHORTCUTS.slice(1).forEach((s) => {
		desktop.add_icon(
			$grid,
			{ label: s.label, logo_url: `/assets/raysut_cement/images/${s.logo}` },
			rc_route(s.company)
		);
		const $tile = $grid.children(".desktop-icon").last().addClass("rc-shortcut");
		$tile.find('[data-toggle="tooltip"]').tooltip({ placement: "bottom" });
		$tile.insertAfter($after);
		$after = $tile;
	});
});
