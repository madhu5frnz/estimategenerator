import { Suspense } from "react";

import { ProjectList } from "./ProjectList";

export const metadata = { title: "Projects" };

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectList />
    </Suspense>
  );
}
