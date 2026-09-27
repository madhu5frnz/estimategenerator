import { Suspense } from "react";

import { ResetForm } from "./ResetForm";

export const metadata = { title: "Set a new password" };

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
