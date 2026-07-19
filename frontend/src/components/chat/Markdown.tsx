import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import python from "highlight.js/lib/languages/python";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";
import { memo } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

// highlight.js registers ~190 languages by default, which is most of a
// megabyte for grammars nobody in this app will use. These cover what a
// document-grounded assistant actually emits; anything else renders as plain
// monospace, which is a fine outcome.
const LANGUAGES = { python, typescript, javascript: typescript, bash, json, yaml, sql, xml };

/** Renders an answer's markdown.
 *
 *  Memoized on the text because streaming re-renders this on every token, and
 *  re-parsing the whole document each time is what makes a stream feel slow.
 *  GFM adds the tables the agent is told it may use. */
export const Markdown = memo(function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { languages: LANGUAGES, detect: true }]]}
        components={{
          // Links from a model can point anywhere: open them in a new tab and
          // strip the opener reference.
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
});
