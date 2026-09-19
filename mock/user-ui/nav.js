/* user-ui nav — brand + menu for the user app mock. Synthetic only. */
window.MOCK_APP = {
  kind: "user",
  brand: { name: "Greenlight AI", tagline: "USER", subtitle: "Nothing ships without a green light." },
  nav: [
    { page: "runs", label: "Runs", href: "index.html", icon: "runs" },
    { page: "new-run", label: "New run", href: "new-run.html", icon: "plus" },
    { page: "review", label: "Review", href: "review.html", icon: "review", count: 3 },
    { page: "report", label: "Final report", href: "report.html", icon: "report" },
    { page: "stats", label: "Run stats", href: "run-stats.html", icon: "stats" },
    { page: "configs", label: "Config history", href: "config-history.html", icon: "config" },
  ],
};
