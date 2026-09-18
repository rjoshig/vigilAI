import { redirect } from "next/navigation";

/** Artifact types is the home screen: every other screen refers to them. */
export default function Home() {
  redirect("/artifacts");
}
