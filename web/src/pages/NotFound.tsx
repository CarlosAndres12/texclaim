import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common";

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<Compass />}
      title={t("app.notFound")}
      body={t("app.notFoundBody")}
      action={<Button asChild><Link to="/">{t("app.goHome")}</Link></Button>}
    />
  );
}
