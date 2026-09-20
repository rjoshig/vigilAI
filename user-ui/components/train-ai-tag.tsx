/**
 * The mark on every control that exists only because Train AI mode is on (6.4a).
 *
 * The mode records what people write. The tag says so at the point of writing, so a
 * person can tell at a glance which parts of the screen are collecting their words.
 * The configuration-note field carries no tag: notes exist whatever the mode says.
 */

import { Badge } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/** What the mode does, in one sentence. Shared with the sidebar indicator. */
export const TRAIN_AI_HINT =
  "What you write in the training controls is recorded and reviewed by an administrator before it changes anything.";

/** The tag's text, shared so a test names it once. */
export const TRAIN_AI_TAG_LABEL = "Train AI";

export interface TrainAiTagProps {
  className?: string;
}

export function TrainAiTag({ className }: TrainAiTagProps) {
  return (
    <Badge
      tone="info"
      title={TRAIN_AI_HINT}
      className={cn("px-1.5 py-0 text-[0.625rem] uppercase tracking-wide", className)}
    >
      {TRAIN_AI_TAG_LABEL}
    </Badge>
  );
}
