/** Project open, no thread yet: hero + composer; the first send creates the
 * thread (POST /api/threads/send without thread_id) and navigates to it. */
import { BrandMark } from "./Brand";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { sendMessage } from "../lib/wbApi";
import type { AttachmentRef } from "../lib/wbTypes";
import { zh } from "../lib/zh";
import { useWorkbench } from "../state/WorkbenchProvider";
import { useCrystal } from "../state/CrystalProvider";
import { Composer } from "./composer/Composer";
import { OpenProjectDialog } from "./sidebar/OpenProjectDialog";
import { StorageCard } from "./StorageCard";
import { projectLabel, threadUrl } from "./urls";

export function ProjectHome({ project }: { project: string }) {
  const wb = useWorkbench();
  const { state } = useCrystal();
  const structureOnly = state.nodes.find((node) => node.id === state.activeNode)?.structure_only === true;
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);

  const onSend = async (
    text: string,
    attachments?: AttachmentRef[],
  ): Promise<string | null> => {
    try {
      const res = await sendMessage({ project, message: text, attachments });
      void wb.refreshThreads();
      navigate(threadUrl(res.thread_id, project));
      return null;
    } catch (e) {
      return e instanceof Error ? e.message : String(e);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-6">
        <div className="w-full max-w-2xl py-10 text-center">
          <BrandMark variant="app" size={56} className="mx-auto mb-4" />
          <h1 className="text-4xl leading-snug font-semibold tracking-tight text-balance">
            {structureOnly ? zh.structureOnlyTitle : zh.heroTitle}
          </h1>
          <p className="mt-2.5 text-base text-ink-2">
            {projectLabel(project, wb.settings?.display_name)} · {structureOnly ? zh.cifImportHint : zh.projectHeroSubtitle}
          </p>
          <p className="mt-2 text-xs text-ink-3" data-testid="new-thread-target">
            {zh.newThreadIn} <span className="font-mono">{project}</span> ·{" "}
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="underline decoration-line underline-offset-2 transition-colors hover:text-ink"
            >
              {zh.changeProject}
            </button>
          </p>
          <StorageCard project={project} />
        </div>
      </div>
      <div className="shrink-0 px-6 pb-8">
        <div className="mx-auto w-full max-w-3xl">
          <Composer onSend={onSend} autoFocus />
        </div>
      </div>
      {dialogOpen && <OpenProjectDialog onClose={() => setDialogOpen(false)} />}
    </div>
  );
}
