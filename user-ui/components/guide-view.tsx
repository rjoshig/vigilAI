"use client";

/**
 * The Guide, rendered (Phase 6.19b).
 *
 * Shared by both apps, with each one passing its own generated sections. The renderer is
 * deliberately small: blocks arrive already parsed, so this decides how a heading, a
 * paragraph, a list and a table look, and nothing else. No markdown is interpreted here.
 *
 * The contents list is not decoration. The whole point of the Guide is that somebody
 * arrives with a question rather than reading it front to back, so the questions have to
 * be visible in one screen before any of the answers are.
 */

import * as React from "react";

import type { GuideBlock, GuideSection, GuideSpan } from "@/lib/guide";

/** One run of text, with whatever emphasis it carries. */
function Spans({ spans }: { spans: GuideSpan[] }) {
  return (
    <>
      {spans.map((span, index) => {
        if (span.code) {
          return (
            <code key={index} className="mono rounded bg-muted px-1 py-0.5 text-[0.85em]">
              {span.text}
            </code>
          );
        }
        if (span.bold) {
          return (
            <strong key={index} className="font-semibold text-foreground">
              {span.text}
            </strong>
          );
        }
        if (span.italic) {
          return <em key={index}>{span.text}</em>;
        }
        return <React.Fragment key={index}>{span.text}</React.Fragment>;
      })}
    </>
  );
}

function Block({ block }: { block: GuideBlock }) {
  switch (block.kind) {
    case "heading":
      return (
        <h3 className="mt-5 text-sm font-semibold text-foreground">
          <Spans spans={block.spans} />
        </h3>
      );
    case "text":
      return (
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          <Spans spans={block.spans} />
        </p>
      );
    case "list":
      return (
        <ul className="mt-3 flex flex-col gap-1.5 pl-5 text-sm leading-relaxed text-muted-foreground">
          {block.items.map((item, index) => (
            <li key={index} className="list-disc">
              <Spans spans={item} />
            </li>
          ))}
        </ul>
      );
    case "ordered":
      return (
        <ol className="mt-3 flex flex-col gap-1.5 pl-5 text-sm leading-relaxed text-muted-foreground">
          {block.items.map((item, index) => (
            <li key={index} className="list-decimal">
              <Spans spans={item} />
            </li>
          ))}
        </ol>
      );
    case "table":
      return (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {block.head.map((cell, index) => (
                  <th
                    key={index}
                    className="border-b px-2 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                  >
                    <Spans spans={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, index) => (
                    <td
                      key={index}
                      className="border-b px-2 py-1.5 align-top leading-relaxed text-muted-foreground"
                    >
                      <Spans spans={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
  }
}

/**
 * The Guide.
 *
 * @param sections The generated sections for this app's audience.
 */
export function GuideView({ sections }: { sections: GuideSection[] }) {
  return (
    <div className="flex flex-col gap-6">
      <nav aria-label="What this guide answers" className="rounded-lg border bg-card p-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          What this answers
        </div>
        <ol className="mt-2 flex flex-col gap-1 text-sm">
          {sections.map((section) => (
            <li key={section.id}>
              <a className="text-primary hover:underline" href={`#${section.id}`}>
                {section.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      {sections.map((section) => (
        <section key={section.id} id={section.id} className="scroll-mt-6">
          <h2 className="border-b pb-1.5 text-base font-semibold tracking-tight">
            {section.title}
          </h2>
          {section.blocks.map((block, index) => (
            <Block key={index} block={block} />
          ))}
        </section>
      ))}
    </div>
  );
}
