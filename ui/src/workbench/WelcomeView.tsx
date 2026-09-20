/** No project open: centered hero + the project status board + dialog. */
import { BrandMark } from "./Brand";
import { useState } from "react";
import { t } from "../lib/i18n";
import { IconPlus } from "./icons";
import { ProjectStatusBoard } from "./ProjectStatusBoard";
import { OpenProjectDialog } from "./sidebar/OpenProjectDialog";

export function WelcomeView() {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-6">
      {/* wider than the hero needs: the status board carries four metrics
          per card and two 288px columns squeezed them */}
      <div className="w-full max-w-3xl py-12 text-center">
        <BrandMark variant="app" size={72} className="mx-auto mb-5" />
        <h1 className="mx-auto max-w-xl text-4xl leading-snug font-semibold tracking-tight text-balance">
          {t.heroTitle}
        </h1>
        <p className="mx-auto mt-2.5 max-w-xl text-base text-ink-2">
          {t.heroSubtitle}
        </p>

        <div className="mt-8 flex justify-center">
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="flex h-10 items-center gap-2 rounded-pill bg-ink px-5 text-sm font-medium text-bg transition-opacity hover:opacity-85"
          >
            <IconPlus size={15} />
            {t.openProject}
          </button>
        </div>

        <ProjectStatusBoard />
      </div>
      {dialogOpen && <OpenProjectDialog onClose={() => setDialogOpen(false)} />}
    </div>
  );
}
