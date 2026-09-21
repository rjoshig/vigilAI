"use client";

/**
 * The Guide (Phase 6.19b).
 *
 * The rollout plan asks the senior associates to deliver an hour of training per region.
 * An hour teaches how to click. It cannot teach the things that actually decide whether
 * the tool is worth having — which fields are worth writing carefully, what the tool is
 * not looking at, and when to disagree with it — so those live here, on a screen the
 * person already has open, rather than in a document nobody opens twice.
 *
 * The content is generated from `docs/user-training.md`, so there is one source and the
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
        description="What the tool is doing on your behalf, what it needs from you, and what it will not catch. Written for your first week; useful in your tenth."
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
