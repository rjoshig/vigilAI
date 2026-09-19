/* admin-ui nav — brand + menu for the admin app mock. Synthetic only. */
window.MOCK_APP = {
  kind: "admin",
  brand: { name: "Greenlight Admin Console", tagline: "ADMIN", subtitle: "Nothing ships without a green light." },
  nav: [
    { page: "templates", label: "Report templates", href: "index.html", icon: "template" },
    { page: "checks", label: "Checks", href: "checks.html", icon: "check" },
    { page: "compliance", label: "Compliance & scope", href: "compliance.html", icon: "shield" },
    { page: "reference", label: "Reference data", href: "reference.html", icon: "book" },
    { page: "usage", label: "Usage", href: "usage.html", icon: "gauge" },
  ],
};
