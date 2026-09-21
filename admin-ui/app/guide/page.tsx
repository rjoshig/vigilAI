"use client";

/**
 * The Guide (Phase 6.19b).
 *
 * Administering this tool is a different job from using it, and the part that is hard to
 * learn is not where the buttons are: it is choosing between five surfaces that can each
 * express the same rule, knowing which of the things you could do is worth doing first,
 * and reading the numbers honestly. Those live here, on a screen an administrator already
 * has open, rather than in a document nobody opens twice.
 *
 * The content is generated from `docs/admin-training.md`, so there is one source and the
 * two cannot drift. Offered only while the Guide is switched on (`ui.guide`).
 */

import * as React from "react";

import { GuideView } from "@/components/guide-view";
import { usePalette } from "@/components/palette-provider";
import { EmptyState, PageHeader } from "@/components/ui/primitives";
import { GUIDE } from "@/lib/guide.generated";

export default function GuidePage() {
  const { guide } = usePalette();

  return (
    <>
      <PageHeader
        title="Guide"
        description="Which surface a thing belongs on, what improves the QC in the order it pays off, what the numbers mean, and who may do what. Written for the job of running this deployment, which is a different job from using it."
      />
      {guide ? (
        <GuideView sections={GUIDE} />
      ) : (
        <EmptyState
          title="The Guide is switched off"
          hint="An administrator has turned it off for this deployment, usually because training is delivered another way. Ask them if you need it."
        />
      )}
    </>
  );
}
