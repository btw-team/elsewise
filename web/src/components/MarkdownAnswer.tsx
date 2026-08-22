import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";

const COMPONENTS: Components = {
  a({ children, href }) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
};

export default memo(function MarkdownAnswer({ text }: { text: string }) {
  return (
    <div className="agent-answer">
      <ReactMarkdown components={COMPONENTS}>{text}</ReactMarkdown>
    </div>
  );
});
