import { redirect } from "next/navigation";

/** The Runs list is the home screen. */
export default function Home() {
  redirect("/runs");
}
