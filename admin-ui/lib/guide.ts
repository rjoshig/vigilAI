/**
 * The Guide's content model (Phase 6.19b).
 *
 * The sections themselves are generated into `guide.generated.ts` from this audience's
 * training document by `scripts/build_guides.py`. There is **one source per audience**:
 * edit the document, regenerate, commit both. `scripts/check_docs.sh` fails when the two
 * disagree, because a Guide that can drift from the training document is two documents
 * and the second one is the one nobody maintains.
 *
 * Blocks arrive already parsed, with inline emphasis resolved into spans. Neither app
 * carries a markdown renderer, and writing a regex one here would be a new class of bug
 * in a screen whose whole job is to be trustworthy.
 */

/** One run of text, with the emphasis it carries. */
export interface GuideSpan {
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
}

/** One block of a section. `kind` says how to draw it and which fields are present. */
export type GuideBlock =
  | { kind: "heading"; spans: GuideSpan[] }
  | { kind: "text"; spans: GuideSpan[] }
  | { kind: "list"; items: GuideSpan[][] }
  | { kind: "ordered"; items: GuideSpan[][] }
  | { kind: "table"; head: GuideSpan[][]; rows: GuideSpan[][][] };

/** One section of the Guide, in the order the document's markers asked for. */
export interface GuideSection {
  /** Stable within a build; used for the in-page anchor and the contents list. */
  id: string;
  title: string;
  blocks: GuideBlock[];
}
