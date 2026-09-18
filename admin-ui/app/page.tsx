import { redirect } from "next/navigation";

/** Report templates is the home screen: named values depend on them. */
export default function Home() {
  redirect("/templates");
}
